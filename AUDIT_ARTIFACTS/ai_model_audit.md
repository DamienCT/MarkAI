# Phase 3: AI/ML Model & Provider Audit

**Date:** 2026-03-30
**Auditor:** Claude Opus 4.6 (automated)
**Scope:** All AI model references, LLM integrations, prompt templates, vector DB, SDK versions

---

## 3.1 AI Model Inventory

### 3.1.1 Models Referenced in Code

| Model ID | Provider | Category | Location(s) | Usage |
|---|---|---|---|---|
| `gpt-5.4` | OpenAI | text, vision | `agents/shared/llm.py`, `backend/app/services/ai_model_service.py`, `litellm/config.yaml` | Primary text/reasoning model (fallback default) |
| `gpt-5.4-mini` | OpenAI | text-fast | `agents/shared/llm.py`, `backend/app/services/ai_model_service.py`, `litellm/config.yaml` | Fast/cheap text model (fallback default) |
| `gpt-image-1.5` | OpenAI | image | `agents/shared/llm.py`, `backend/app/services/ai_model_service.py`, `litellm/config.yaml` | Image generation (fallback default) |
| `gpt-image-1` | OpenAI | image | `litellm/config.yaml`, `review/generate_posts.py` | Older image generation |
| `gpt-image-1-mini` | OpenAI | image | `litellm/config.yaml` | Budget image generation |
| `text-embedding-3-small` | OpenAI | embedding | `agents/shared/llm.py`, `litellm/config.yaml` | Embedding model (fallback default) |
| `sora-2` | OpenAI | video | `litellm/config.yaml` | Video generation |
| `sora-2-pro` | OpenAI | video | `litellm/config.yaml` | Pro video generation |
| `gemini-2.5-flash-image` | Google | image/vision | `backend/app/services/gemini_service.py`, `review/generate_posts.py` | Product replacement in images |
| `gemini-3.1-flash-image-preview` | Google | image/vision | `backend/app/services/gemini_service.py` | Fallback for product replacement |

### 3.1.2 Dynamic Model Resolution Architecture

**GOOD:** The system uses a dynamic model resolution pattern:
1. Models are discovered from OpenAI API and stored in PostgreSQL (`ai_models` table)
2. Active model per category is selected via UI (`frontend/src/app/providers/page.tsx`)
3. Agent code calls `get_model_for_category("text")` which queries the backend API
4. Results are cached in Valkey (5-minute TTL) with in-memory fallback
5. Hardcoded model strings only exist as **fallback defaults** when DB/API is unavailable

**Files implementing this:**
- `agents/shared/llm.py` -- agent-side model resolution + LiteLLM proxy calls
- `backend/app/services/ai_model_service.py` -- backend-side model management + discovery
- `backend/app/scheduler/model_discovery.py` -- daily scheduled discovery job

### 3.1.3 LiteLLM Configuration

**File:** `litellm/config.yaml`

```yaml
model_list:
  - gpt-5.4          -> openai/gpt-5.4
  - gpt-5.4-mini     -> openai/gpt-5.4-mini
  - text-embedding-3-small -> openai/text-embedding-3-small
  - gpt-image-1.5    -> openai/gpt-image-1.5
  - gpt-image-1      -> openai/gpt-image-1
  - gpt-image-1-mini -> openai/gpt-image-1-mini
  - sora-2           -> openai/sora-2
  - sora-2-pro       -> openai/sora-2-pro

litellm_settings:
  cache: true (Redis/Valkey)
  num_retries: 3
  request_timeout: 120
  drop_params: true
```

**Observation:** LiteLLM config only has OpenAI models. If users want to route via Gemini for text tasks, they would need to add entries. Currently Gemini is called directly (bypassing LiteLLM) for product image replacement only.

### 3.1.4 LangChain / LangGraph Usage

**Framework:** LangGraph (stateful workflow orchestration)

