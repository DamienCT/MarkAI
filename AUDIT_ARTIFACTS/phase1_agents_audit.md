# Phase 1: Agents Service Audit

**Date:** 2026-03-30
**Scope:** All Python files in `D:\MarkAI\agents\` (48 files)
**Auditor:** Claude Opus 4.6

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 5 |
| HIGH | 14 |
| MEDIUM | 19 |
| LOW | 12 |
| **Total** | **50** |

---

## CRITICAL Findings

### C1. SQL Injection via `execute_query` — Arbitrary Query Execution
- **File:** `agents/shared/tools/database.py`, lines 517-520
- **Category:** Security
- **Description:** `execute_query()` accepts a raw SQL string and executes it. Multiple callers construct queries with string interpolation or pass caller-controlled queries. In `worker.py` line 123-126, the function is called with a hardcoded query (safe), but the function itself is a generic query executor that any future caller could misuse. More critically, `execute_update()` (lines 523-531) exposes write access with the same pattern. Any workflow node that constructs queries from LLM output or user input could inject SQL.
- **Proposed Fix:** Restrict `execute_query`/`execute_update` to accept only parameterized queries. Add an allowlist of query patterns or replace with purpose-built DAO methods. Add a code review gate prohibiting raw SQL construction outside `database.py`.

### C2. Unbounded LLM Output Trusted as SQL/Logic — No Schema Validation
- **File:** `agents/workflows/planning/nodes.py`, lines 237-239; `agents/workflows/content/nodes.py`, lines 367-370
- **Category:** Security / Bug
- **Description:** LLM-generated JSON is parsed via `parse_llm_json()` and then directly used to construct database records (e.g., `store_calendar_items`, `store_content`). If the LLM returns unexpected field types (e.g., nested objects where strings are expected, or excessively long strings), the database insert can fail with an unhandled exception or store corrupt data. There is no schema validation between LLM output parsing and database writes.
- **Proposed Fix:** Add Pydantic models (or similar validation) between `parse_llm_json()` and all database operations. Validate field types, lengths, and allowed values before passing to `store_*` functions.

### C3. MemorySaver Checkpointer in Production — Unbounded Memory Growth
- **File:** `agents/workflows/strategy/graph.py`, line 45; `agents/workflows/adaptation/graph.py`, line 35
- **Category:** Performance / Reliability
- **Description:** `MemorySaver()` stores all checkpoint state in-memory. In production, each strategy/adaptation graph invocation accumulates state that is never cleaned up. Over time (or under load), this will cause the worker process to OOM. MemorySaver is intended for development/testing only.
- **Proposed Fix:** Replace `MemorySaver()` with a persistent checkpointer (e.g., `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`) that uses the existing Postgres database. This also enables proper graph resume after worker restarts.

### C4. Race Condition in Idempotency Check — TOCTOU Window
- **File:** `agents/worker.py`, lines 121-136
- **Category:** Bug / Reliability
- **Description:** The duplicate workflow check (`SELECT ... WHERE status = 'running'`) and the subsequent `create_agent_run()` are not atomic. Two NATS messages for the same brand/agent_type can both pass the check before either inserts a row. The `pass` on exception (line 136) silently ignores failures, meaning the idempotency check could also silently fail entirely.
- **Proposed Fix:** Use a database-level unique constraint or advisory lock. For example: `INSERT INTO agent_runs ... ON CONFLICT DO NOTHING` with a partial unique index on `(brand_id, agent_type) WHERE status = 'running' AND started_at > NOW() - INTERVAL '30 minutes'`. Or use PostgreSQL advisory locks keyed on `(brand_id, agent_type)`.

### C5. Adaptation Workflow `get_pending_adaptations` Queries Wrong Schema
- **File:** `agents/shared/tools/database.py`, lines 492-503
- **Category:** Bug
- **Description:** `get_pending_adaptations()` JOINs `adaptations a` on `content c ON a.source_content_id = c.id`, but `store_adaptations()` (lines 437-489) can insert records using the evaluation-node schema which has `brand_id` directly on the adaptation and **no** `source_content_id`. These records will never be returned by `get_pending_adaptations()`, making the entire adaptation->apply workflow a no-op for evaluation-generated adaptations.
- **Proposed Fix:** Rewrite `get_pending_adaptations()` to query both schemas:
  ```sql
  SELECT * FROM adaptations WHERE brand_id = :brand_id AND status IN ('pending', 'auto_applied')
  UNION
  SELECT a.* FROM adaptations a JOIN content c ON a.source_content_id = c.id
  WHERE c.brand_id = :brand_id AND a.status = 'proposed'
  ```

---

## HIGH Findings

### H1. Global Mutable `_HEADERS` Dict — Thread Safety Issue
- **File:** `agents/shared/llm.py`, lines 36, 52-56
- **Category:** Bug
- **Description:** `_HEADERS` is a mutable module-level dict populated lazily on first call. In a concurrent async environment, multiple coroutines could call `_auth_headers()` simultaneously on startup, causing a race condition. While dict operations in CPython are GIL-protected, this is an anti-pattern that could cause subtle issues with key rotation or config changes.
- **Proposed Fix:** Initialize `_HEADERS` eagerly at module level or use a lock. Better yet, construct headers fresh each call (the performance cost is negligible compared to HTTP calls).

### H2. `_model_cache` Not Thread-Safe — Stale/Inconsistent Reads
- **File:** `agents/shared/llm.py`, lines 38-40
- **Category:** Bug
- **Description:** `_model_cache` is a plain dict with tuple values accessed from multiple concurrent coroutines. While asyncio is single-threaded, `await` points in `get_model_for_category()` allow interleaving. Two coroutines could both see an expired cache entry and both make HTTP requests to the backend.
- **Proposed Fix:** Use `asyncio.Lock` around the cache read-write section, or accept the minor double-fetch as harmless (document it).

### H3. `httpx.AsyncClient` Created Per-Request — Connection Pool Not Reused
- **File:** `agents/shared/llm.py`, lines 167, 204, 242; `agents/shared/tools/browser.py`, lines 61, 88, 100, 118, 131; `agents/shared/tools/social.py` (all functions); `agents/shared/tools/fabric.py`, line 39
- **Category:** Performance
- **Description:** Every LLM call, embedding request, image generation, browser-worker call, social API call, and Fabric token request creates a new `httpx.AsyncClient`, establishing a new TCP connection each time. This adds ~50-100ms per request from TLS handshake overhead and prevents HTTP/2 multiplexing.
- **Proposed Fix:** Create module-level `httpx.AsyncClient` instances with appropriate connection pooling. For the LiteLLM client, create one shared client with `limits=httpx.Limits(max_keepalive_connections=20)`. Ensure proper cleanup on shutdown.

### H4. Temp Files Not Cleaned Up on Exception in `render_logo_png`
- **File:** `agents/shared/image_processing.py`, lines 66-84
- **Category:** Reliability
- **Description:** `tempfile.NamedTemporaryFile(delete=False)` creates a file that must be manually cleaned up. The `finally` block handles the happy path, but if the process crashes between file creation and the try/finally block, the temp file leaks. Also, `png_path = svg_path.replace(".svg", ".png")` (line 70) assumes the path contains `.svg` and that the replacement file exists before the `finally` block tries to delete it.
- **Proposed Fix:** Use `tempfile.TemporaryDirectory()` as context manager, or move `delete=False` temp file creation inside the try block so cleanup is guaranteed.

### H5. `store_competitors` — N+1 Query Pattern
- **File:** `agents/shared/tools/database.py`, lines 181-211
- **Category:** Performance
- **Description:** For each competitor in the list, `store_competitors` executes a SELECT to check existence, then an INSERT if new. With 5 competitors this is 10 queries. This should be a single upsert.
- **Proposed Fix:** Use `INSERT ... ON CONFLICT (brand_id, LOWER(name)) DO NOTHING` (requires a unique index) or batch the operations.

### H6. `source_product_images_node` — Sequential Image Sourcing, No Parallelism
- **File:** `agents/workflows/product_intel/nodes.py`, lines 160-186
- **Category:** Performance
- **Description:** Product images are sourced sequentially in a for-loop. Each iteration makes 1-3 HTTP requests (BC lookup, supplier scrape, web search). With 500 products, this could take hours.
- **Proposed Fix:** Use `asyncio.gather()` with a semaphore to process images in parallel (e.g., 10 concurrent).

### H7. `research_brand` — Sequential Brand Research, No Parallelism
- **File:** `agents/workflows/product_intel/nodes.py`, lines 73-116
- **Category:** Performance
- **Description:** Same sequential pattern as H6. Each brand is researched one at a time with web search + page extraction + LLM call.
- **Proposed Fix:** Use `asyncio.gather()` with concurrency limit.

### H8. Worker Chain Error Overwrites Successful Result
- **File:** `agents/worker.py`, lines 314-322
- **Category:** Bug
- **Description:** If the workflow succeeds but the chain publish fails, the code calls `complete_agent_run()` again with status "completed" (line 321), overwriting the already-stored successful result with a version that includes `_chain_error`. But `complete_agent_run()` was already called on line 160. The second call sets `completed_at` again to a later time, which is misleading.
- **Proposed Fix:** Instead of calling `complete_agent_run()` again, use a separate update to append chain error metadata: `execute_update("UPDATE agent_runs SET output_payload = ... WHERE id = :id", ...)`.

### H9. `load_adaptations` Returns `status: "no_pending"` — Breaks `_check_failed` Pattern
- **File:** `agents/workflows/adaptation/nodes.py`, lines 22-28
- **Category:** Bug
- **Description:** When no pending adaptations exist, the node returns `{"status": "no_pending"}`. The `_check_failed` router only checks for `status == "failed"`, so the graph continues through `apply_tier1`, `propose_tier2`, `propose_tier3` with empty lists. This is harmless but the `propose_tier2`/`propose_tier3` functions don't short-circuit before `interrupt()` — they check `if not tier2: return {}` which works. However, the `status: "no_pending"` value persists in state and is returned as the final workflow status, which is non-standard (not "completed", "failed", etc.).
- **Proposed Fix:** Return `{"status": "completed", "adaptations": []}` when no pending adaptations exist to match the expected status values.

### H10. `get_pending_adaptations` Returns Adaptations with `status = 'proposed'` Only
- **File:** `agents/shared/tools/database.py`, lines 492-503; `agents/workflows/evaluation/nodes.py`, line 118
- **Category:** Bug
- **Description:** `store_adaptations_node` in evaluation sets tier1 adaptations to `status: "auto_applied"` (line 118). `get_pending_adaptations()` only queries `status = 'proposed'`. So tier1 adaptations set to "auto_applied" by evaluation are never picked up by the adaptation workflow.
- **Proposed Fix:** Either change evaluation to set tier1 status to "pending" (let the adaptation workflow apply them), or change `get_pending_adaptations()` to also include `status = 'auto_applied'`.

### H11. Adaptation `propose_tier2`/`propose_tier3` — `interrupt()` Called Without Checkpointer Check
- **File:** `agents/workflows/adaptation/nodes.py`, lines 71, 118
- **Category:** Reliability
- **Description:** `interrupt()` requires a checkpointer to be configured on the graph. The adaptation graph does use `MemorySaver()`, but if the worker process restarts between the interrupt and resume, all checkpoint state is lost (see C3). The tier2/tier3 adaptations would be stuck in "proposed" status forever since there is no mechanism to detect and recover stale interrupted runs.
- **Proposed Fix:** Use persistent checkpointer (see C3). Add a cleanup job that detects interrupted runs older than X hours and either auto-rejects or re-queues them.

### H12. `strategy/nodes.py` — `research_data` May Be String Instead of Dict
- **File:** `agents/workflows/strategy/nodes.py`, lines 22-25
- **Category:** Bug
- **Description:** `get_latest_research()` returns an `agent_runs` row whose `output_payload` column may be a JSON string (depending on how SQLAlchemy/asyncpg handles JSONB). Line 25 does `research.get("output_payload", research)` — if `output_payload` is a string, the entire strategy workflow gets a string instead of a dict, and all subsequent `.get()` calls on it will fail or return defaults.
- **Proposed Fix:** Parse `output_payload` through `_parse_payload()` (already exists in database.py) before returning:
  ```python
  return {"research_data": _parse_payload(research.get("output_payload", research))}
  ```

### H13. Content `load_context` Stores Extra Keys Not in `ContentState` TypedDict
- **File:** `agents/workflows/content/nodes.py`, lines 133-144
- **Category:** Quality / Bug
- **Description:** `load_context` returns keys like `positioning`, `relevant_pillar`, `relevant_audience`, `month_context`, `recent_posts`, `top_performing`, `product` — but these are NOT defined in `ContentState` TypedDict. LangGraph TypedDict states only accept declared keys. Undeclared keys may be silently dropped depending on the LangGraph version, causing downstream nodes to get empty dicts.
- **Proposed Fix:** Add all these fields to `ContentState` TypedDict in `content/state.py`.

### H14. `web_search` HTML Parsing Fragile — Regex on DDG HTML
- **File:** `agents/shared/tools/web_search.py`, lines 44-57
- **Category:** Reliability
- **Description:** The web search tool parses DuckDuckGo HTML using regex patterns. DDG frequently changes their HTML structure, and any change would silently return 0 results, breaking the research workflow. The regex patterns target specific CSS classes that could change at any time.
- **Proposed Fix:** Use the `duckduckgo-search` Python library which uses DDG's API endpoint, or add a test that validates the regex still works against a live query. Add a warning log when 0 results are returned for a non-empty query.

---

## MEDIUM Findings

### M1. `validate_llm_output` Only Checks First List Item
- **File:** `agents/shared/llm.py`, lines 125-141
- **Category:** Bug
- **Description:** When `expect_list=True`, the validation only checks `required_fields` against `data[0]`. All subsequent items could be missing required fields and would pass validation.
- **Proposed Fix:** Check all items in the list, or at minimum log a warning if the list has heterogeneous structures.

### M2. `_auth_headers` Caches Headers Forever — No Key Rotation Support
- **File:** `agents/shared/llm.py`, lines 36, 52-56
- **Category:** Security
- **Description:** If `LITELLM_MASTER_KEY` changes at runtime (e.g., secret rotation), the cached headers will never be updated. The process must be restarted.
- **Proposed Fix:** Construct headers fresh each call, or add a TTL to the header cache.

### M3. `store_calendar_items` — `ids` List Contains Tuples, Sorted by Datetime
- **File:** `agents/shared/tools/database.py`, lines 411-417
- **Category:** Quality
- **Description:** The `ids` local variable is a list of `(item_id, scheduled_at)` tuples. The sorting and final extraction works, but the variable name `ids` is misleading. Also, the type annotation on the return value (`list[str]`) does not match intermediate state.
- **Proposed Fix:** Rename to `id_schedule_pairs` or use a separate sort step for clarity.

### M4. `sanitize_for_prompt` — Injection Patterns Too Narrow
- **File:** `agents/shared/sanitize.py`, lines 6-16
- **Category:** Security
- **Description:** The prompt injection patterns are a small static list. Sophisticated injection attacks using unicode characters, base64 encoding, markdown formatting, or multi-turn prompt manipulation would bypass these filters. The sanitizer also does not handle nested JSON injection where user content is embedded in JSON structures.
- **Proposed Fix:** Add more patterns (e.g., `assistant:`, `\x00`-`\x1f` control chars, zero-width Unicode). Consider using an LLM-based injection detector for high-risk inputs (brand names, user-provided descriptions). Add JSON-aware escaping in `sanitize_json_for_prompt`.

### M5. `crawl_site` Timeout of 300 Seconds (5 Minutes) — Too Long
- **File:** `agents/shared/tools/browser.py`, line 131
- **Category:** Performance
- **Description:** The crawl timeout is 300 seconds. If the browser-worker is slow or hung, this blocks the research workflow for 5 minutes per URL. With multiple URLs, this compounds.
- **Proposed Fix:** Reduce to 60-120 seconds with a per-page timeout, or add a progress callback.

### M6. No Rate Limiting on Social API Calls
- **File:** `agents/shared/tools/social.py`, all functions
- **Category:** Reliability
- **Description:** Instagram, Facebook, and LinkedIn API calls have no rate limiting or backoff. The Meta Graph API has strict rate limits (~200 calls/hour for some endpoints). Exceeding these will result in 429 errors with no retry logic.
- **Proposed Fix:** Add rate limiting (e.g., `asyncio.Semaphore` or token bucket) and retry-with-backoff for 429 responses.

### M7. `upsert_product` — Passes Raw `product` Dict as SQL Params
- **File:** `agents/shared/tools/database.py`, lines 306-323
- **Category:** Security / Bug
- **Description:** `upsert_product(product)` passes the entire product dict as SQL parameters (line 319). If the dict contains extra keys not in the SQL query, SQLAlchemy will raise an error. If it's missing required keys, the insert will fail with a less helpful error.
- **Proposed Fix:** Explicitly extract and validate required fields before passing to the SQL query.

### M8. `Fabric execute_sql` — SQL Injection via String Concatenation
- **File:** `agents/workflows/product_intel/nodes.py`, lines 28-35
- **Category:** Security
- **Description:** `execute_sql("SELECT ... WHERE blocked = 0")` uses hardcoded queries (safe), but the `execute_sql()` function itself accepts arbitrary SQL strings. The `get_product_inventory` function (fabric.py line 117) correctly uses parameterized queries with `?` placeholders, but the function interface makes it easy for future callers to concatenate user input.
- **Proposed Fix:** Document that `execute_sql()` must only be called with parameterized queries. Consider adding a linter rule.

### M9. `generate_mockups_node` Always Generates All 4 Platforms
- **File:** `agents/workflows/content/nodes.py`, lines 838-856
- **Category:** Performance
- **Description:** Mockups are generated for instagram, facebook, linkedin, and x regardless of which channels are enabled for the brand. This wastes compute time (Pillow image processing + MinIO upload) for channels the brand doesn't use.
- **Proposed Fix:** Read enabled channels from `state.get("brand", {}).get("enabled_channels", [])` and only generate mockups for those platforms.

### M10. `_extract_month_section` — Regex Uses Unescaped `{1,3}` in f-String
- **File:** `agents/workflows/content/nodes.py`, lines 43-56
- **Category:** Bug
- **Description:** Line 44 has `rf"(#{1,3}\s*..."`. In a raw f-string, `{1,3}` is a Python f-string expression, not a regex quantifier. This should be `{{1,3}}` to produce the literal `{1,3}` in the regex pattern, or use `r"..."` without `f`. As written, it raises a `ValueError` because `1,3` is not a valid Python expression.
- **Proposed Fix:** Change to: `pattern = re.compile(rf"(#{{1,3}}\s*.*{re.escape(month_name)}.*?)(?=#{{1,3}}\s|\Z)", re.IGNORECASE | re.DOTALL)`

### M11. `store_content` — `hashtags` Stored as JSON String, Not Array
- **File:** `agents/workflows/content/nodes.py`, line 893; `agents/shared/tools/database.py`, lines 237-244, 274
- **Category:** Bug
- **Description:** In `store_content_node`, hashtags are passed as `json.dumps(state.get("hashtags", []))` (a JSON string). In `store_content()`, this string is parsed back (lines 237-244), but the SQL insert passes `raw_hashtags` (a Python list) as the `:hashtags` parameter. If the column type is `text[]` (Postgres array), asyncpg may handle this correctly. If the column type is `jsonb`, it depends on driver behavior. The double-encode/decode is wasteful and fragile.
- **Proposed Fix:** Pass hashtags as a Python list directly, not as a JSON string. Let the database driver handle serialization.

### M12. `worker.py` — Chain Logic in `_handle_message` Is 200+ Lines
- **File:** `agents/worker.py`, lines 80-345
- **Category:** Quality
- **Description:** The `_handle_message` function is ~265 lines long with deeply nested chain logic. This makes it hard to test, debug, and maintain. The chain routing logic (activation chains, sequential content chains, product intel chains, adaptation feedback loops) is all inline.
- **Proposed Fix:** Extract chain routing into a separate `ChainRouter` class or module. Each chain type should be a separate function with clear inputs and outputs.

### M13. `planning/nodes.py` — Product Name Matching Is Case-Sensitive Exact Match
- **File:** `agents/workflows/planning/nodes.py`, lines 253-261
- **Category:** Bug
- **Description:** `product_map` uses `p["name"].lower()` as keys, but `product_name` is also lowered. However, `product_name` comes from LLM output which may abbreviate or rephrase the product name. Exact lowercase match will miss "Omega 3 Fish Oil" vs "Omega-3 Fish Oil Caps".
- **Proposed Fix:** Use fuzzy matching (e.g., `difflib.get_close_matches`) or tokenized overlap scoring.

### M14. `generate_calendar` — LLM Asked to Generate Hundreds of Items
- **File:** `agents/workflows/planning/nodes.py`, lines 200-238
- **Category:** Reliability
- **Description:** The prompt asks for `total_items` items (e.g., 3 channels x 28 days = 84 items). LLMs frequently produce fewer items than requested, especially at high counts. There is no validation that the LLM actually produced the expected number, no retry logic for under-generation, and `parse_llm_json` fallback is an empty list.
- **Proposed Fix:** After parsing, check `len(items)` against expected count. If significantly under (e.g., <50%), retry with a more explicit prompt. Log a warning either way.

### M15. `store_calendar_items` — Silent Channel Skipping
- **File:** `agents/shared/tools/database.py`, lines 344-347
- **Category:** Quality
- **Description:** Items for disabled channels are silently skipped with only an INFO log. If the LLM generates 84 items but 40 are for disabled channels, the caller gets back only 44 IDs with no indication of why. The planning workflow doesn't validate expected vs actual item counts.
- **Proposed Fix:** Return a tuple of `(stored_ids, skipped_count)` so the caller can log/validate.

### M16. `evaluation/nodes.py` — `performance_data` Passed Fully to LLM
- **File:** `agents/workflows/evaluation/nodes.py`, line 40
- **Category:** Performance
- **Description:** `sanitize_json_for_prompt(perf_data)` with default `max_length=10000` sends potentially large engagement metrics data to the LLM. With 30 days of data across multiple channels, this could be 50+ records with many fields, exceeding context limits.
- **Proposed Fix:** Summarize/aggregate the performance data before sending to the LLM (e.g., aggregate by channel/content_type/week).

### M17. `nats_consumer.py` — `drain()` Then `close()` Is Redundant
- **File:** `agents/shared/nats_consumer.py`, lines 86-87
- **Category:** Quality
- **Description:** `drain()` already closes the connection after draining. Calling `close()` after `drain()` may raise an error on some NATS client versions since the connection is already closed.
- **Proposed Fix:** Remove the `close()` call after `drain()`, or add a check: `if not self._nc.is_closed: await self._nc.close()`.

### M18. `image_processing.py` — `generate_mockup` Hardcodes `username="healthspan.mu"`
- **File:** `agents/shared/image_processing.py`, line 253
- **Category:** Bug
- **Description:** The default `username` parameter is hardcoded to `"healthspan.mu"`. This means all brands get Instagram mockups with this specific username unless the caller explicitly passes a different one. The `generate_mockups_node` in content nodes does pass `display_name` but not `username`.
- **Proposed Fix:** Pass brand-specific username from brand config (e.g., from `brand_guidelines.channels.instagram.handle`).

### M19. `research/nodes.py` — Sequential Embedding in `store_results`
- **File:** `agents/workflows/research/nodes.py`, lines 298-300
- **Category:** Performance
- **Description:** `vectors = [await get_embedding(t) for t in texts_to_embed]` calls the embedding API sequentially for each text. With 10+ gaps and personas, this adds 10+ sequential HTTP roundtrips.
- **Proposed Fix:** Use `asyncio.gather()` or batch embedding API call (pass all texts in one request if the embedding API supports it).

---

## LOW Findings

### L1. Dead Import: `import json` in Multiple `__init__.py` Files
- **File:** Various `__init__.py` files
- **Category:** Quality
- **Description:** Several `__init__.py` files are empty (just a newline). This is fine but inconsistent with files that import for side effects.
- **Proposed Fix:** No action needed; just noting for consistency.

### L2. `config.py` — Default Passwords Are Empty Strings
- **File:** `agents/shared/config.py`, lines 25-26, 32, 36-37
- **Category:** Security
- **Description:** `POSTGRES_PASSWORD`, `QDRANT_API_KEY`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` all default to empty strings. While these should be set via env vars in production, an empty default means the service can start without credentials and attempt to connect with no password, potentially accessing an unprotected database.
- **Proposed Fix:** Add a startup validation that raises an error if critical credentials are empty when not in dev mode.