**7 workflow graphs identified:**
| Workflow | File | LLM Calls | Purpose |
|---|---|---|---|
| Research | `agents/workflows/research/` | 4-6 chat completions + embeddings | Website crawl, social analysis, competitor analysis, gap identification, persona building |
| Strategy | `agents/workflows/strategy/` | 5 chat completions | Positioning, pillars, audiences, cadence, themes |
| Planning | `agents/workflows/planning/` | 3 chat completions | Campaign generation, calendar items, strategy document |
| Content | `agents/workflows/content/` | 3-4 chat completions + 1 image gen + 1 Gemini call | Hook, caption, hashtags, background image, product replacement |
| Evaluation | `agents/workflows/evaluation/` | 3 chat completions | Pattern analysis, recommendations, adaptation classification |
| Adaptation | `agents/workflows/adaptation/` | 0 (applies changes) | Tiered change application with human-in-the-loop |
| Product Intel | `agents/workflows/product_intel/` | 4-5 chat completions | Brand discovery, research, product matching, promotability |

**Human-in-the-loop:** Strategy and Adaptation workflows use `langgraph.types.interrupt()` for human review gates, with auto-approve bypass for automated pipeline triggers.

### 3.1.5 Vector Database (Qdrant)

**Two Qdrant clients exist:**
1. `agents/shared/tools/vector.py` -- async wrappers for agent use
2. `backend/app/services/qdrant_service.py` -- backend service

**Configuration:**
- Default collection: `markai_embeddings`
- Vector size: 1536 (matches `text-embedding-3-small`)
- Distance metric: Cosine
- Collections used: `brand_research` (for gaps + personas)

**Docker image:** `qdrant/qdrant:v1.17.0`

---

## 3.2 Model Version Currency

### 3.2.1 OpenAI Models

| Model in Code | Status | Notes |
|---|---|---|
| `gpt-5.4` | **Current** | Latest GPT-5 series model (launched March 2026) |
| `gpt-5.4-mini` | **Current** | Fast/cheap variant |
| `gpt-image-1.5` | **Current** | Latest image generation model |
| `gpt-image-1` | **Active but superseded** | `gpt-image-1.5` is newer; only used in `review/generate_posts.py` (benchmark scripts) |
| `gpt-image-1-mini` | **Active** | Budget image model |
| `text-embedding-3-small` | **Current** | Standard embedding model; `text-embedding-3-large` available for higher quality |
| `sora-2` / `sora-2-pro` | **Current** | Latest Sora video models |

**No deprecated models found in executable code.** Legacy references (`gpt-4o`, `gpt-3.5`, `dall-e-3`) only exist in old documentation files under `docs/build-files/`.

### 3.2.2 Google Gemini Models

| Model in Code | Status | Notes |
|---|---|---|
| `gemini-2.5-flash-image` | **Current** | Used for product image replacement |
| `gemini-3.1-flash-image-preview` | **Preview** | Fallback model; preview status means it may change |

### 3.2.3 Pricing Awareness

No pricing data is tracked in the system. The `agent_runs` table has `tokens_used` and `cost_usd` columns, but token counting is not implemented in the LLM wrapper (`agents/shared/llm.py`). LiteLLM tracks costs server-side if enabled.

---

## 3.3 API Integration Patterns

### 3.3.1 API Key Security

| Check | Status | Details |
|---|---|---|
| Keys in environment variables | **PASS** | All keys loaded via Pydantic Settings from `.env` |
| `.env` in `.gitignore` | **PASS** | `.env`, `.env.local`, `.env.production` all gitignored |
| No hardcoded keys in source | **PASS** | No actual API key values found in code |
| Production startup validation | **PASS** | `backend/app/config.py` refuses to start in production with default `SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY` |
| Azure AD required in production | **PASS** | Backend validates `AZURE_AD_TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` in production mode |
| LiteLLM key via env | **PASS** | `os.environ/OPENAI_API_KEY` syntax in config.yaml |
| Gemini key via env | **PASS** | Loaded from `settings.GEMINI_API_KEY` |

**ISSUE: Backend Qdrant client has no API key support.** `backend/app/services/qdrant_service.py` line 29 creates the client without `api_key` parameter, while the agents client (`agents/shared/tools/vector.py` line 33) does pass `api_key`. This could be a problem if Qdrant is deployed with authentication enabled.

### 3.3.2 Error Handling

| Component | Error Handling | Retry Logic | Timeout |
|---|---|---|---|
| `agents/shared/llm.py` `chat_completion` | **GOOD** -- catches `ConnectError`, `TimeoutException`, `HTTPStatusError` | **GOOD** -- tenacity: 3 attempts, exponential backoff (2-30s), retries on 429/500/502/503 | 120s |
| `agents/shared/llm.py` `get_embedding` | **GOOD** -- same pattern | **GOOD** -- same tenacity config | 60s |
| `agents/shared/llm.py` `generate_image` | **GOOD** -- same pattern | **GOOD** -- same tenacity config | 180s |
| `backend/app/api/v1/intelligence.py` `_call_llm` | **FAIR** -- catches generic exceptions for LiteLLM, falls back to direct OpenAI | **MISSING** -- No retry logic on the backend's direct LLM calls | 30s |
| `backend/app/services/gemini_service.py` | **GOOD** -- try/except per model with fallback chain | **PARTIAL** -- tries multiple models in sequence, but no retry per model | No explicit timeout |
| `agents/workflows/content/nodes.py` Gemini call | **GOOD** -- wrapped in try/except, falls back to original image | **MISSING** -- no retry | 30s (httpx default for image download) |
| `backend/app/services/ai_model_service.py` `discover_models` | **GOOD** -- exception logging | **MISSING** -- no retry on OpenAI API list call | 30s |

### 3.3.3 Rate Limit Handling

| Check | Status | Details |
|---|---|---|
| HTTP 429 retry | **PASS** | `_is_retryable()` in `agents/shared/llm.py` retries on 429 |
| LiteLLM built-in rate limiting | **PASS** | LiteLLM proxy handles rate limit headers from upstream |
| Per-workflow rate limiting | **MISSING** | No per-workflow or per-brand rate limits; a brand activation could spike costs |
| Token budget / cost caps | **MISSING** | No mechanism to limit spend per brand or per workflow run |

### 3.3.4 Response Validation

| Check | Status | Details |
|---|---|---|
| JSON parsing from LLM | **GOOD** | `parse_llm_json()` strips markdown fences, handles `JSONDecodeError`, uses fallback values |
| Structural validation | **GOOD** | `validate_llm_output()` checks required fields and expected types (list vs dict) |
| Fallback on parse failure | **GOOD** | Every `parse_llm_json` call provides a sensible fallback |
| Output sanitization | **PARTIAL** | Input is sanitized before prompts, but LLM output is not sanitized before storage |

### 3.3.5 Token Count Tracking

| Check | Status | Details |
|---|---|---|
| Token counting in wrapper | **MISSING** | `chat_completion()` returns only `choices[0].message.content`, discards `usage` data |
| `agent_runs.tokens_used` column | **EXISTS BUT UNUSED** | Column exists in DB schema but is never populated |
| `agent_runs.cost_usd` column | **EXISTS BUT UNUSED** | Column exists in DB schema but is never populated |
| LiteLLM server-side tracking | **AVAILABLE** | LiteLLM can track usage if configured, but no integration to push to `agent_runs` |

---

## 3.4 SDK Versions

### 3.4.1 Python Dependencies (agents)