### L3. `fabric.py` — Token Stored in Module-Level Dict
- **File:** `agents/shared/tools/fabric.py`, lines 22-51
- **Category:** Security
- **Description:** The Fabric SQL access token is cached in a module-level dict (`_token_cache`). If the process dumps memory or has a debug endpoint, the token is exposed.
- **Proposed Fix:** Acceptable trade-off for caching. Ensure no debug endpoints expose module state.

### L4. `vector.py` — `create_collection` Calls `get_collections()` Every Time
- **File:** `agents/shared/tools/vector.py`, lines 38-51
- **Category:** Performance
- **Description:** Every call to `create_collection` fetches the full list of collections from Qdrant to check existence. This should be cached after the first successful creation.
- **Proposed Fix:** Cache known-created collection names in a module-level set.

### L5. `browser.py` — User-Agent String Identifies as "MarkAI Research Bot"
- **File:** `agents/shared/tools/browser.py`, line 63
- **Category:** Quality
- **Description:** The direct-fetch fallback user agent identifies as "MarkAI Research Bot/1.0". This could be blocked by websites that filter bots.
- **Proposed Fix:** Use a standard browser user agent for the fallback, matching the DDG search user agent.

### L6. `_mockup_x` — Does Not Create New Image/Draw Like Other Mockups
- **File:** `agents/shared/image_processing.py`, lines 486-541
- **Category:** Bug (cosmetic)
- **Description:** `_mockup_instagram` reuses the passed `img` and `draw`, while `_mockup_facebook` and `_mockup_linkedin` create new `Image` and `Draw` objects. `_mockup_x` also reuses the passed objects. This inconsistency means `_mockup_x` draws on a white background with potential artifacts from `generate_mockup`'s initial draw operations (like `_draw_status_bar`). In practice, the X mockup's status bar drawing at line 488 (`_draw_status_bar(draw, W, 0)`) overwrites whatever was drawn by `generate_mockup` at the same position, so the visual result is correct. But it's fragile.
- **Proposed Fix:** Have `_mockup_x` create its own `Image.new()` and `ImageDraw.Draw()` like Facebook and LinkedIn do, for consistency.