| Package | Pinned Version | Latest Stable (approx.) | Status |
|---|---|---|---|
| `langgraph` | `>=1.0,<2.0` | ~1.x | **OK** -- wide range, will get updates |
| `langchain-core` | `>=1.0,<2.0` | ~1.x | **OK** |
| `langchain-openai` | `>=1.0,<2.0` | ~1.x | **OK** |
| `litellm` | `>=1.60` | ~1.70+ | **OK** -- open range |
| `qdrant-client` | `>=1.17` | ~1.17 | **OK** |
| `google-genai` | `>=1.5` | ~1.5+ | **OK** -- uses new `google-genai` SDK (not deprecated `google-generativeai`) |
| `httpx` | `>=0.28` | ~0.28 | **OK** |
| `tenacity` | `>=9.0` | ~9.0 | **OK** |
| `opentelemetry-api/sdk` | `>=1.40` | ~1.40 | **OK** |

### 3.4.2 Python Dependencies (backend)

| Package | Pinned Version | Notes |
|---|---|---|
| `litellm` | `>=1.60` | Same as agents |
| `google-genai` | `>=1.5` | Same as agents |
| `qdrant-client` | `>=1.17` | Same as agents |
| `redis` | `>=7.1` | Used for Valkey cache |

### 3.4.3 Frontend Dependencies

| Package | Version | Notes |
|---|---|---|
| `next` | `^16.2.1` | Latest Next.js |
| `next-auth` | `^4.24.11` | Auth library for Azure AD SSO |
| `react` | `^19.2.4` | Latest React |

**No AI/ML SDKs in frontend.** All AI calls are routed through the backend API.

### 3.4.4 Docker Images

| Image | Version | Notes |
|---|---|---|
| `ghcr.io/berriai/litellm` | `main-latest` | **CONCERN** -- `main-latest` is a floating tag; could break unexpectedly. Pin to a specific version for production stability. |
| `qdrant/qdrant` | `v1.17.0` | **OK** -- pinned |

---

## 3.5 Prompt Engineering Quality

### 3.5.1 System Prompt Structure

**Total system prompts found:** ~25+ across all workflow nodes + backend intelligence.py

**Strengths:**
- All prompts have clear role assignments ("You are a brand strategist", "You are a social media analyst", etc.)
- Consistently include Mauritian market context (bilingual English/French/Creole, local holidays, Indian Ocean region)
- Structured output expectations (JSON schema described in plain text within prompts)
- Temperature values are thoughtfully varied: 0.2-0.3 for analytical tasks, 0.5 for strategy, 0.7-0.8 for creative content
- `max_tokens` is set per call type (256 for hooks, 2048 for captions, 8192-16384 for strategy documents)

**Weaknesses:**
1. **No structured output mode:** Prompts request JSON via natural language ("Return a JSON array") rather than using OpenAI's `response_format` with JSON schema. The `json_mode` parameter is only used in `intelligence.py` `_call_llm()`, not in the agents' `chat_completion()`.
2. **Very long prompts:** Some system prompts are 500+ words (e.g., `build_personas` in research/nodes.py). These could be refactored into template files for maintainability.
3. **Prompt templates inline:** All prompts are embedded directly in Python code as f-strings. No centralized prompt management or versioning system.

### 3.5.2 Prompt Injection Protection

**File:** `agents/shared/sanitize.py`

**GOOD -- Dedicated sanitization module exists:**
- Filters known injection patterns: "ignore previous instructions", "system:", "you are now", "forget all previous", "[INST]", "<|im_start|>", "<<SYS>>"
- Truncates input to configurable max_length
- Applied consistently across ALL workflow nodes via `sanitize_for_prompt()` and `sanitize_json_for_prompt()`

**Coverage verification:**
- `research/nodes.py` -- uses `sanitize_for_prompt` and `sanitize_json_for_prompt` for all user data
- `strategy/nodes.py` -- uses `sanitize_json_for_prompt` for all data inputs
- `planning/nodes.py` -- uses both sanitization functions
- `content/nodes.py` -- extensive use of `sanitize_for_prompt` for every field
- `product_intel/nodes.py` -- uses both sanitization functions
- `evaluation/nodes.py` -- uses `sanitize_json_for_prompt`
- `intelligence.py` (backend) -- **DOES NOT use sanitization** for brand field generation prompts