### L7. `worker.py` — Import Inside Function Body
- **File:** `agents/worker.py`, lines 112, 167, 225, 275
- **Category:** Quality
- **Description:** `from shared.tools.database import ...` is imported inside function bodies in several places. These are unnecessary since the imports could be at the top of the file.
- **Proposed Fix:** Move all database imports to the top of the file.

### L8. `planning/nodes.py` — `store_strategy` Called with `agent_type="content_calendar"`
- **File:** `agents/workflows/planning/nodes.py`, line 311
- **Category:** Quality
- **Description:** `store_strategy()` inserts a record with `agent_type="content_calendar"`, but the `agent_runs` table CHECK constraint was recently updated (commit 7785062) to include "activation". It's unclear if "content_calendar" is in the CHECK constraint for `agent_type`.
- **Proposed Fix:** Verify that "content_calendar" is an allowed value in the `agent_runs.agent_type` CHECK constraint. If not, add it.

### L9. Logging — `logger.exception()` Used with Explicit `exc_info=True`
- **File:** `agents/workflows/content/nodes.py`, line 850
- **Category:** Quality
- **Description:** `logger.warning("...", exc_info=True)` is used alongside `logger.exception()` elsewhere. `logger.exception()` automatically includes exception info. The usage is inconsistent but not harmful.
- **Proposed Fix:** Use `logger.warning("...", exc_info=True)` consistently for warnings, `logger.exception("...")` for errors.