**ISSUE:** The backend's `intelligence.py` constructs prompts using brand data directly without calling `sanitize_for_prompt()`. Brand names, descriptions, and other user-editable fields are interpolated directly into LLM prompts.

### 3.5.3 Prompt Consistency

| Aspect | Assessment |
|---|---|
| Role assignment | **Consistent** -- all use "You are a [role]" pattern |
| Output format | **Consistent** -- JSON requested with field descriptions |
| Market context | **Consistent** -- Mauritius/Indian Ocean context in every prompt |
| Fallback handling | **Consistent** -- `parse_llm_json` with fallback on every call |
| Temperature selection | **Consistent** -- lower for analytical, higher for creative |

---

## 3.6 Critical Issues (Must Fix)

### CRITICAL-1: Backend Qdrant Client Missing API Key
**File:** `backend/app/services/qdrant_service.py:26-29`
**Risk:** If Qdrant is deployed with authentication, backend vector operations will fail silently.
**Fix:** Add `api_key=settings.QDRANT_API_KEY or None` to the QdrantClient constructor.

### CRITICAL-2: LiteLLM Docker Image Uses Floating Tag
**File:** `docker-compose.yml:131`
**Risk:** `ghcr.io/berriai/litellm:main-latest` could pull a breaking update at any rebuild.
**Fix:** Pin to a specific version tag (e.g., `ghcr.io/berriai/litellm:v1.63.14` or current stable).

### CRITICAL-3: Token Usage Not Tracked
**Files:** `agents/shared/llm.py`, `agent_runs` schema
**Risk:** No visibility into API costs per workflow run; no ability to set spend limits.
**Fix:** Extract `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens` from LiteLLM response and propagate to `agent_runs.tokens_used` and `agent_runs.cost_usd`.

---

## 3.7 High-Priority Issues

### HIGH-1: Backend `_call_llm` Has No Retry Logic
**File:** `backend/app/api/v1/intelligence.py:24-69`
**Risk:** Transient API failures (429, 502) will immediately error out brand field generation.
**Fix:** Add tenacity retry decorator matching the pattern in `agents/shared/llm.py`.

### HIGH-2: Backend `_call_llm` Missing Prompt Sanitization
**File:** `backend/app/api/v1/intelligence.py:509-568`
**Risk:** Brand names or descriptions could contain prompt injection payloads.
**Fix:** Import and apply `sanitize_for_prompt` from agents or replicate the sanitization logic in the backend.

### HIGH-3: Gemini Service No Timeout Configuration
**File:** `backend/app/services/gemini_service.py`
**Risk:** Gemini API calls could hang indefinitely; the `google-genai` client does not have explicit timeout set.
**Fix:** Configure timeout in the genai Client or wrap calls with `asyncio.wait_for()`.

### HIGH-4: No `response_format` for JSON Outputs
**Files:** All workflow nodes
**Risk:** LLM may return malformed JSON; current mitigation (`parse_llm_json` fallback) is reactive rather than preventive.
**Fix:** Pass `response_format={"type": "json_object"}` for all calls that expect JSON output. This is supported by GPT-5.4 and LiteLLM.

### HIGH-5: Content Nodes Gemini Uses Wrong Model Category
**File:** `agents/workflows/content/nodes.py:678`
**Risk:** `get_model_for_category("vision")` returns an OpenAI model string (e.g., `openai/gpt-5.4`), but this is passed to a Gemini client. The Gemini client will fail or ignore this model string.
**Fix:** Use the hardcoded Gemini image models from `gemini_service.py` or create a separate "gemini-image" model category. The Gemini client needs Gemini model names, not OpenAI ones.

---

## 3.8 Medium-Priority Issues

### MED-1: No Per-Brand or Per-Workflow Cost Caps
**Risk:** A brand activation triggering research -> strategy -> planning -> content could generate many LLM calls with no spend limit.
**Fix:** Implement cost tracking (see CRITICAL-3) and add configurable per-brand monthly limits.

### MED-2: Duplicate Qdrant Clients
**Files:** `agents/shared/tools/vector.py` and `backend/app/services/qdrant_service.py`
**Risk:** Two separate implementations with slightly different APIs (e.g., backend lacks async wrappers natively, agents wrap sync client in `asyncio.to_thread`).
**Fix:** Low priority -- acceptable given separate services. Ensure both use `api_key` parameter.

### MED-3: `review/generate_posts.py` Uses Hardcoded Models
**File:** `review/generate_posts.py:812, 835, 903, 926, 994`
**Risk:** Benchmark/review scripts use hardcoded `gpt-image-1` and `gemini-2.5-flash-image`.
**Fix:** Low priority (scripts, not production code). Consider parameterizing for consistency.

### MED-4: Prompts Not Externalized
**Risk:** 25+ prompts embedded in Python f-strings across 7 workflow modules makes version control, A/B testing, and prompt iteration difficult.
**Fix:** Consider moving prompts to external template files (Jinja2, YAML, or dedicated prompt management).

### MED-5: No LLM Output Sanitization Before Storage
**Risk:** LLM outputs are stored directly in the database. If an LLM generates XSS payloads or unexpected content, it could affect the frontend.
**Fix:** Sanitize LLM text outputs before storing in the database, particularly for fields rendered in the UI.

---

## 3.9 Informational Notes

### INFO-1: Model Discovery Is OpenAI-Only
The `discover_models()` function only queries OpenAI's `/v1/models` endpoint. Gemini models are not discovered or tracked in the DB. If multi-provider support is desired, discovery needs to be extended.

### INFO-2: LangSmith Tracing Is Available But Optional
LangSmith tracing (`LANGCHAIN_TRACING_V2`) is configured but disabled by default in production. This is a reasonable default but should be enabled during development/debugging.

### INFO-3: Promptfoo Evaluation Setup Exists
`eval/promptfooconfig.yaml` contains test cases for content generation and research summary evaluation, routed through LiteLLM. This is good practice for prompt quality assurance.

### INFO-4: Good Architectural Pattern
The dynamic model resolution pattern (DB -> cache -> fallback) is well-designed. It allows changing models via the UI without code changes or restarts, which is a significant operational advantage.

---

## 3.10 Summary Scorecard

| Area | Score | Notes |
|---|---|---|
| Model Currency | **A** | All models are current generation; no deprecated models in production code |
| API Key Security | **A** | Keys in env vars, .env gitignored, production validation |
| Error Handling | **B** | Good in agents, weak in backend direct calls |
| Retry Logic | **B+** | Excellent in agents (tenacity), missing in backend and Gemini |
| Rate Limit Handling | **B-** | LiteLLM handles upstream limits; no application-level caps |
| Response Validation | **B+** | Good JSON parsing with fallbacks; no structured output mode |
| Token Tracking | **F** | Schema exists but completely unused |
| Prompt Injection Protection | **B+** | Dedicated module, consistently used in agents; missing in backend |
| Prompt Quality | **A-** | Well-structured, contextual, appropriate temperatures; not externalized |
| SDK Versions | **A-** | All current; LiteLLM Docker tag should be pinned |
| Architecture | **A** | Dynamic model resolution, LiteLLM proxy, LangGraph workflows |

**Overall Grade: B+**

The AI/ML integration is architecturally sound with a mature dynamic model resolution system, good prompt engineering practices, and proper input sanitization. The primary gaps are: token/cost tracking (completely unimplemented despite schema support), backend prompt injection protection, and the Gemini model category mismatch in content nodes.