### L10. `content/state.py` — Missing Fields Used by Nodes
- **File:** `agents/workflows/content/state.py`
- **Category:** Quality
- **Description:** (Related to H13) Fields like `positioning`, `relevant_pillar`, `relevant_audience`, `month_context`, `recent_posts`, `top_performing`, `product` are stored in state by `load_context` but not declared in the TypedDict. TypedDict is used for documentation and IDE support; undeclared fields may work at runtime but break type checking.
- **Proposed Fix:** Add all required fields to `ContentState`.

### L11. `worker.py` — WORKFLOW_TIMEOUT Import Position
- **File:** `agents/worker.py`, lines 26-27
- **Category:** Quality
- **Description:** `WORKFLOW_TIMEOUT` is defined between two import blocks (line 26 is between `shared.config` import and `shared.nats_consumer` import). This violates PEP 8 import ordering.
- **Proposed Fix:** Move `WORKFLOW_TIMEOUT` definition after all imports.

### L12. `image_processing.py` — PNG `quality` Parameter Ignored
- **File:** `agents/shared/image_processing.py`, line 203, 279
- **Category:** Quality
- **Description:** `result.convert("RGB").save(buf, format="PNG", quality=95)` — PNG does not support a `quality` parameter (that's JPEG). Pillow silently ignores it. For PNG, use `compress_level` (0-9).
- **Proposed Fix:** Remove `quality=95` from PNG saves, or change to `compress_level=6` for reasonable compression.

---

## Cross-Cutting Observations

### O1. No Unit or Integration Tests
No test files were found in the agents directory. All workflows, tools, and utility functions lack test coverage. This is a significant risk given the complexity of the chain routing logic, LLM output parsing, and database operations.

### O2. No Health Check Endpoint
The worker process has no HTTP health check endpoint. Container orchestrators (Docker, K8s) cannot determine if the worker is healthy, connected to NATS, and processing messages.

### O3. No Metrics or Observability
Beyond logging, there are no metrics (Prometheus, StatsD) for workflow latency, LLM call counts, error rates, or queue depth. LangSmith tracing is configurable but optional.

### O4. No Input Size Limits on NATS Messages
The worker accepts any size NATS message payload. A large payload could cause OOM when JSON-decoded or when passed to LLM prompts.

### O5. No Circuit Breaker Pattern
If LiteLLM, browser-worker, or Postgres goes down, all workflow invocations will fail sequentially with full timeout waits. There is no circuit breaker to fast-fail when a dependency is known to be down.

---

*End of Phase 1 Audit*
