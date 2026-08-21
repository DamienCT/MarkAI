# MarkAI Comprehensive Audit and World-Class Roadmap

Audit date: 2026-08-21

Repository: D:\MarkAI

Audit posture: read-only review plus non-destructive verification

Primary objective: turn MarkAI into the most dependable automated marketing-agent team possible, producing professional, evidence-backed, brand-safe content consistently

---

## 1. Executive verdict

MarkAI is an ambitious and credible product foundation, not a production-ready autonomous marketing operation.

The application already has more breadth than most early marketing-agent systems: brand onboarding, research, strategy, annual planning, product intelligence, still and video creation, approvals, publishing, analytics, adaptation, provider routing, system operations, and a polished administration UI. The strongest engineering is in deterministic creative post-processing, especially image placement, product swapping, video assembly, and the large body of media-oriented tests.

The central problem is trust. Several controls that appear to govern autonomy do not govern it in practice:

- LangGraph human-review interrupts are returned under __interrupt__, but the worker treats non-failed results as completed and can chain the next workflow. There is no durable resume command.
- Evaluation stores adaptation fields inside encoded notes, while adaptation reads nonexistent top-level fields. Even an “applied” adaptation changes only status, not system behavior.
- Publishing lacks an atomic claim/idempotency boundary, and webhook verification lacks replay-safe attempt binding.
- Brand or tenant ownership is not consistently enforced across APIs, jobs, assets, reviewers, and agent lookups.
- Social credentials are modeled as readable application data and are forwarded into n8n execution payloads.
- Several media and browser services are fail-open or insufficiently authenticated.
- Content and video quality gates can fail and still send incomplete work to ordinary review.
- Reports, mockups, analytics, and generated samples sometimes present inferred or invented information as fact.

These are not cosmetic shortcomings. They make autonomous publishing, adaptation, and multi-client operation unsafe today.

The recommended strategy is therefore:

1. Freeze unattended production publishing while the P0 trust gates are repaired.
2. Build one canonical, versioned campaign and artifact model with durable approvals, provenance, and ownership.
3. Make every agent outcome measurable, reproducible, and fail-closed.
4. Add professional editorial, rights, experimentation, attribution, and localization capabilities.
5. Re-enable bounded autonomy gradually, by risk tier and measured quality—not by a single model confidence score.

### Overall maturity scorecard

Scores are evidence-based maturity estimates out of 10, not a substitute for formal certification.

| Domain | Score | Current assessment |
|---|---:|---|
| Product vision and breadth | 8 | Exceptional scope and a coherent marketing-operations ambition |
| Desktop UI and information architecture | 7 | Polished, consistent, and broadly understandable |
| Mobile UX and accessibility | 4 | Responsive foundation exists; crowding, focus, keyboard, semantics, and chart alternatives remain |
| Agent role coverage | 7 | Major marketing stages exist, but orchestration is mostly linear and role boundaries are weak |
| Research and strategic truthfulness | 3 | Outputs lack durable citations, evidence packets, calibration, and contradiction handling |
| Content quality and brand fidelity | 4 | Strong deterministic tooling; samples still show invented text/products, weak platform adaptation, and uncited claims |
| Workflow correctness and durability | 2 | Human review, chaining, ACK order, checkpointing, retries, leases, and lifecycle semantics have critical defects |
| Learning and experimentation | 1 | Adaptation does not actually mutate behavior; no causal measurement or rollback |
| Publishing reliability | 3 | Direct publishers exist, but idempotency, media flows, retries, and channel completeness are not production-grade |
| Security and tenant isolation | 2 | Authentication intent is visible; authorization, secrets, SSRF, webhook, and service exposure need immediate work |
| Data model and migrations | 3 | Broad schema exists; lifecycle duplication, cross-record integrity, and migration provenance are weak |
| Frontend code quality | 5 | Strict TypeScript/build pass; lint fails and there are no automated frontend tests |
| Backend/agent test posture | 6 | 1,442 tests pass across backend and agents; critical paths have low coverage and mocks miss contract failures |
| Observability and operations | 3 | Components exist; tracing, alert delivery, dashboards, redaction, SLOs, and production enablement are incomplete |
| Deployment and recovery | 4 | Thoughtful compose/deploy/backup work; single-node, drift, secret output, and restore/HA gaps remain |
| Documentation truthfulness | 4 | Rich documentation, but substantial version, topology, deployment, and implementation drift |
| Production readiness for bounded autonomous publishing | 2 | Do not enable unattended publishing until the P0 exit gate is met |

### Go/no-go recommendation

| Capability | Recommendation now |
|---|---|
| Local development and internal demonstrations | Go, with known limitations disclosed |
| Human-reviewed drafting and ideation | Conditional go; require manual source and asset verification |
| Client-facing reports | Conditional go after citations, truthfulness, versioning, and export controls |
| Multi-brand or multi-client production | No-go until tenant/object authorization is complete |
| Automated publishing | No-go until idempotency, authenticated webhooks, immutable approvals, and kill switches are verified |
| Automated learning/adaptation | No-go; current loop is structurally nonfunctional |
| Regulated health/wellness claims | No-go without claim evidence, jurisdiction policy, and legal/medical review gates |

---

## 2. Scope, methodology, and confidence

### 2.1 Every-file coverage

The audit reconciled and reviewed 516 repository-authored or project-relevant files:

| Area | Files reviewed |
|---|---:|
| agents | 137 |
| backend | 134 |
| db | 2 |
| frontend, including ignored TypeScript build metadata | 112 |
| Root, CI/CD, infrastructure, docs, browser worker, notifications, observability, evals, reports, review assets, and samples | 131 |
| Total | 516 |

---

### 2.2 Current official benchmark references

These sources were used to validate time-sensitive design recommendations; repository evidence remains the basis of the findings.

- LangGraph interrupts, durable checkpointing, __interrupt__, and Command(resume): https://langchain-ai.github.io/langgraph/concepts/breakpoints/
- OpenAI guardrails and human approvals: https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- OpenAI agent workflow evaluation: https://developers.openai.com/api/docs/guides/agent-evals
- OpenAI evaluation best practices: https://developers.openai.com/api/docs/guides/evaluation-best-practices
- NIST Generative AI Risk Management Profile: https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- NIST zero-trust cloud-native guidance: https://csrc.nist.gov/pubs/sp/800/207/a/final
- FTC advertising and marketing guidance: https://www.ftc.gov/business-guidance/advertising-marketing
- FTC endorsement guidance: https://www.ftc.gov/news-events/topics/truth-advertising/advertisement-endorsements
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/
- C2PA 2.4 specifications: https://spec.c2pa.org/specifications/specifications/2.4/index.html
- IPTC photo metadata guidance: https://www.iptc.org/std/photometadata/documentation/userguide/
- IPTC RightsML: https://iptc.org/standards/rightsml/
- LinkedIn Posts API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?tabs=curl&view=li-lms-2026-04
- LinkedIn Images API: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-06
- YouTube video resource/states: https://developers.google.com/youtube/v3/docs/videos
- YouTube resumable uploads: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- n8n security audit: https://docs.n8n.io/hosting/securing/security-audit/
- n8n execution history: https://docs.n8n.io/workflows/executions/all-executions/
- OpenTelemetry observability primer: https://opentelemetry.io/docs/concepts/observability-primer/
- Google Ads experiments: https://developers.google.com/google-ads/api/docs/experiments/overview
- Google Conversion Lift: https://support.google.com/google-ads/answer/12003020
- Mauritius Data Protection Act resources: https://dataprotection.govmu.org/Pages/The%20Law/Data-Protection-Act-2017.aspx
- Mauritius right to object to direct marketing: https://dataprotection.govmu.org/Pages/Data%20Subjects/Right-to-object.aspx

---

### 2.3 Verification evidence

### Executed checks

| Area | Command/check | Outcome |
|---|---|---|
| Backend | pytest | 189 passed |
| Backend | Python AST parse | 128/128 |
| Backend | Ruff | 5 findings |
| Agents | pytest | 1,253 passed |
| Agents | coverage | 56% |
| Agents | Ruff | 41 findings |
| Frontend | npx tsc --noEmit --incremental false | Passed |
| Frontend | npm run build | Passed, but missing Azure config incorrectly remained nonfatal |
| Frontend | npm run lint | Failed: 10 errors, 71 warnings |
| Frontend | npm audit --omit=dev | Failed: 2 critical, 4 high, 1 moderate |
| Compose | docker compose config --quiet | Passed |
| Compose VPS | docker compose with VPS overlay config --quiet | Passed |
| Structured data | JSON parse | No failures |
| Structured data | YAML parse, 24 files | No failures |
| Other Python | compileall for browser-worker, notifications, scripts, and review | Passed |
| Media | ffprobe and representative frame/contact-sheet inspection, 10 MP4s | All decode; quality findings recorded |
| Audio | ffprobe/decoding, 15 M4As | All decode |
| Browser | Sign-in, shell, 15 routes, reports, sequence map at desktop/mobile | Completed with mocked authenticated API state |
| Repository | git diff --check | Passed before final report validation |
| Ledger | Exact comparison to current non-generated inventory | 516 ledger entries, 516 files, zero missing, zero extra, zero duplicates |

### Browser limitation

The UI inspection intentionally did not use real Azure or social credentials. It validates rendering, navigation, responsive behavior, accessibility observations, and representative application states. It does not replace a staging end-to-end test with real backend jobs and provider sandboxes.

### Secret handling

The ignored .env file was reviewed only for key presence, placeholder/default state, and configuration risk. No secret value is reproduced here. Existing secrets should be treated as rotation candidates when vault migration is performed.

---

### 2.4 Decision checklist for production authorization

Do not authorize unattended production publishing until every answer is yes:

- Is every request/job/resource tenant-scoped and negative-tested?
- Are all channel credentials vault-resident and absent from payloads/logs?
- Is the approved content/media immutable and hash-bound?
- Does human pause survive restart and resume exactly once?
- Can retries/crashes/callback replays produce at most one remote post?
- Can every provider timeout be reconciled before retry?
- Does a global/brand/channel kill switch stop queued, running, and retrying work?
- Are all externally verifiable claims sourced and current?
- Are rights, releases, provenance, alt text, captions, and disclosures complete?
- Do deterministic quality gates fail closed?
- Is the database reproducible from an empty environment and restorable from backup?
- Are audit records append-only and complete?
- Are dependencies patched and configuration fail-closed?
- Do critical browser journeys pass WCAG 2.2 AA checks?
- Do alerts, runbooks, and restore drills prove the team can recover?


### 2.5 Coverage details and exclusions

Every text/source/configuration file was read. Structured files were also parsed or validated where appropriate. Binary media was inspected using metadata plus visual or audio review:

- 15 bundled M4A music files
- 29 review images and mockups
- 10 sample MP4 reels
- SVG and application image assets
- four interactive HTML reports and the sequence map
- both user-supplied runtime-log attachments

Generated and third-party trees were inventoried but not semantically audited file by file:

- frontend/node_modules: 39,201 files, about 660.5 MB
- frontend/.next: 2,673 files, about 242.6 MB
- Git internals
- Python bytecode and test/lint caches
- temporary browser-audit artifacts, which were removed after inspection

The full 516-file coverage ledger is in Appendix A.

### 2.6 Review methods

- Full source and configuration reading, with cross-file data-flow tracing
- API, schema, service, scheduler, message-bus, workflow, and database relationship review
- Security review against Python/FastAPI and JavaScript/TypeScript/Next.js secure-development guidance
- Static syntax and type checks
- Unit-test execution and coverage review
- Dependency vulnerability checks
- Docker Compose and structured-file validation
- Real-browser desktop and mobile inspection using the Playwright audit workflow
- Visual inspection of generated content, platform mockups, reports, and sample videos
- Runtime-log analysis
- Documentation-to-implementation reconciliation
- Current official documentation checks for LangGraph interrupt behavior, LinkedIn media posting, n8n security/execution behavior, WCAG 2.2, and C2PA provenance

### 2.7 Verification summary

| Check | Result |
|---|---|
| Backend tests | 189 passed in 8.31 seconds |
| Agent tests | 1,253 passed in 36.44 seconds |
| Agent coverage | 56% overall; critical workflow files are often 11–31% |
| Backend Python parsing | 128/128 modules parsed |
| Backend Ruff | Failed: 5 findings |
| Agent Ruff | Failed: 41 findings, 10 in production source |
| Frontend TypeScript | Passed |
| Frontend production build | Passed 21 routes, but incorrectly tolerated missing required Azure configuration |
| Frontend lint | Failed: 10 errors and 71 warnings |
| Frontend tests | None |
| Frontend production dependency audit | Failed: 7 vulnerabilities; 2 critical, 4 high, 1 moderate |
| Docker Compose base configuration | Passed |
| Docker Compose VPS overlay configuration | Passed |
| JSON parsing | Passed for all reviewed JSON |
| YAML parsing | Passed for all 24 reviewed YAML files |
| Python compile checks outside backend/agents | Passed |
| Git whitespace validation | Passed |
| Authenticated real-data browser E2E | Not run: Azure credentials and representative live backend data were intentionally not supplied |

### 2.8 Important limitations

- This was not a destructive penetration test.
- No production social account was used and no content was published.
- No production database was modified.
- Azure-authenticated end-to-end flows were not exercised with real credentials.
- Infrastructure protections outside this repository—cloud firewall, WAF, private networks, identity policies, secret manager, and host hardening—must be verified independently.
- Dependency findings reflect the lockfile and available audit tools on 2026-08-21.
- Generated-content quality judgments combine deterministic defects with expert visual/editorial review; they should be converted into a maintained golden evaluation set.

### 2.9 Severity definitions

| Severity | Meaning |
|---|---|
| P0 / stop-ship | Can bypass governance, cross tenants, expose credentials, duplicate external effects, corrupt provenance, or publish materially unsafe work. Must be closed before unattended production use. |
| P1 / high | Likely to cause major reliability, trust, security, content-quality, or operational failure. Resolve in the first implementation waves. |
| P2 / medium | Significant UX, maintainability, observability, efficiency, or completeness issue. Schedule after the trust foundation. |
| P3 / improvement | Differentiating capability, polish, or scale enhancement. |

---

## 3. Current architecture and actual workflow

~~~text
Browser / Next.js
    |
    | Azure bearer token
    v
FastAPI backend
    |---- PostgreSQL / SQLAlchemy / Alembic
    |---- MinIO object storage
    |---- NATS JetStream
    |---- Qdrant
    |---- Valkey
    |---- direct social publishers
    |---- n8n publishing webhook
    |
    +--> agent worker
          product intelligence
              -> research
              -> strategy
              -> planning
              -> still content or video
              -> review
              -> publishing
              -> engagement pull
              -> evaluation
              -> adaptation

Supporting services:
    browser worker, notification gateway, LiteLLM,
    local Forge/ComfyUI media server, Grafana/Loki/Prometheus/OTel
~~~

The intended flow resembles an agent team, but the current graphs are mostly linear pipelines. The worker is the practical supervisor: it routes by NATS subject prefix, invokes a graph, records a run, ACKs, and publishes the next stage. Graphs have limited revision loops, independent critic authority, durable memory, or policy-driven branching.

The same business lifecycle is represented in several places—database enums/status strings, agent state, scheduler logic, UI Kanban columns, local browser watchers, and n8n callbacks. These representations disagree. This is the root cause of disappearing Kanban items, approval ambiguity, stale jobs, unsafe chaining, and unreliable publishing.

---

## 4. What is already strong

These strengths should be preserved while the foundation is repaired:

- Broad, coherent product vision spanning the real marketing lifecycle
- Polished desktop design language, strong card hierarchy, dark theme, skeletons, dialogs, selects, tabs, toasts, and print styling
- Strict frontend TypeScript compilation
- Central API/types/constants layer and reusable UI primitives
- Microsoft Entra token validation intent, inactive-user rejection, viewer-default role, and authenticated route sweep tests
- Parameterized backend data access and explicit Pydantic/SQLAlchemy domain structure
- Non-root backend, agents, browser-worker, notification, and frontend containers
- Business Central retry/circuit-breaker work and direct Meta, LinkedIn, and YouTube publisher implementations
- YouTube synthetic-media disclosure support
- Strong deterministic media engineering: image subject detection, product region/swap guards, placement scoring, logo/text handling, render-quality checks, audio assembly, end cards, multi-shot video, and storage-path tests
- 1,253 agent tests and 189 backend tests
- Deployment locking, SHA checks, backups, build-before-up logic, and a production-oriented Compose topology
- A substantial master upgrade specification that already identifies many of the right strategic goals
- Existing UI surfaces for approvals, learning, model routing, system health, audit, and provider administration—the correct control-plane concepts exist even where behavior is incomplete

---

## 5. P0 stop-ship findings

### P0-01 — Human review does not reliably stop or resume workflows

Security/workflow rule: durable approval and external-effect governance

Severity: P0

Location: agents/workflows/strategy/nodes.py:358–408; agents/workflows/adaptation/nodes.py:76–166; agents/worker.py:2228–2254, 2400–2413, 2625–2637; strategy/graph.py and adaptation/graph.py

Evidence:

- Installed LangGraph returns an interrupt payload under result.__interrupt__ for invoke-style execution.
- The worker treats only result.status == failed as failure and otherwise records completion.
- Downstream planning can be chained from a strategy result that is actually waiting for review.
- No Command(resume=...) path exists.
- Checkpointing uses process memory, so review state is lost on restart.
- Rejection yields needs_revision but does not enter a revision loop; the worker can still treat it as non-failed.
- Event-triggered strategy is unconditionally auto-approved.

Impact: the system can visibly claim human governance while continuing without an actual decision.

Fix:

- Model awaiting_review, approved, rejected, needs_revision, and cancelled explicitly.
- Detect __interrupt__ and persist a paused run and review request.
- Use a durable checkpointer and stable thread ID.
- Resume the exact workflow with authenticated, idempotent Command(resume=...).
- Chain only from an approved terminal state.

Mitigation before the fix: disable autonomous strategy-to-planning and adaptation-to-replan chaining; require a manual operator command.

False-positive/runtime check: none for the invoke behavior; it was reproduced against the installed LangGraph version. Deployment could wrap the worker externally, but no such compensating path exists in the repository.

Exit criteria:

- Restart-safe pause/resume integration tests pass.
- Duplicate, stale, and unauthorized decisions are rejected.
- Rejection never emits downstream work.
- Reviewer edits create a new immutable artifact version and return to a revision node.

### P0-02 — Tenant and brand authorization is not a system invariant

Security rule: FASTAPI-AUTHZ-001 / object- and property-level authorization

Severity: P0

Location: backend/app/api/v1 routers and services broadly; agents/workflows/content/nodes.py:485–504, 1462–1468; agents/worker.py regeneration/rebrand handlers; global reviewer and notification selection

Evidence:

- Roles are global, not scoped to an organization/brand membership and capability.
- Many resources are fetched by independently supplied IDs without verifying their shared organization/brand relationship.
- Content can load a brand, calendar item, and products through separate unscoped lookups.
- Reviewers and admin notifications are selected globally.
- Internal NATS messages are routed by subject/payload without a cryptographically bound tenant command envelope.

Impact: an overprivileged UI user, BOLA request, compromised service, or forged internal message may read or mutate another brand’s content, products, assets, approvals, settings, or runs.

Fix:

- Add Organization, Workspace, Membership, RoleBinding, and BrandAccess entities.
- Require organization_id and brand_id on every owned aggregate.
- Resolve compound references in one scoped query or reject mismatches.
- Derive server-side capabilities; never trust the client’s role or brand scope.
- Scope reviewers, notifications, storage keys, jobs, analytics, and provider configuration.
- Sign/version internal command envelopes and require authenticated NATS in production.

Mitigation: operate as a single-client system only; restrict access to a very small trusted team.

False-positive/runtime check: edge or identity-group restrictions may reduce exposure but do not repair missing per-object authorization.

Exit criteria:

- A generated cross-tenant API/job test matrix proves deny-by-default behavior for every CRUD and action route.
- Storage, webhook, scheduler, agent, and UI scopes use the same tenant context.
- Security audit logs include actor, tenant, brand, object, decision, reason, and correlation ID.

### P0-03 — Social credentials are plaintext application data and enter workflow history

Security rule: secret minimization and excessive-data exposure

Severity: P0

Location: backend brand models/schemas/services; frontend/src/types/index.ts:27–38, 78–85; frontend/src/components/brand/tabs/ChannelsTab.tsx:15–21, 47–68; docs/n8n-workflows/markai-publish.json

Evidence:

- Channel access tokens are stored in brand_guidelines-style application data.
- API contracts and frontend state model secrets as readable values with reveal controls.
- The backend sends live tokens in the n8n webhook payload.
- n8n execution data can retain inputs and retry data; repository documentation claims credentials are not stored there, contradicting the workflow.
- The ignored local .env is labeled as synchronized from the VPS and contains a broad populated credential set. Values were deliberately not copied into this report.
- Compose injects the whole .env into backend, frontend, agents, browser-worker, and notifications, giving multiple services credentials they do not need.
- The retained frontend.log contains six OAuth callback URLs with authorization-code parameters. Those codes are likely expired, but authentication codes must never be retained in workspace logs.

Impact: database reads, browser compromise, logs, support exports, workflow execution history, backups, or an overprivileged user can expose publishing credentials.

Fix:

- Rotate all current long-lived credentials after migration.
- Store references in application records; store values in a managed secret vault.
- Use OAuth connections and short-lived tokens where supported.
- Make credential APIs write-only and return only state, scopes, owner, expiry, and last validation time.
- Let the publishing executor resolve a secret just in time; never place it on NATS or n8n payloads.
- Redact credentials from traces, logs, errors, and backups.
- Delete or securely quarantine legacy logs under the owner’s retention policy after incident review; rotate/revoke anything a governed scan identifies as still usable.

Mitigation: disable n8n execution-data persistence for sensitive workflows, limit execution access, and restrict the database while migrating.

False-positive/runtime check: database disk encryption would not prevent application-layer disclosure.

Exit criteria:

- Secret scanning finds no live credential values in API responses, job envelopes, logs, traces, or n8n executions.
- Rotation, revocation, expiry alerts, scope validation, and break-glass access are tested.

### P0-04 — Publishing can produce duplicate external posts

Security/reliability rule: exactly-once external-effect intent

Severity: P0

Location: backend/app/scheduler/publish_checker.py; backend/app/services/publish_service.py; agents/worker.py ACK/chaining paths; n8n publish workflow

Evidence:

- The scheduler does not atomically claim a due item before dispatch.
- Multiple API processes can each run APScheduler without leader election.
- There is no durable publish-attempt object or provider idempotency key spanning claim, upload, publish, callback, and retry.
- Agent messages are ACKed before downstream publish in several paths; downstream failure has no transactional outbox.
- n8n has no deduplication or idempotency guard.

Impact: concurrent schedulers, retries, restarts, delayed callbacks, and ambiguous timeouts can publish the same content more than once or lose the intended publish entirely.

Fix:

- Introduce immutable PublishAttempt records with a unique key per content-version/channel/scheduled-slot.
- Atomically claim with compare-and-set or row locking.
- Use a transactional outbox to dispatch claimed attempts.
- Persist provider request/response IDs and reconcile ambiguous outcomes before retry.
- Run one elected scheduler or use a distributed scheduler/queue.

Mitigation: one scheduler replica, manual publish monitoring, and an operator-side duplicate check.

Exit criteria:

- Concurrency, crash-before/after-send, timeout, callback replay, and retry tests yield at most one provider post.
- Every attempt is recoverable and visible without mutating approved content.

### P0-05 — Webhook trust and lifecycle updates are replayable

Security rule: authenticated, replay-safe webhook processing

Severity: P0

Location: backend/app/api/v1/webhooks.py; backend publishing state handlers; docs/n8n-workflows

Evidence:

- A static shared secret is used rather than a body-bound HMAC signature.
- Timestamp verification is optional or insufficiently bound.
- There is no nonce/event-ID deduplication or publish-attempt binding.
- Delayed callbacks can regress content state.
- The inbound n8n webhook itself lacks authentication.

Impact: captured callbacks can be replayed; fabricated or late messages can mark the wrong item published/failed or regress newer state.

Fix:

- HMAC-sign the raw body plus timestamp and event ID.
- Enforce a short clock window and store event IDs.
- Bind each callback to one PublishAttempt and accept only legal monotonic transitions.
- Authenticate the n8n ingress separately and restrict its network path.

Mitigation: private network allowlisting and aggressive secret rotation, while recognizing that neither provides replay safety alone.

Exit criteria:

- Tampered, expired, duplicate, cross-attempt, and state-regressing callbacks fail closed.

### P0-06 — Evaluation and adaptation do not form a learning loop

Severity: P0 for any claim of autonomous learning

Location: agents/workflows/evaluation/nodes.py:202–215; agents/shared/tools/database.py:712–781; agents/workflows/adaptation/nodes.py:34–166; agents/worker.py:2438–2466

Evidence:

- Evaluation serializes tier, confidence, and data into adaptation_notes; data is encoded again.
- The database getter returns raw rows without lifting or decoding those fields.
- Adaptation filters on nonexistent top-level tier values, leaving its queues empty.
- Tier 1 can be stored as auto_applied before any behavior changes.
- Apply operations only update status; they do not mutate cadence, audiences, channels, templates, strategy, or policy.
- There is no before/after version, holdout, causal measurement, or rollback.

Impact: the product can display learning decisions that never affect future output.

Fix:

- Define a typed AdaptationCommand: target, operation, payload, evidence, risk tier, owner, metric, baseline, version, and rollback.
- Create transactional executors for each supported operation.
- Measure downstream outcomes against baseline/holdout and automatically retain or roll back only within policy.

Mitigation: label the feature “recommendations” and require manual configuration changes until the loop is proven.

Exit criteria:

- An end-to-end test shows evaluation creates one typed command, approval applies a real versioned change, the next plan/content uses it, and later evaluation attributes a measured result.

### P0-07 — Auxiliary services expose SSRF and weak-auth attack surfaces

Security rules: FASTAPI-SSRF-001, FASTAPI-AUTH-001/002, service least privilege

Severity: P0 when internet- or tenant-reachable

Location: browser-worker/app/main.py:73–75, 125–142, 184–206; capture.py:42,77; product_image.py:100–103; notifications/app/main.py and portal.py; Forge proxy configuration

Evidence:

- Browser-worker accepts arbitrary HTTP URLs for screenshots/extraction and follows redirects.
- Private, loopback, link-local, metadata, DNS-rebinding, port, response-size, and redirect destinations are not robustly blocked.
- Domain checks use substring matching.
- Browser-worker and notifications authentication can fail open when their token is blank.
- Notification POST is unauthenticated; SSE uses a global token in a query string plus caller-controlled user_id.
- The attached Forge log contains successful health/generation calls and unrelated external IP requests for root, favicon, and robots.txt, confirming internet discovery/scanning.

Impact: internal service access, metadata theft, arbitrary browsing, notification spoofing/IDOR, secret leakage through URLs, resource exhaustion, and direct abuse of a high-cost GPU service.

Fix:

- Put auxiliary services on private networks; expose only the backend.
- Require workload identity or mTLS and fail startup if auth is absent.
- Use a centralized egress broker with scheme/host/port allowlists, DNS resolution checks before and after redirects, private-range denial, response limits, and concurrency quotas.
- Authenticate notification actions; authorize user-specific streams; move tokens out of query strings.
- Remove public Forge routing or put it behind VPN/identity-aware access and rate limits.

Mitigation: firewall allowlist the API/worker hosts immediately and disable the public route.

False-positive/runtime check: network ACLs were not available for inspection. The supplied access log nevertheless proves the Forge path was reachable by unsolicited clients.

Exit criteria:

- SSRF tests cover IPv4/IPv6, encoded hosts, DNS rebinding, redirects, userinfo, alternate ports, and metadata endpoints.
- No anonymous notification or GPU-generation action succeeds.

### P0-08 — Media authorization and integrity are incomplete

Security rules: FASTAPI-FILES-001, FASTAPI-UPLOAD-001, object authorization

Severity: P0 in multi-tenant production

Location: backend/app/api/v1/files.py; backend/app/services/minio_service.py; upload endpoints; frontend/src/lib/utils.ts:76–99

Evidence:

- File proxy/object references are not consistently bound to caller ownership.
- Some records accept arbitrary object references and deletion paths without cross-record integrity checks.
- Uploads can be buffered without strong size/decompression limits.
- SVG/PDF or other active formats may be served from the application/media origin.
- Client URL sanitization accepts data:image/*, including SVG.
- Approved content can retain mutable asset references during regeneration.

Impact: cross-brand asset disclosure/deletion, storage abuse, decompression denial of service, active-content execution, and approved creative changing after sign-off.

Fix:

- Use opaque MediaAsset IDs and tenant-scoped signed delivery URLs.
- Quarantine uploads; validate magic bytes, dimensions, duration, decoded size, and malware.
- Convert active formats or serve as attachment from an isolated origin.
- Make content versions point to immutable asset versions and hashes.

Mitigation: disallow SVG/PDF uploads and public proxying until safe handling is in place.

Exit criteria:

- Cross-tenant and arbitrary-key tests fail; approved asset hashes cannot change; file policy tests cover malicious and oversized samples.

### P0-09 — Database schema provenance and deployment bootstrap are unsafe

Severity: P0 for repeatable production deployment

Location: backend/alembic/versions/0001_baseline.py; db/init.sql; db/migrations; backend/docker-entrypoint.sh; deployment documentation

Evidence:

- The Alembic baseline is effectively empty.
- A fresh database can be stamped rather than created from a trustworthy migration history.
- Schema ownership is split among init.sql, manual SQL, startup behavior, and Alembic revisions.
- Deployment documentation still claims Alembic is absent and instructs manual DDL, contradicting the repository.
- Cross-record constraints and lifecycle provenance are incomplete.

Impact: fresh environments, disaster recovery, upgrades, and rollback can produce a database that does not match the code while reporting a current revision.

Fix:

- Generate and review a complete baseline from the canonical schema.
- Make Alembic the only schema authority after initial database creation.
- Add migration drift and upgrade-from-every-supported-release tests.
- Back up and restore in a disposable environment before deployment.

Mitigation: block new environment creation and manual schema changes; document the exact known-good database snapshot.

Exit criteria:

- Empty-to-head, current-to-head, downgrade policy, and backup-restore tests pass in CI.
- Application startup never creates or silently stamps missing schema.

### P0-10 — Quality failures can be presented as professional, review-ready output

Severity: P0 for unattended publication and regulated claims

Location: agents/workflows/content/nodes.py:2225–2239, 2857–2892, 3440–3455, 3578–3610, 3940–4000; agents/workflows/video/nodes.py:3735–3849, 4122–4164, 4677–4838, 5111–5135, 6342–6608; generated review and sample assets

Evidence:

- Missing image/background/branding patches can still produce an in_review record.
- Content record validation effectively requires only a caption.
- Critic failure can be treated as approval and ad copy-contract breaches are report-only.
- Video label guard can explicitly ship invented lettering after one retry; chained/hero lanes skip that guard.
- Missing overlays, CTA/end card, audio, or target audio can fail open into review.
- Sample outputs show invented package labels, wrong product geometry, duplicated or oversized logos, missing glyphs, fabricated engagement/follower counts, and generic cross-platform copy.
- Research and report samples display precise claims and confidence without citations.

Impact: reviewers are asked to find machine-detectable defects; client-visible output can be false, misleading, off-brand, inaccessible, or legally risky.

Fix:

- Define a deliverable contract per channel/content type.
- Introduce deterministic final validators for text, claims, asset identity, logo, safe zones, dimensions, duration, audio, CTA, captions, accessibility, and provenance.
- Use passed, needs_repair, quarantined, manual_exception, and failed outcomes.
- Treat evaluator/critic unavailability as unknown, never pass.
- Require claim-to-source mapping and risk-policy approval.

Mitigation: mandatory human creative and fact review using the original product/source material; prohibit health claims and fake platform mockup metrics.

Exit criteria:

- Golden-set regression thresholds and first-review pass-rate targets are met for four consecutive weeks.
- Zero known critical defect can enter the standard approval queue.

### P0-11 — Audit evidence and operational kill switches are not trustworthy

Severity: P0

Location: backend audit service/system API; frontend/src/app/system/audit/page.tsx:57–75,89; brand/user deactivation and running job paths

Evidence:

- Audit writes are incomplete and sometimes swallowed.
- Administrators can hard-delete audit history from the UI.
- Deactivating a brand/user does not reliably cancel queued/running/publishing work or revoke all sessions/tokens.
- Approval history can remain attached to content whose media is later mutated.
- Worker shutdown can mark all globally running jobs failed rather than only its leased jobs.

Impact: forensic evidence can disappear, disabled clients can still publish, and operators cannot prove who approved the exact artifact that went live.

Fix:

- Append-only audit store with retention policy, export, legal hold, hash chaining/WORM option, and separately audited break-glass operations.
- System-wide kill switches at organization, brand, campaign, channel, provider, and global levels.
- Bind approval to immutable content/asset hashes and policy version.
- Use worker lease IDs and scoped cancellation.

Mitigation: remove audit deletion UI and require manual queue inspection when disabling anything.

Exit criteria:

- Kill-switch tests prove no new external effect after activation.
- Every published asset resolves to immutable inputs, approvals, attempt, actor, and provider receipt.

### P0-12 — Known vulnerable dependencies and fail-open production configuration

Security rule: supply-chain hygiene and fail-closed configuration

Severity: P0 before internet production

Location: frontend/package.json and package-lock.json; frontend/src/lib/auth.ts:7–12,161; Python manifests and container image strategy

Evidence:

- npm audit reports 7 production vulnerabilities: 2 critical, 4 high, 1 moderate, including Auth Core/NextAuth, Next.js, nanoid, PostCSS, sharp, and uuid.
- The frontend build logs a FATAL missing-Azure message but exits successfully.
- NEXTAUTH_SECRET is not robustly validated.
- Several Python services use broad lower bounds without a lockfile, weakening reproducibility and vulnerability response.

Impact: known framework/authentication risk and deployments that build successfully despite unusable or unsafe authentication configuration.

Fix:

- Upgrade to patched compatible versions and regenerate the lockfile.
- Add blocking SCA, SBOM, license, secret, and container scans.
- Validate required environment and secret strength at build/startup; exit nonzero.
- Produce locked Python environments and pinned image digests.

Mitigation: restrict deployment access and edge exposure until patched.

Exit criteria:

- No critical/high exploitable production dependency findings without an accepted, expiring exception.
- Missing/placeholder/weak required configuration always prevents startup.

### P0-13 — Production-like diagnostic data and environment identifiers are kept in the workspace

Security rule: data minimization, secret/PII handling, and controlled diagnostic evidence

Severity: P0 until the data is classified and removed or formally governed

Location: docs/build-files/BC-COLUMNS.txt; docs/build-files/FABRIC-TABLES.txt; docs/build-files/SETUP-REMAINING.md; AUDIT_ARTIFACTS/bc_image_coverage.md

Evidence:

- BC-COLUMNS.txt contains raw schema samples spanning customer, transaction, accounting, inventory, user, and operational fields.
- FABRIC-TABLES.txt exposes a 256-table discovery inventory including backup, development, test, temporary, medical, customer, and accounting domains.
- The TXT files are ignored rather than tracked, but remain in the repository workspace and therefore enter backups, support bundles, screen sharing, and agent context.
- Tracked setup/probe documents expose real environment hostnames, application/tenant identifiers, and a named account.
- Operational guides expose precise host topology, public/private addresses, root/deploy account guidance, application IDs, and password-location hints.

Impact: sensitive operational or personal data can propagate outside its intended system without retention, purpose, access, or redaction controls.

Fix:

- Move raw production diagnostics to an encrypted, access-controlled data catalog.
- Replace them in development with synthetic/redacted schema fixtures.
- Classify every exported field and attach owner, purpose, retention, expiry, source, and approval.
- Scan tracked and untracked workspace data in CI/developer preflight.
- Sanitize environment-specific identities in documentation.

Mitigation: immediately restrict workspace sharing/backups and exclude these files from any AI/support bundle.

False-positive/runtime check: the audit did not attempt to prove that every sample maps to a living person or current secret. The categories and environment specificity are sufficient to require formal classification.

Exit criteria:

- A data owner confirms the raw exports are removed or governed.
- Automated tracked/untracked scans find no unapproved PII, credential, or infrastructure identifier.
- Any actual credential found during the governed scan is rotated.

---

## 6. Product and feature-design audit

### 6.1 The missing organizing object: Campaign

Campaign exists as a partial backend concept, but it is not the first-class operating object joining:

- business objective and funnel stage
- audience and market
- offer, products, evidence, and restrictions
- approved strategy and creative brief versions
- channels, placements, budget, cadence, and schedule
- content variants and asset rights
- tasks, owners, reviewers, and SLAs
- experiments, holdouts, KPIs, attribution, and results
- learning decisions and rollback

Without that spine, workflows operate mainly at brand, run, calendar-item, and content levels. Context is repeatedly re-inferred, campaign_id is often null, and analytics cannot reliably connect output to business outcomes.

Recommendation: make Campaign the product home and execution boundary. Every agent stage should consume and emit versioned campaign artifacts, not mutable prose blobs.

### 6.2 Feature truthfulness and completeness

| ID | Severity | Finding | Evidence / impact | Recommendation |
|---|---|---|---|---|
| PROD-01 | P1 | The UI promises governed approvals, learning, and health more strongly than the implementation supports | Human review bypass, adaptation no-op, unknown services rendered healthy | Add capability-status labels and hide/disable claims until contract tests pass |
| PROD-02 | P1 | Intelligence reports are not evidence-grade | Source fields exist but citations, capture dates, and snapshots are not rendered; raw output is exposed | Claim-level citations, source packets, freshness, confidence calibration, contradiction states |
| PROD-03 | P1 | A report fabricates completion | Intelligence report renders monthlyThemes.length or 12 | Render incomplete state; prohibit synthetic counts |
| PROD-04 | P1 | Analytics can convert errors into zeroes | Promise.allSettled results feed empty KPI cards without coverage warnings | Per-source freshness/coverage/error state and last-known data separation |
| PROD-05 | P1 | “Optimal posting times” is only posting-frequency | Heatmap counts when posts happened; no outcome normalization | Rename it or compute outcome-normalized lift with sample size and confidence |
| PROD-06 | P1 | Revenue and funnel outcomes are absent | Engagement dominates; no conversion, pipeline, revenue, ROI, CAC, or attribution | Build outcome/attribution model before autonomous optimization |
| PROD-07 | P1 | Product image search has a visible no-op | ProductsTab handler contains only a comment | Implement as a durable job or remove the control |
| PROD-08 | P1 | Bulk operations disguise partial failure | Product include/exclude, multi-channel create, and document apply can partially succeed then toast success | Server batch jobs with idempotency, per-item results, retry, cancellation |
| PROD-09 | P1 | Apply & Re-plan runs without a meaningful diff | It can trigger expensive destructive replanning with no changes | Diff, impact preview, scope confirmation, immutable rollback |
| PROD-10 | P1 | Content beyond seven days is silently hidden | Generation allows up to 30 days | Date-range control, hidden count, no invisible lifecycle records |
| PROD-11 | P1 | Kanban omits approved and publishing states | Items disappear during critical handoffs | One canonical lifecycle and exhaustive state tests |
| PROD-12 | P1 | Channel capability is overstated | n8n only partially handles Instagram/Facebook/LinkedIn; X/TikTok/YouTube absent in that path | Publish a capability matrix driven by verified adapters |
| PROD-13 | P2 | Important routes are weakly discoverable | Approvals, Learning, Prompts, and product intelligence are not all in primary navigation | Role-aware information architecture and task-based navigation |
| PROD-14 | P2 | Global brand context is fragmented | Local selectors/dialog defaults diverge; stale closures can apply results to a prior brand | URL-backed workspace/brand context with request sequencing |
| PROD-15 | P2 | Notifications are not an operational inbox | Five-item view, silent errors, local clear even on server failure, no actions/history | Durable actionable notification center with ownership and escalation |
| PROD-16 | P2 | Professional editorial operations are missing | No assignment, SLA, threaded comments, legal lane, checklist, diff, escalation, or mobile approval | Build an editorial review workspace |
| PROD-17 | P2 | Asset management is a gallery, not a DAM | No rights, source, license expiry, renditions, similarity, safe zones, accessibility metadata | Rights-aware DAM and immutable asset lineage |
| PROD-18 | P2 | Localization is not a first-class constraint | English/Mauritius defaults and hardcoded season/time assumptions | Locale, market, timezone, hemisphere, language, cultural and legal policy |

### 6.3 Recommended product operating model

Each campaign should move through explicit gates:

~~~text
Brief accepted
  -> evidence pack approved
  -> strategy version approved
  -> channel plan validated
  -> creative variants generated
  -> deterministic QA
  -> specialist review
  -> legal/claims review when required
  -> immutable approval
  -> publish attempt
  -> provider reconciliation
  -> outcome measurement
  -> bounded adaptation proposal
  -> experiment/approval
~~~

Every gate needs an owner, contract, SLA, outcome, exception path, and audit event.

### 6.4 Feature inventory and readiness

| Product area | Current value | Readiness | Principal next move |
|---|---|---|---|
| Brand onboarding/system | Broad profile, channels, logos, competitors, products | Beta | Version the brand system and separate secrets/rights/policies |
| Product catalog | BC/Fabric sync, filters, imagery | Prototype/Beta | Canonical ProductDTO, authoritative media, provenance, batch jobs |
| Intelligence | Research, trends, reports, personas, competitors | Prototype | Evidence packets, citations, freshness, hypothesis labels |
| Strategy | Positioning, pillars, cadence, themes | Prototype | Objective/KPI/budget strategy version and durable approval |
| Planning/calendar | High-volume calendar generation | Prototype | Atomic PlanVersion, campaign binding, completeness contracts |
| Still-content studio | Copy, images, branding, edits, mockups | Beta with safety gaps | Per-channel contracts and non-bypassable final QA |
| Video studio | Multi-lane generation, assembly, audio, overlays | Beta with safety gaps | Uniform final validator, rights, cost and rendition lineage |
| Approvals | Queue, history, actions | Prototype | Hash-bound editorial/legal/accessibility workspace |
| Publishing | Direct and n8n paths | Unsafe for unattended use | Attempts, idempotency, vault, reconciliation, adapter registry |
| Analytics | Engagement/KPI dashboards | Prototype | Coverage/freshness truth, event warehouse, conversions, cost |
| Learning | Tiered adaptations UI/workflow | Nonfunctional | Typed change/executor/canary/measurement/rollback |
| Provider routing | Discovery and active/fallback controls | Prototype | Evaluated staged activation, budget/capability routing |
| System operations | Health, queues, runs, audit | Prototype | Honest readiness, full DAG/trace/cost, immutable audit |
| Users/access | Global roles and activation | Unsafe for multi-client | Tenant membership/capabilities and lockout protection |
| Notifications | Toast/SSE/Teams foundation | Unsafe/incomplete | Authentication, ownership, persistence, actions, retry |

### 6.5 Capability expansion after the trust foundation

To become a complete marketing operating system, add capability families in this order:

1. Owned web and lifecycle: landing pages, blog/SEO, email/CRM, reusable lead magnets.
2. Organic channel depth: native carousels/stories/short video/long video, community response, social listening.
3. Experimentation and conversion: governed variants, first-party conversion events, incrementality.
4. Paid media: creative adaptation and recommendations first; budget/spend execution only at A3 dual-approval.
5. Partnerships/influencers: brief, contract/rights, disclosure, deliverable, approval, performance.
6. Sales enablement: campaign-to-CRM handoff, product collateral, case studies, nurture.

Each capability needs a verified adapter contract, explicit unsupported state, rights/consent policy, golden evaluations, and business-outcome semantics before the UI advertises it.

---

## 7. UI/UX and accessibility audit

### 7.1 Browser-tested experience

The browser audit covered sign-in, the authenticated application shell with representative mocked API state, all 15 major application routes, four HTML sample reports, and the sequence map at desktop and mobile widths.

What works:

- Sign-in renders and behaves coherently.
- The desktop dashboard has a polished visual system, consistent spacing, readable information hierarchy, and convincing product breadth.
- Core routes provide meaningful empty states instead of blank pages.
- The mobile shell stacks content without broad horizontal overflow.
- The mobile drawer opens reliably and its primary controls have labels.
- The report templates have strong visual hierarchy and print-oriented styling.

Observed failures:

- Mobile dashboard chart-card headings and controls crowd and wrap awkwardly.
- The sequence-map title is clipped under the mobile hamburger and dense flow/list text overlaps.
- Strategy report status and fourth KPI clip on narrow screens.
- The mobile sidebar lacks dialog semantics, focus trapping, Escape behavior, and aria-current.
- There is no skip link or robust addressable main landmark; the fixed h-screen/overflow shell can complicate zoom and reflow.
- Calendar drag/drop has no equivalent keyboard operation.
- Several report cards, table rows, product actions, filters, and checkboxes are mouse-oriented or lack accessible names.
- Charts and heatmaps have no table/text alternative.
- Hover-only product gallery controls are weak on touch and keyboard.
- No reduced-motion override is defined.

The appropriate release target is WCAG 2.2 AA. W3C recommends WCAG 2.2 for current applicability and explicitly adds criteria for focus visibility, dragging alternatives, target size, and accessible authentication: https://www.w3.org/TR/WCAG22/

### 7.2 UX finding register

| ID | Severity | Finding | Evidence | Remediation / acceptance |
|---|---|---|---|---|
| UX-01 | P1 | Settings can overwrite real configuration after a read failure | Defaults remain active and Save remains enabled in frontend/src/app/settings/page.tsx:103–179 | Separate unloaded/error/loaded state; disable save until authoritative read; require version/ETag and review diff |
| UX-02 | P1 | Last-admin and self-lockout safeguards are absent | Role/active and bulk-admin actions in settings/users/page.tsx:141–165, 254–351 | Server-enforced last-admin rule; step-up auth, reason, confirmation, and audit |
| UX-03 | P1 | Client redirects are mistaken for access control | frontend/src/lib/hooks.ts:20–37; many callers render before redirect and ignore hasAccess | Server capability enforcement; withhold privileged content until resolved |
| UX-04 | P1 | Error, not-found, empty, and zero are conflated | Brand allSettled flow falls through to “not found”; analytics uses empty zeroes | Typed states for unauthorized, 404, partial, stale, outage, and genuinely empty |
| UX-05 | P1 | Selection can act on hidden records | Content-stage, trends, and users selection survives filter/scope changes | Clear or summarize hidden selection; server action preview |
| UX-06 | P1 | Bulk scope is misleading | “No Image” processes only the first 10; products fetch up to 10,000 client-side | Paginated server jobs with disclosed scope, progress, cancel, and result ledger |
| UX-07 | P1 | Gallery deletion is too easy | No confirmation; hover-only actions | Confirmation, undo/soft-delete, keyboard/touch-visible actions |
| UX-08 | P1 | Report delivery is not professional | “Download PDF” invokes print; no controlled export/version cover sheet | Server PDF export with version, sources, approvals, accessibility, and redaction |
| UX-09 | P1 | Raw diagnostics can reach page users | Intelligence report exposes raw output | Restrict to privileged debug view and redact secrets/PII/tool payloads |
| UX-10 | P1 | Model/provider changes are one-click production changes | providers/page.tsx:125–187, 302–319 | Draft → evaluate → canary → approve → activate, with rollback |
| UX-11 | P1 | Health can display unknown as healthy | ServiceHealth.tsx:32 defaults to green check | Explicit Unknown/Stale states, checked-at time, reason, dependency detail |
| UX-12 | P1 | System overview uses misleading partial aggregates | Only 50 runs; queue component mixes live and lifetime counts | Server time-window metrics, queue age, throughput, error taxonomy, SLOs |
| UX-13 | P2 | Sidebar information architecture hides important work | Approvals, Learning, Prompts, and product-intelligence routes are weakly discoverable | Organize nav around Campaigns, Produce, Review, Publish, Learn, Operate |
| UX-14 | P2 | Mobile density and clipping reduce confidence | Browser evidence on dashboard, reports, and sequence map | Responsive content priority; collapse secondary controls; device-width visual tests |
| UX-15 | P2 | Accessibility semantics are inconsistent | Missing landmarks, focus management, aria-current, labels, keyboard alternatives | Automated axe plus manual keyboard/screen-reader release gate |
| UX-16 | P2 | Calendar is not accessible or operationally rich | Drag-only operation; no assignment/SLA/conflict representation | Keyboard reschedule, agenda view, dependency/conflict and owner indicators |
| UX-17 | P2 | Polling and completion feedback are fragmented | Per-item five-second watchers and independent timers | Central job event stream with timeout, cancel, retry budget, last update |
| UX-18 | P2 | Clear-all notifications can lie | Local state clears even when API fails | Optimistic rollback or server-confirmed mutation; durable history |
| UX-19 | P2 | Platform previews can mislead clients | Fake counts and outdated/generic chrome | Label as simulation; remove metrics; test exact channel constraints and safe areas |
| UX-20 | P2 | No accessible content-quality checklist | Review emphasizes a preview and action buttons | Show claims/evidence, rights, alt text, captions, policy, platform, and diff status |

### 7.3 Target navigation and workspace design

Recommended primary navigation:

1. Campaigns — briefs, objectives, budgets, audiences, deadlines
2. Intelligence — evidence, competitors, products, trends, claims
3. Studio — briefs, variants, assets, per-channel adaptations
4. Review — editorial, visual, legal, accessibility, approvals
5. Calendar & Publishing — schedule, preflight, attempts, reconciliation
6. Performance — outcomes, attribution, experiments, insights
7. Learning — proposed adaptations, evaluations, canaries, rollback
8. Operations — runs, DAG, costs, providers, incidents, audit
9. Brand & Access — brand system, DAM, channels, members, policies

The global header should always display organization, brand, campaign, environment, and automation mode. No action should depend on a brand value hidden only in local component state.

### 7.4 Review-workspace acceptance criteria

- Reviewer sees the exact channel payload and immutable asset hash.
- Source/claim, product, rights, disclosure, accessibility, and platform preflight are visible in one place.
- Material changes invalidate approval automatically.
- Comments are threaded and anchored to content/asset regions.
- Rejection requires a structured category and optional remediation instruction.
- Assignment, due time, escalation, and reviewer authority are explicit.
- Mobile approval is fully keyboard/screen-reader accessible.
- Preview simulations clearly state what is approximate and never fabricate popularity metrics.

---

## 8. Frontend code-quality and architecture audit

### 8.1 Positive engineering signals

- Strict TypeScript compilation passes.
- The Next.js App Router structure is clear.
- API/types/constants are centralized.
- React rendering does not use dangerouslySetInnerHTML, eval, document.write, or a raw-HTML Markdown plugin.
- External-link target handling did not show the common unsafe blank-target pattern.
- Radix-based primitives provide a good foundation for accessible dialogs, tabs, selects, and menus.
- Standalone container output is deterministic from a lockfile and runs non-root.

### 8.2 Frontend finding register

| ID | Severity | Finding | Evidence / impact | Recommendation |
|---|---|---|---|---|
| FE-01 | P0 | Vulnerable production dependency graph | npm audit: 2 critical, 4 high, 1 moderate | Patch, lock, regression-test, and block CI on actionable critical/high findings |
| FE-02 | P1 | No automated frontend safety net | No test files/config/scripts for unit, component, E2E, or accessibility | Vitest/RTL + Playwright + axe; cover critical lifecycle and permission journeys |
| FE-03 | P1 | Lint fails with correctness rules | 10 errors, 71 warnings | Make lint zero-warning in CI; fix effects, dependencies, ref/render, purity, types |
| FE-04 | P1 | Configuration validation fails open | auth.ts logs FATAL but build succeeds; NEXTAUTH_SECRET not validated | Typed environment schema evaluated at build/startup; terminate nonzero |
| FE-05 | P1 | Bearer token exists in browser session | auth.ts:141–150 | Short lifetime, strong CSP, minimal scopes, server-side proxy consideration |
| FE-06 | P1 | No visible CSP in Next configuration | next.config.ts defines several headers but not CSP | Verify edge; otherwise nonce-based CSP, initially report-only |
| FE-07 | P1 conditional | SVG/data-image path can permit active content | utils.ts:76–99 and SVG upload UI | Disallow/sanitize/transform; isolated media origin and safe headers |
| FE-08 | P1 | API client lacks resilience contracts | No global timeout, retry classification, response validation, correlation, idempotency | Typed query/mutation layer, AbortSignal, runtime schemas, single-flight auth |
| FE-09 | P1 | Concurrent 401s can cause sign-in storms | api.ts:120–125; session cache timer race | Single-flight refresh/re-auth and deterministic expiry |
| FE-10 | P1 | Prompt weight debounce loses writes | One shared timer in prompts/page.tsx:82,97–107 | Per-record debouncer or explicit save; rollback/refetch on failure |
| FE-11 | P1 | Trend refresh can bind to stale brand | Intelligence polling closure | Brand-scoped job ID, cancellation/sequencing, query-key isolation |
| FE-12 | P1 | Multi-write mutations lack transaction/reconciliation | Promise.all and sequential loops across content/products/documents | Server batch command and per-item ledger |
| FE-13 | P2 | Client-side role hook results are unused | Repeated hasAccess/roleLoading unused warnings | Capability-aware route wrapper; remove decorative guards |
| FE-14 | P2 | Five god-components concentrate risk | 974–1,896-line pages/components | Domain state machines, hooks, schemas, small tested views |
| FE-15 | P2 | Dead/duplicated components exist | PerformanceGrid and ReportContentEditor unused; WorkflowMonitor duplicated | Remove or integrate; dependency graph/dead-code CI |
| FE-16 | P2 | Report parser drops introductory content | ContentCalendarStrategy.tsx:76–83,188–193 | Preserve every section; raw/source equivalence fixtures |
| FE-17 | P2 | Engagement chart drops supplied metrics | Impressions/engagement rate unused | Metric selector, definitions, denominators, benchmarks, table |
| FE-18 | P2 | UI-local storage participates in lifecycle truth | opened-content and post-watch stores | Treat browser state as presentation cache only; server is canonical |
| FE-19 | P2 | Next/image optimizations are inconsistently bypassed | Lint warnings/raw images | Define media component supporting signed assets and previews |
| FE-20 | P2 | Build artifact metadata appears in authored inventory | ignored tsconfig.tsbuildinfo | Keep ignored; clean in audit/CI contexts; not a product issue |

Concrete lint risks include:

- set-state-in-effect in WorkflowStatus, KanbanBoardInner, Header, and Sidebar
- impure Date.now during OverviewTab render
- ref access during LogoEditor render
- an any in BrandOnboarding
- invalid empty-interface patterns in input and textarea primitives
- stale/missing hook dependencies and unused authorization results

### 8.3 Frontend target architecture

- Server-derived SessionContext containing tenant, memberships, capabilities, brand scope, and feature flags
- URL-backed WorkspaceContext for brand/campaign/time/locale
- Runtime-validated API client with generated schemas and correlation/idempotency headers
- Query cache for reads; command/job abstraction for mutations
- One shared lifecycle package generated from a canonical state-machine definition
- Route-level loading/error/partial/stale contracts
- Domain modules for campaign, evidence, content, review, publishing, measurement, and operations
- Design-system accessibility tests and viewport snapshots
- Feature availability derived from verified backend/channel capabilities, not hardcoded UI promises

---

## 9. Backend, API, data, and security audit

### 9.1 Security posture

Authentication has a reasonable Entra foundation, but authorization and data boundaries are insufficient for a multi-brand product. The central policy must become: an authenticated identity has no access unless a server-derived capability explicitly permits an action on that tenant/brand/object.

The security review followed framework-specific FastAPI and Next.js guidance for authentication, object authorization, response minimization, uploads, files, CORS, host/proxy trust, SSRF, secrets, webhooks, dependency hygiene, and safe deployment.

### 9.2 Backend finding register

| ID | Severity | Finding | Evidence / impact | Recommendation |
|---|---|---|---|---|
| BE-01 | P0 | No true tenant/brand authorization model | Global roles and broad object-by-ID access | Tenant membership/capabilities, scoped repositories, RLS, negative test matrix |
| BE-02 | P0 | Social credentials are readable plaintext fields | Brand guideline persistence and API response paths | Vault references and write-only connection APIs |
| BE-03 | P0 | Publishing race and no idempotency boundary | Scheduler/service dispatch | PublishAttempt + atomic claim + outbox + reconciliation |
| BE-04 | P0 | Webhook replay/state regression | Static secret and weak attempt binding | Raw-body HMAC, timestamp/event dedup, monotonic attempt transitions |
| BE-05 | P0 | Object proxy lacks complete ownership enforcement | files.py/object keys | Tenant-scoped MediaAsset IDs and signed delivery |
| BE-06 | P0 | Audit log can be hard-deleted and writes are incomplete | Audit service/API/UI | Append-only audit and governed retention |
| BE-07 | P0 | Schema provenance is broken | Empty baseline and split schema authorities | Complete reviewed Alembic baseline; one migration authority |
| BE-08 | P1 | Cross-record integrity is not enforced | Brand/content/calendar/product/media IDs accepted independently | Compound scoped resolution and DB foreign/check constraints |
| BE-09 | P1 | Deactivation is not a kill switch | Queued/running/publish operations survive | Hierarchical cancellation/revocation and fenced executor checks |
| BE-10 | P1 | Provider upload URLs can receive bearer tokens without strict allowlists | Publisher upload flow | Per-provider URL allowlist, DNS/IP validation, never forward auth cross-host |
| BE-11 | P1 | APScheduler scales unsafely | Each API process can schedule | Leader election or external scheduler |
| BE-12 | P1 | Entra revocation/identity refresh can fail open | Cached identity paths | Short session, explicit revocation, fail-closed privileged actions |
| BE-13 | P1 | User creation bypasses access-grant governance | Global user-admin paths | Invitation/membership workflow with least privilege and approval |
| BE-14 | P1 | DB state can commit before NATS publish | No transactional outbox | Outbox within same transaction; idempotent inbox consumer |
| BE-15 | P1 | Health endpoints are shallow/fail-open | Dependency failure not reflected consistently | Liveness vs readiness; required dependency checks and stale timestamps |
| BE-16 | P1 | Outbound URL policy is redirect/DNS unsafe | URL validators and fetchers | Central egress policy and network enforcement |
| BE-17 | P1 | Uploads can exhaust memory/decoder | Buffering and weak decompression bounds | Streaming quarantine, byte/pixel/frame/duration limits |
| BE-18 | P1 | Active uploads may share application origin | SVG/PDF handling | Convert or isolate with attachment/CSP/nosniff |
| BE-19 | P1 | DB/object storage operations lack compensation | Partial media/database writes | Saga/transactional state with orphan sweeper |
| BE-20 | P1 | Business Central sync can be partial/destructive | Last-location-wins, partial batches, hard deletes | Snapshot/stage/reconcile, provenance, soft lifecycle, per-location inventory |
| BE-21 | P1 | Shared pyodbc usage is concurrency-unsafe | Fabric service shared connection behavior | Pool per request/task or serialized executor |
| BE-22 | P1 | Approval updates race | No compare-and-set/version on decision | Unique active decision and optimistic versioning |
| BE-23 | P1 | Approval is not bound to immutable artifact | Regeneration can mutate media | Hash-bound approval and new version on every edit |
| BE-24 | P1 | State machines conflict | Backend, agents, UI, scheduler, n8n differ | One generated canonical lifecycle with legal transitions |
| BE-25 | P1 | Content “versioning” mutates in place | Update semantics | Immutable ContentVersion and current pointer |
| BE-26 | P1 | Model discovery can disable unrelated configuration | Discovery/availability updates | Provider-scoped observations and staged activation |
| BE-27 | P1 | Image verification is hardcoded/fail-open | Regeneration gate | Versioned policy and explicit unknown/quarantine |
| BE-28 | P1 | Long AI operations run inside requests | Timeout/resource coupling | Durable async jobs with status events |
| BE-29 | P1 | JSONB settings suffer lost updates | Whole-document writes | Typed tables or JSON patch with ETag/version |
| BE-30 | P1 | Prompt A/B controls do not implement a valid experiment | Weighting without assignment/outcome design | Experiment registry, sticky assignment, exposure and result analysis |
| BE-31 | P1 | Caption quality lacks deterministic validation | LLM-centric review | Claims, length, CTA, prohibited terms, language, accessibility rules |
| BE-32 | P1 | Event detection trusts model memory | Immediate writes without sources | Evidence-backed proposals and human confirmation |
| BE-33 | P1 | Trends can mislead | Weak source/recency/scoring contract | Source timestamps, trend window, volume/baseline, uncertainty |
| BE-34 | P1 | Stale-run reaper has no heartbeat lease | Age-only cleanup | Worker lease, heartbeat, fencing token |
| BE-35 | P1 | NATS configuration and messages lack strong convergence/identity | Optional auth and weak message IDs | Required auth, schema/version, ID, tenant, signature, DLQ |
| BE-36 | P1 | Raw operational exceptions can escape | API/service errors | Stable public error codes; internal correlated details only |

### 9.3 Data-model findings

The database has broad entity coverage, but needs aggregate boundaries and immutable versions.

Problems:

- Brand guidelines combine ordinary settings and secrets.
- Content, media, approvals, publishing, and engagement are not linked through immutable version/attempt identities.
- Strategy and research are represented partly as agent runs rather than first-class approved artifacts.
- Adaptation payloads are stored as opaque notes.
- Lifecycle values are duplicated across layers.
- Relationships often rely on application convention rather than tenant-aware constraints.
- Product data from Business Central, Fabric, and agent DTOs uses inconsistent names and semantics.
- A “latest completed” query often substitutes for explicit approved/current-version pointers.

Recommended canonical entities:

- Organization, Workspace, Membership, RoleBinding, CapabilityGrant
- Brand, BrandSystemVersion, BrandPolicyVersion, ChannelConnection
- Campaign, CampaignBriefVersion, Objective, AudienceVersion, OfferVersion
- EvidenceSource, EvidenceSnapshot, Claim, ClaimEvidence, ClaimPolicyDecision
- ProductSourceRecord, ProductVersion, InventorySnapshot, PriceSnapshot
- StrategyVersion, PlanVersion, CalendarVersion, CalendarItemVersion
- ContentConceptVersion, ChannelAdaptationVersion, ContentVersion
- MediaAsset, MediaRendition, RightsGrant, Release, ProvenanceManifest
- ReviewTask, ApprovalReceipt, ExceptionWaiver
- WorkflowRun, StepRun, MessageInbox, OutboxEvent, WorkerLease
- PublishIntent, PublishAttempt, ProviderReceipt, ReconciliationEvent
- MetricEvent, MetricSnapshot, Experiment, Assignment, Exposure, Outcome
- AdaptationProposal, AdaptationExecution, EvaluationResult, Rollback
- AuditEvent and Incident

Every owned table should include organization_id. Most campaign artifacts should also include brand_id, campaign_id, immutable version, schema version, content hash, created_by, created_at, and supersedes_id.

### 9.4 API contract requirements

- Explicit request and response schemas; reject unknown write fields where appropriate
- No ORM/internal objects returned directly
- Stable error codes and request/correlation IDs
- Idempotency-Key on every command that can be retried
- If-Match/version for mutable configuration
- Async 202 + job resource for long work
- Pagination and server filtering for collections
- Per-command capability checks and scoped object resolution
- Structured batch results
- Rate, payload, upload, and compute quotas by tenant
- Liveness separate from dependency-aware readiness
- OpenAPI protected or disabled in public production
- Trusted host/proxy configuration verified at the edge

### 9.5 Security strengths to retain

- Entra signature/issuer/audience validation intent
- Rejection of unknown and inactive users
- Authentication route-sweep tests
- Placeholder-secret refusal in several production settings
- CORS and several security headers are configured
- Parameterized SQL/ORM use dominates
- File path traversal and range behavior have tests
- Containers generally run non-root
- Business Central has retry/circuit-breaker handling

### 9.6 Browser-worker engineering findings

Beyond the P0 SSRF/authentication issue:

- A synchronous MinIO client is called from async request paths and can block the event loop.
- Returned media URLs can use the internal http://minio:9000 hostname.
- There is no global semaphore, tenant quota, browser pool budget, response-size budget, or robust cancellation.
- Social/product image scraping depends on brittle third-party markup and unclear image rights.
- Search/download work is often sequential.
- Raw exception strings can be returned.
- A degraded health payload still uses HTTP 200, and Compose checks only HTTP success.
- Dependency manifests use lower bounds without a reproducible lock.
- There are no automated tests.

Positive: the container runs non-root and separates browsing from the main API, which is the correct architectural direction. Keep that separation, but turn it into a private, quota-controlled retrieval service returning immutable evidence/media IDs rather than arbitrary response bodies/URLs.

### 9.7 Notification-service findings

Beyond the unauthenticated /notify and SSE IDOR:

- A single global token is placed in the SSE query URL, leaking into logs/history/referrers.
- Pub/sub is ephemeral; users cannot reliably read, replay, acknowledge, or audit notifications.
- New Valkey clients can be opened per message without clear lifecycle management.
- Health does not establish dependency readiness.
- No idempotency, payload/recipient bounds, rate limit, retry policy, durable delivery record, or DLQ exists.
- Raw errors can escape.
- SQL dependencies appear unused.
- There are no tests.

Target: durable Notification records plus per-channel DeliveryAttempt, ownership/capabilities, authenticated event stream, templates, deduplication, retry/backoff, quiet hours, preferences, escalation, and actionable links.

### 9.8 LiteLLM/model-gateway findings

- Broad provider wildcards weaken the intended model allowlist.
- A one-hour global cache needs verified tenant/source/policy-aware keying; otherwise identical prompts may create stale or cross-context results.
- Very long 600-second timeouts and retries can amplify cost and queue blockage.
- drop_params silently changes requests and already masks an invalid image-guard temperature parameter.
- There are no clear fallback groups by capability/risk, per-tenant keys, hard budgets, circuit breakers, or quality/cost/latency routing policies.
- Direct OpenAI/Gemini calls in review tooling bypass the gateway.

Target:

- explicit capability registry for text, vision, image, video, embeddings, and graders
- tenant/purpose-isolated credentials, cache keys, budgets, and logs
- prompt/model/tool/policy pinning per run
- timeout/retry/circuit/fallback policies by operation
- evaluated canary activation and one-click rollback
- quality, latency, availability, and cost telemetry
- no provider wildcard in production without an approved policy

---

## 10. Agent team, jobs, tasks, and workflow audit

### 10.1 Architectural verdict

The current subsystem is eight specialized workflows behind one prefix-routed worker. It is better described as a staged pipeline than an autonomous team:

- limited supervisor reasoning
- nearly linear graph edges
- almost no durable inter-agent negotiation
- no independent evidence/claims authority
- no first-class editorial or legal role
- incomplete revision loops
- process-memory checkpoints for human review
- broad shared tools rather than least-privilege role contracts
- weak outcome attribution and cost control

The target should not be an unconstrained agent swarm. It should be a deterministic campaign control plane around specialized, replaceable agents. Agents propose and evaluate; policy gates decide; a non-LLM executor performs external side effects.

### 10.2 Current role-by-role assessment

| Current role | What it does well | Principal failure | Target role contract |
|---|---|---|---|
| Product Intelligence | Connects BC/Fabric/product imagery and promotability ideas | Incompatible DTO fields, first-50/100 limits, missing brand/upsert fields, invented margin reasoning | Ground product facts only from systems of record; persist provenance and commercial inputs |
| Research | Produces a broad competitor, audience, gap, and persona narrative | Website field mismatch, first-result “official” site, no claim citations/snapshots, write-only vector memory | Build evidence packets and hypotheses; never present model memory as source |
| Strategy | Produces positioning, pillars, cadence, themes, and review step | Synthetic scores, generic cadence, weak objectives, duplicate runs, broken human pause | Versioned objective/KPI strategy grounded in approved evidence and constraints |
| Planning | Produces large calendars and campaign-like structures | Partial batches complete, warning-only language, null campaign IDs, type collapse, purge-before-insert | Stage a validated plan version and atomically activate only after completeness/approval |
| Still Content | Extensive image/brand/product/copy tooling | All-channel duplication, future-month bug, single-platform unwrap bug, fail-open QA, fabricated mockups | Produce one channel contract per planned item; quarantine missing mandatory deliverables |
| Video | Strong assembly, visual, audio, overlay, end-card, and multi-shot machinery | Invented text can ship; some lanes skip guard; CTA/audio/overlay/duration failures fail open | Deterministic final delivery validator and immutable rendition ledger |
| Evaluation | Creates performance narratives and recommendations | LLM-only, weak sample/data controls, self-reported confidence | Deterministic metrics + declared experiments + calibrated graders |
| Adaptation | Exposes tiered review concept | Payload mismatch and status-only “apply” | Typed reversible changes measured against a baseline/holdout |

### 10.3 Workflow and delivery findings

| ID | Severity | Finding | Evidence / impact | Recommendation |
|---|---|---|---|---|
| AG-01 | P0 | Human interrupt is bypassed | See P0-01 | Durable checkpoint, pause resource, authenticated resume |
| AG-02 | P0 | Adaptation loop is nonfunctional | See P0-06 | Typed command/executor/evaluation |
| AG-03 | P1 | Agent ownership checks are inconsistent | Content/calendar/product/brand IDs resolve separately; global reviewers | Tenant-scoped command context and compound resolution |
| AG-04 | P1 | NATS auth is optional | Not required in production configuration | Fail startup without authenticated NATS; workload identity |
| AG-05 | P1 | Messages lack an authoritative envelope | Prefix routing and broad payload persistence | Versioned schema with ID, tenant, actor, scope, causation, signature |
| AG-06 | P1 | Current message is ACKed before downstream stage exists | worker.py downstream chaining | Transactional outbox; ACK only after durable successor intent |
| AG-07 | P1 | Broad exceptions are ACKed and discarded | worker.py:2639–2650 | Retryable/permanent taxonomy and DLQ |
| AG-08 | P1 | Delivery limit ends in loss | max_deliver=5 without DLQ/replay workflow | DLQ with reason, operator replay, poison isolation |
| AG-09 | P1 | Duplicate in-flight work can be silently ACKed | Non-content/video duplicate behavior | Idempotent inbox and schedule retry/observe existing run |
| AG-10 | P1 | Worker concurrency has weak global bounds | Push consumers lack explicit service budgets | max_ack_pending, per-provider semaphore, tenant quotas |
| AG-11 | P1 | Shutdown marks other workers’ jobs failed | Global update of running agent_runs | Worker lease ID; release only locally fenced work |
| AG-12 | P1 | Original untrusted payload is persisted | Worker stores full message instead of whitelisted state | Validate schema; store canonical sanitized inputs |
| AG-13 | P1 | Run history is deleted as control flow | Content queue deletes completed planning/calendar history when empty | Never delete provenance; explicit no-work result |
| AG-14 | P1 | “Latest completed” skips stale/incompatible stages | Reuse ignores approval, version, scope, freshness | Pin exact input/output artifact versions |
| AG-15 | P1 | Content batch cap strands item 101+ | Worker selects only 100 and no continuation | Cursor-based bounded claims until queue drained |
| AG-16 | P1 | Queue-less trigger activates every planned item | Ignores desired production horizon | Rolling horizon, campaign scope, operator policy |
| AG-17 | P1 | Special regeneration/rebrand always ACKs | Errors swallowed; no normal run/retry record | First-class versioned workflow using same guards |
| AG-18 | P1 | Regeneration accepts remote URLs outside central policy | Unbounded product/logo/image URLs | Egress broker, media IDs, download policy |
| AG-19 | P1 | Regeneration mutates approved creative | Deterministic object names/current metadata | Immutable assets and fresh approval |
| AG-20 | P2 | Agent observability is too shallow | No step-level trace/cost/tool policy in UI | OpenTelemetry + immutable step ledger + cost/SLO dashboard |
| AG-21 | P2 | Agent tool permissions are broad | Roles share powerful DB/browser/social/storage functions | Per-role allowlisted tools and read/write capability budgets |
| AG-22 | P2 | Prompts/models are not fully reproducible | Latest routing and dynamic discovery | Pin prompt/model/tool/policy/source versions per run |

### 10.4 Product intelligence

Detailed defects:

- Raw DB products use fields such as bc_item_no and vendor fields, while workflow grouping/matching expects sku and vendor.
- Fabric fallback records omit required brand_id, bc_item_no, vendor_no, price, and inventory.
- Workflow metadata and image_url are not persisted by the called upsert.
- New upserted records can be inactive.
- Matching processes only 100 products and promotability only 50; the remainder silently disappears.
- The first web search result can be treated as the official brand site.
- “Margin potential” is inferred without margin or cost-of-goods data.
- Image sourcing is serial and lacks durable provenance.
- No complete product-intelligence artifact is stored.

Required fix: one ProductDTO with source-specific adapters, staged bulk reconciliation, source/field provenance, price/inventory timestamps, margin inputs, image rights and hashes, resumable batching, and an approved ProductIntelligenceVersion.

### 10.5 Research

Detailed defects:

- Competitor positioning, strengths, weaknesses, content strategy, threats, and follower estimates are inferred from thin inputs.
- The prompt produces website_url, but later code reads website, discarding model-provided competitor sites.
- Search result URLs, excerpts, timestamps, licenses, source class, and evidence-to-claim links are not persisted.
- Personas include demographics, income, behavior, platform, buying triggers, and engagement times without a required factual basis.
- Qdrant receives gap/persona embeddings, but production workflows do not retrieve similar research; memory is effectively write-only.
- “Latest completed” research is accepted without approval, freshness, or schema version.

Required fix: a research agent may create Observations and Hypotheses only. Every observation must cite an immutable EvidenceSnapshot. Unsupported persona details remain hypotheses with a validation plan.

### 10.6 Strategy

Detailed defects:

- Competitors receive synthetic 1–5 scores without an evidence model.
- Cadence begins from generic Mauritius/platform conventions rather than capacity or measured outcomes.
- Business objective, funnel stage, KPI target, revenue target, media budget, operational capacity, offer, experiment allocation, and risk class are not required.
- Twelve-month theme completeness is weakly validated.
- Strategy storage can create a second completed agent run, producing ambiguous provenance.
- Latest strategy selects completed, not approved.

Required fix: StrategyVersion must include objective tree, assumptions, evidence, audiences, propositions, offers, channel hypotheses, budget/capacity, KPI definitions, experiments, risks, and approval. Plans pin the exact version.

### 10.7 Planning and calendar

Detailed defects:

- A failed batch returns an empty list and the aggregate logs rather than fails a completeness contract.
- Language and repetition violations are warnings that never reject.
- Product validation may skip rows while the run still completes.
- campaign_id is written as null.
- Rich types such as carousel, story, article, newsletter, and ad collapse into post/reel.
- Existing plans are committed deleted before insert.
- Purge failure permits duplicates; insert failure after purge loses the working plan.
- Zero inserts can still report completed.
- Invalid channel/type values become Instagram/post and invalid dates can become “now.”

Required fix: construct PlanVersion in staging; validate counts, dates, types, channel constraints, products, themes, budgets, risk and uniqueness; review; then atomically switch the campaign’s active plan pointer. Invalid values fail, never coerce.

### 10.8 Still-content workflow

Detailed defects:

- A future post can use the worker’s current month rather than the scheduled month.
- Each channel-specific calendar item can be adapted to all enabled channels, duplicating planned concepts.
- A valid one-platform result can be incorrectly unwrapped.
- Background generation failure returns no image without failed status.
- Missing image or logo can yield an empty branding patch.
- Content validation only guarantees a caption; hook, CTA, image, brand asset, QA, and platform conformance are optional.
- Critic failure can pass.
- Ad copy-contract failure is advisory only.
- Mockup generation falls back to four platforms even when none are configured.
- Platform mockups embed fake engagement/follower values.

Required fix: one ContentRequirement per channel/placement with mandatory fields, schema validation, deterministic copy/claim/accessibility checks, and an explicit quarantine lane.

### 10.9 Video workflow

Strengths:

- Anchor-frame, product-swap, overlay, render-quality, audio, end-card, multi-shot, provider, storage, and shutdown behavior all have dedicated tests.
- The code anticipates a wide range of generative-media failure modes.

Remaining defects:

- Native label guard ships invented lettering after one failed retry.
- Chained/hero paths do not invoke that guard.
- Motion retries can retain a frozen/churning original.
- Overlay burning can return the unburned master.
- CTA can be withheld from footage for an end card, then disappear if end-card attachment fails.
- Silent or off-target audio may ship.
- Missing ffmpeg/ffprobe can collapse a multi-shot plan to an approximately five-second single call.
- These outcomes can still enter normal review.
- Fifteen bundled M4A beds have no license/source manifest; one reaches roughly +1.9 dB true peak.

Required final-delivery validator:

- exact channel dimensions, codec, frame rate, duration, size, and safe areas
- frame-sampled product, logo, unintended-text, continuity, hand/anatomy, and artifact checks
- mandatory hook/CTA/overlay/end-card contract
- audio presence, loudness, true peak, clipping, dialogue/music balance, and caption sync
- rights, source, AI disclosure, and provenance metadata
- immutable output hash and rendition lineage

Failure must repair or quarantine, never silently pass to ordinary review.

### 10.10 Target specialized team

| Target role | Allowed autonomy | Prohibited behavior |
|---|---|---|
| Campaign Director | Build dependencies, scope, deadlines, and recommendations | Publish, change spend, waive policy |
| Evidence Researcher | Retrieve allowlisted sources and build evidence packets | Use model memory as evidence or invent facts |
| Brand/Product Grounder | Resolve claims from approved brand/catalog records | Override source-of-truth values |
| Strategist | Propose audiences, messages, channels, and experiments | Activate budgets or targeting |
| Creative Director | Produce brief, concept system, and creative evaluation criteria | Approve its own output |
| Copy Agent | Generate variants using approved claims and language rules | Introduce unsupported claims |
| Design Agent | Generate compositions and renditions | Use unlicensed assets or mutate approved media |
| Video Agent | Generate storyboard, shots, edit, audio, captions, and renditions | Bypass final technical/visual QA |
| Claims & Compliance Agent | Validate, block, or escalate with cited policy | Self-approve high-risk content |
| Channel Adapter | Create exact channel payloads and preflight results | Call publish APIs |
| Editorial QA | Score clarity, brand voice, CTA, accessibility, and platform fit | Change approved artifacts in place |
| Publisher Executor | Execute the exact approved payload idempotently | Exercise creative judgment |
| Analyst/Experimenter | Analyze declared metrics and controlled experiments | Optimize directly on vanity engagement |
| Learning Curator | Propose versioned changes and eval plans | Promote without regression/canary approval |

### 10.11 Autonomy tiers

| Tier | Policy |
|---|---|
| A0 | Automatic reads, classification, draft research, simulation |
| A1 | Policy-gated internal artifact creation when deterministic checks pass |
| A2 | Human approval for public publishing, customer messaging, claims, audience changes, new integrations, and material brand changes |
| A3 | Dual approval for regulated/sensitive claims, paid-spend changes, crisis messaging, minors, and health/finance/legal topics |
| A4 | Prohibited: unsupported claims, fake endorsements, protected-class targeting, rights/consent violations, approval bypass, or silent disclosure removal |

---

## 11. Generated content, reports, and media quality

### 11.1 Review image set

The final Healthspan/RingConn/SiBionics posts and 12 platform mockups are visually polished at first glance, but not consistently professional-grade:

- generic AI-stock composition rather than a distinctive brand system
- large/inconsistent logos and simplistic black title bars
- product replacement changes real device geometry and sensor detail
- approximate or invented package lettering
- missing French accents
- medical/product claims without cited evidence
- repeated copy across platforms instead of native adaptation
- fake platform engagement/follower metrics
- missing emoji glyph squares
- obsolete/generic platform chrome and excessive whitespace

The generation script also:

- runs substantial work at import time rather than behind a main entrypoint
- initializes vendor clients directly and bypasses LiteLLM governance
- uses hardcoded Windows font paths
- references ringconn_2.webp while the asset is ringconn_2.png
- hardcodes Healthspan and sample/fake metrics
- relies on older named model versions

This review code should become a reproducible evaluation harness, not a one-off local script.

### 11.2 Historical image QA evidence

| Set | Result | Meaning |
|---|---|---|
| NatureSpan, 16 images | 4 clean, 2 minor, 10 reject; 20 recorded defects | Ad lane skips brand review; hallucinated packs/anatomy, contrast and empty-frame failures |
| Healthspan, 13 images | 6 clean, 4 blockers, 3 major; 15 defects | Duplicate/colliding logos, opaque assets, invented lettering |
| FancyFinds, 10 images | 4 publishable, 6 redo | Product/headline collisions, truncation, wrong props, garbled marks, brief drift |
| BC coverage | 39/40 found through web search; 0 confirmed through BC because authentication blocked | Rights/provenance and source-of-truth coverage are not proven |

Across the three image sets, the reports classify only 16/39 (41%) as publishable and 23/39 (59%) as requiring rework; only 12/39 are explicitly fully clean. Even the “publishable” threshold is too permissive in examples that retain gibberish partner packaging or fabricated medical-device/retailer details.

The reports demonstrate useful defect awareness, but they are not automated release gates and some older “all clean” documentation contradicts these results.

### 11.3 Sample video set

Ten NatureSpan olive-oil MP4s were inspected. Technical encoding is consistent:

- 1080 × 1920
- 30 fps
- H.264 video plus AAC audio
- about 20 to 32.5 seconds
- approximately 159.8 MB total

Positive qualities:

- generally attractive cinematic lighting
- smooth technical encoding
- several credible food/ingredient shots
- useful side-by-side evidence of pipeline evolution

Professional-quality failures:

- no consistent real NatureSpan product pack
- invented/garbled bottle labels
- bottle and product continuity changes
- repetitive oil/bread/tomato imagery
- an unexplained empty glass bottle
- weak or awkward opening/CTA text in some versions
- the Sora benchmark is cinematic but lacks brand, product, story, and CTA
- no visible rights/provenance/disclosure record
- no subtitle tracks or accompanying transcripts
- v7 is about −21.4 LUFS, roughly 7 LU quieter than the otherwise approximately −14 LUFS set

### 11.4 Report quality

The sample strategy, research, planning, and calendar reports are attractive but not decision-grade:

- research states 47 sources and 94% confidence without citations
- precise competitor/persona/salary/statistical claims are unsupported
- strategy repeats an unsupported 87% vitamin-D absorption claim
- planning invents products, prices, discounts, testimonials, staff, partnerships, targets, and WhatsApp capability
- calendar content includes questionable health, fasting, detox, and date assumptions
- confidence percentages are decorative rather than calibrated
- IDs, durations, completion ages, and status values are hardcoded
- no source appendix, data freshness, reviewer, model/prompt version, change history, or controlled export

The output must distinguish:

- observed fact
- sourced claim
- model inference
- strategic hypothesis
- proposed experiment
- placeholder awaiting client confirmation

### 11.5 Professional content acceptance gate

An asset cannot be review-ready unless:

- all required channel deliverables exist
- every externally verifiable statement maps to current evidence
- product identity/specification/price/inventory map to the system of record
- product and logo fidelity checks pass
- rights/release/license and expiry are valid
- AI-generation/edit disclosure policy is satisfied
- language/locale/brand voice/prohibited-term rules pass
- accessibility metadata exists
- deterministic platform preflight passes
- model graders are available and above calibrated thresholds
- no critical visual/editorial defect is known
- the complete lineage and cost record is stored

### 11.6 Provenance target

Adopt a rights-aware DAM and C2PA/IPTC-compatible provenance model. C2PA 2.4 is the current specification set for certifying media source and history: https://spec.c2pa.org/specifications/specifications/2.4/index.html

Each asset should store:

- cryptographic hash and perceptual hash
- original and derived renditions
- creator/source/commission
- rights owner, license, territory, channel, purpose, expiry
- model/property/person releases
- AI system/version/prompt metadata
- transformation history
- accessibility metadata
- retention/takedown status
- C2PA manifest and validation state

---

## 12. Channel publishing and external integration audit

### 12.1 Current channel reality

The product has two publishing approaches:

- direct backend publishers for Meta, LinkedIn, and YouTube
- an n8n webhook workflow that partially covers Instagram, Facebook, and LinkedIn

The UI and documentation imply broader, more uniform channel capability than the current adapters provide.

### 12.2 n8n workflow findings

| ID | Severity | Finding | Impact | Fix |
|---|---|---|---|---|
| PUB-01 | P0 | n8n publish webhook has no inbound authentication | Anyone reaching it may trigger work | Authenticated private ingress, signed command, allowlisted caller |
| PUB-02 | P0 | Live platform tokens are included in input payload | Secrets retained in execution/history/logging | Vault-side resolution by connection ID |
| PUB-03 | P0 | No idempotency or deduplication | Duplicate provider posts on retry | PublishAttempt key and execution-level dedup |
| PUB-04 | P1 | No robust retry/backoff/reconciliation | Transient and ambiguous failures are mishandled | Provider-specific retry classification and remote status check |
| PUB-05 | P1 | Instagram publishes immediately after container creation | Media may not be ready | Poll container status until ready/fail/timeout |
| PUB-06 | P1 | Facebook image URL is sent as a feed link | Not equivalent to native photo post | Use the appropriate photo/media API and verified upload |
| PUB-07 | P1 | LinkedIn path ignores image media | Text-only result despite visual creative | Upload media and use its Image URN |
| PUB-08 | P1 | X, TikTok, and YouTube are missing in n8n | Capability mismatch | Adapter registry must advertise verified support only |
| PUB-09 | P1 | Preview and production share a risky shape | Preview can accidentally activate | Separate environment/credentials/endpoints and hard no-publish preview executor |
| PUB-10 | P1 | n8n version/docs assumptions drift | Compose uses 1.82.1 while docs describe newer behavior | Pin supported version and contract-test imports/execution |
| PUB-11 | P1 | Preview leaves content stuck in publishing | It deliberately never calls back | Preview must use a separate non-publishing lifecycle and artifact |
| PUB-12 | P1 | Workflow response mode conflicts with documented upgrade | JSON retains responseMode lastNode while changelog says newer n8n is incompatible | Versioned import/activation contract test |

LinkedIn’s current Posts API explicitly requires uploading an image to obtain an Image URN before creating an image post: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?tabs=curl&view=li-lms-2026-04 and https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-06

n8n’s official security audit specifically checks unprotected webhooks and missing security settings: https://docs.n8n.io/hosting/securing/security-audit/

### 12.3 Required channel-adapter contract

Every channel adapter must declare and test:

- supported media and post types
- exact file, duration, ratio, text, hashtag, title, alt-text, caption, and thumbnail constraints
- authentication scopes, account identity, token expiry/refresh/revocation
- API version and sunset date
- upload lifecycle and asynchronous processing states
- edit, delete, takedown, and remote reconciliation semantics
- disclosure/AI-generated-content fields
- analytics availability and metric definitions
- sandbox/test account support
- idempotency strategy and provider request/remote IDs

Canonical publish lifecycle:

~~~text
approved
  -> claimed
  -> preflighted
  -> uploading
  -> provider_processing
  -> remotely_verified
  -> published

Any step may enter:
  retry_wait, reconciliation_required, failed_permanent,
  cancelled, or takedown_requested
~~~

Upload success is not publish success.

---

## 13. Evaluation, experimentation, analytics, and learning

### 13.1 Current evaluation is not statistically valid

The evaluation workflow sends a short performance window to an LLM and asks it to infer best times, trends, themes, recommendations, confidence, and expected impact. It does not enforce:

- minimum sample sizes
- exposure/reach normalization
- age and seasonality normalization
- deterministic metric definitions
- control/treatment assignment
- significance or uncertainty
- selection and survivorship bias checks
- conversion or revenue outcomes
- attribution windows
- predeclared hypotheses/stopping rules

An LLM-generated confidence value is not statistical confidence.

### 13.2 Required truth layers

Analytics must visibly distinguish:

1. Observed — provider or first-party events
2. Derived — deterministic ratios/aggregates
3. Attributed — credit assigned by a declared model/rule
4. Incremental — causal lift supported by controlled or quasi-experimental evidence
5. Inferred — model interpretation or hypothesis

Current dashboards blur observed/derived/inferred states and can show missing data as zero.

### 13.3 Target event model

~~~text
campaign
  -> content_version
  -> channel_variant
  -> publish_attempt / remote publication
  -> exposure
  -> interaction
  -> session / lead
  -> conversion
  -> revenue and cost
  -> experiment decision
  -> adaptation proposal
~~~

Store provider metrics as dated immutable snapshots. Never accumulate them repeatedly as if each pull were a delta unless the provider explicitly returns deltas.

### 13.4 Experiment requirements

Every experiment needs:

- hypothesis and owner
- eligibility and unit of assignment
- sticky control/treatment allocation
- primary outcome and guardrail metrics
- baseline and measurement window
- minimum detectable effect/sample plan
- exclusions and contamination risks
- stopping rule
- predeclared analysis method
- cost and risk budget
- winner/rollback policy

Raw engagement must never directly rewrite prompts or strategy.

### 13.5 Evaluation stack

1. Deterministic schema, platform, safety, legal, and file checks
2. Claim entailment and citation checks
3. Product/logo/visual-identity comparison
4. Language, accessibility, and brand-style rules
5. Calibrated model graders
6. Blind human editorial/compliance labels
7. Shadow/canary production evaluation
8. Business outcome and causal experiment analysis

Dataset slices must cover all channels, formats, industries, locales, ambiguous briefs, contradictory/stale evidence, unavailable tools, provider errors, prompt injection, sparse analytics, and brand edge cases.

### 13.6 Learning-promotion gate

- A proposal identifies one typed target and operation.
- It cites evaluation evidence and affected campaigns.
- It has an explicit risk tier and approval authority.
- It produces a new immutable prompt/model/policy/strategy/config version.
- The full regression suite passes.
- A shadow or canary cohort meets quality, latency, and cost thresholds.
- Rollback is one version switch.
- The effect is measured against a baseline/holdout.
- The proposal is retained, revised, or rolled back with an audit event.

---

## 14. Infrastructure, deployment, CI/CD, and recovery

### 14.1 Compose and service topology

Positive:

- Base and VPS Compose configurations validate.
- Nineteen services form a credible local/VPS platform.
- Images are generally pinned.
- Memory limits exist.
- Postgres, MinIO, NATS, Valkey, and Qdrant are represented explicitly.
- Core application containers run non-root.

Risks:

- single-node topology and stateful local volumes create a large failure domain
- container_name is set broadly, preventing ordinary horizontal scaling patterns
- no CPU limits in Compose
- no systematic read-only filesystem, dropped capabilities, seccomp/AppArmor, or no-new-privileges policy
- whole-file environment injection expands every compromised service’s credential reach
- no replica/leader strategy for stateful or scheduled work
- host Docker socket remains mounted read-only to Traefik, which still grants a powerful control surface
- health checks are uneven and do not establish end-to-end readiness
- production observability is disabled by default in the VPS overlay

### 14.2 Edge and network findings

- Traefik’s CSP permits unsafe-inline styles and broad connection targets.
- Permissions-Policy is missing at the edge even though the frontend sets one.
- The Forge host relay exposes host port 9100 through a socat/proxy path.
- The relay uses an unversioned alpine/socat image and has rate limiting but no VPN, mTLS, or IP allowlist.
- Runtime logs confirm unsolicited external scanners reached that endpoint.
- Internal object-storage and service URLs sometimes escape into API results.
- Network segmentation and egress enforcement are not defined as code.

Required target:

- public edge only for frontend/API and necessary authenticated provider webhooks
- private service networks with service identity/mTLS
- no public GPU, browser, notification, database, object store, NATS, Valkey, Qdrant, n8n admin, Grafana, or Docker control path
- explicit egress proxy/allowlists for agents and browser work
- cloud firewall and host policies represented and tested as code

### 14.3 CI/CD gaps

Current CI does not comprehensively gate:

- frontend lint/test/E2E/accessibility
- browser-worker and notification tests
- agent coverage thresholds
- integration tests across Postgres/NATS/MinIO/Valkey/Qdrant
- migration drift and empty-to-head upgrades
- Compose contract/smoke tests
- secret scanning
- dependency/SBOM/license/container scanning
- policy-as-code and infrastructure checks
- generated content golden evaluations
- artifact signing/provenance
- deployment environment approval
- post-deploy smoke, rollback, and SLO validation

The deploy workflow uses SSH StrictHostKeyChecking=accept-new rather than a pinned known-host key. A dedicated document incorrectly suggests disabling checking is safe because a key is pinned.

The VPS redeploy script has several strong controls, but prints a generated Traefik dashboard password into deployment output. It lacks canary/blue-green rollout and automated rollback.

Its optional destructive wipe/skip-backup modes can remove Qdrant even though the backup script does not capture Qdrant. Running containers and a backend health response are treated as adequate post-deploy readiness; recent-log output can also surface sensitive data.

### 14.4 Backup and recovery

Current nightly backup:

- dumps and compresses Postgres
- verifies gzip
- rotates for 14 days
- optionally backs up MinIO/offsite

Gaps:

- optional MinIO/offsite absence still reports success
- no client-side encryption or immutable retention
- no periodic restore drill
- no alert delivery/SLO
- Qdrant, n8n state, Valkey durability, certificates, configuration, audit evidence, and secret metadata are incomplete
- MinIO client credentials can persist in root configuration
- no documented RPO/RTO by subsystem

Required acceptance:

- encrypted, immutable, offsite backup of every authoritative state store
- daily automated verification and scheduled full restore rehearsal
- documented RPO/RTO
- restore into a clean environment using migration provenance
- secret reattachment and provider reconciliation
- evidence that backups honor retention/deletion/legal-hold policies

### 14.5 Infrastructure register

| ID | Severity | Finding | Recommendation |
|---|---|---|---|
| INF-01 | P0 | Public Forge/GPU attack surface | Remove public route; VPN/workload identity/rate/compute budgets |
| INF-02 | P1 | Single-node/stateful failure domain | Managed state or replicated design; tested restore/failover |
| INF-03 | P1 | Scheduler has no leader election | External scheduler or distributed lease |
| INF-04 | P1 | Deploy emits a generated password | Never print secrets; write directly to secret store/file with strict permissions |
| INF-05 | P1 | SSH host trust is not pinned | Managed known_hosts fingerprint |
| INF-06 | P1 | Backups are partial and optional | Required encrypted offsite set and restore drills |
| INF-07 | P1 | Docker socket exposure | Socket proxy with minimal API or provider alternative |
| INF-08 | P1 | Production observability is opt-out/off | Make required stack or managed equivalent part of release |
| INF-09 | P2 | Container hardening is inconsistent | Read-only rootfs, cap_drop ALL, no-new-privileges, tmpfs, seccomp |
| INF-10 | P2 | Resource control lacks CPU/concurrency budgets | CPU/IO limits plus app-level semaphores and tenant quotas |
| INF-11 | P2 | No staging environment | Reproducible staging with safe provider sandboxes and synthetic data |
| INF-12 | P2 | No canary/automatic rollback | Progressive rollout and SLO-gated rollback |

---

## 15. Observability, incident response, and cost governance

### 15.1 Configuration findings

- Grafana’s home dashboard points to missing markai-overview.json.
- Promtail searches /var/log/containers/*.log while the mounted Docker logs are nested in per-container directories, so it may collect nothing.
- Traefik emits metrics on its web/port-80 entrypoint while Prometheus targets traefik:8080.
- OTel exports traces only to a debug destination; no durable trace backend such as Tempo/Jaeger is configured.
- Grafana’s derived trace field points to Prometheus, which is not a trace store.
- Prometheus attempts to scrape NATS /varz JSON as if it were Prometheus exposition.
- Qdrant and MinIO scrapes are likely to fail when authentication is enabled.
- Alert rules exist, but no Alertmanager or notification routing is configured.
- Promtail has no explicit secret/PII redaction.
- Production Compose disables the observability profile by default.
- The application lacks one propagated correlation chain across campaign, workflow, asset, approval, publish, and provider receipt.

### 15.2 Required correlation model

~~~text
organization_id
  -> brand_id
  -> campaign_id
  -> workflow_id
  -> agent_run_id
  -> step_run_id / trace_id
  -> artifact_id
  -> approval_id
  -> publish_attempt_id
  -> provider_remote_id
~~~

OpenTelemetry treats traces, metrics, logs, and contextual propagation as complementary signals: https://opentelemetry.io/docs/concepts/observability-primer/

### 15.3 Required dashboards and SLOs

- Campaign pipeline: age, stage, blocked reason, SLA
- Agent DAG: step duration, failure taxonomy, retry, model/tool versions
- Publishing: queue age, attempt state, provider latency, duplicate/reconciliation/takedown
- Quality: deterministic failure reasons, model/human scores, first-pass approval, edit distance
- Evidence/claims: stale/unsupported/contradicted counts
- Platform health: dependency readiness and data freshness
- Cost: token/media/provider/infrastructure cost per approved asset, campaign, conversion, and incremental conversion
- Security: authorization denies, suspicious file/URL/webhook activity, credential expiry
- SLO/error-budget view by tenant and critical journey

### 15.4 Incident tooling

Operators need:

- cancel, pause, retry, requeue, quarantine, reconcile, and replay actions
- full dependency/input/output/attempt view
- stable error codes and correlated redacted logs/traces
- runbook links and on-call ownership
- immutable incident timeline
- channel/brand/global kill switch
- safe provider takedown/revoke action

---

## 16. Testing, dependency, and engineering-quality audit

### 16.1 Test-distribution risk

The headline 1,442 passing tests is encouraging but misleading if treated as complete assurance:

- frontend has zero automated tests
- browser-worker has no tests
- notifications has no tests
- n8n workflows have no contract tests
- infrastructure and restore behavior have no automated end-to-end tests
- agent overall coverage is 56%, but critical files are much lower:
  - research: about 11%
  - strategy: about 15%
  - product intelligence: about 15%
  - evaluation: about 18%
  - adaptation: about 19%
  - content: about 23%
  - worker: about 31%
  - agent database adapter: about 19%
- tests heavily mock integration contracts, allowing the LangGraph interrupt and adaptation schema failures to pass

The Promptfoo suite is also far below a production evaluation program: two prompts and five tests form a global matrix, so content cases can run against the research prompt with missing variables and vice versa. The shallow synthetic English cases do not import the production prompt registry. It has no deterministic factual/brand/legal/medical checks, source-entailment cases, multilingual/adversarial slices, golden image/video assets, repeated seeds, human labels, regression thresholds, or CI promotion gate. Its 3–8 hashtag instruction also conflicts with the current five-or-fewer policy.

### 16.2 Required test pyramid

| Layer | Required coverage |
|---|---|
| Unit | State machines, validators, policies, metric definitions, DTO adapters |
| Contract | API schemas, NATS envelopes, provider adapters, n8n imports, storage, database |
| Integration | Real Postgres/NATS/MinIO/Valkey/Qdrant and durable workflow checkpoints |
| Workflow | End-to-end research → strategy → plan → content → review → publish → evaluate |
| Chaos | Worker death, redelivery, timeouts after remote success, storage/DB split failure |
| Security | Cross-tenant matrix, SSRF corpus, webhook replay, upload corpus, privilege/kill switch |
| Content eval | Golden briefs/assets/claims across channels/locales and known generative defects |
| Browser | Core role journeys, mobile viewports, keyboard, screen reader, axe |
| Recovery | Empty-to-head migrations, upgrade, encrypted backup, clean restore |
| Performance | Queue throughput, GPU/browser concurrency, large catalogs, annual plans |

### 16.3 Release gates

- Zero P0 failures
- No new high-severity dependency issue without a named, expiring exception
- Lint/type/build/unit/contract/integration/E2E/accessibility all pass
- Minimum coverage by critical module, not only global percentage
- Migration and restore rehearsal pass
- Golden content set meets quality thresholds with zero safety/claim regressions
- Chaos suite proves no lost job or duplicate publish
- Staging provider smoke tests reconcile remote status
- SBOM, signed containers, provenance, and secret scan generated

### 16.4 Code-quality findings

- Backend Ruff: five issues, including unused imports, E712 comparison, and unused regex import.
- Agent Ruff: 41 issues, ten in production source.
- Several source files are extremely large, especially content/video nodes, worker, report pages, and brand/product UI.
- Broad exception handling often converts failure into a normal result.
- Raw dict/JSON contracts cross service boundaries.
- Duplicate URL/sanitization/state logic exists between backend and agents.
- Configuration defaults and hardcoded values can silently change production semantics.
- Several scripts execute on import or are not designed as reusable/testable commands.
- Python environments lack a unified lock/reproducible dependency strategy.

Recommended modularization rule: split by domain invariant and test boundary, not arbitrary line count. First extract lifecycle, command envelope, artifact versioning, URL/media policy, publishing attempt, and quality-gate packages.

---

## 17. Documentation and operational-truth audit

### 17.1 Major contradictions

| Documentation claim | Repository/runtime reality |
|---|---|
| VPS deployment is manual as root | Another guide forbids root and specifies a deploy user; CI deploy also exists |
| Alembic is absent and DDL is manual | Alembic exists, but baseline provenance is broken |
| Stack has 11 or 16 services | Current Compose has 19 |
| No automatic deployment | GitHub deployment workflow and redeploy script exist |
| Production observability is enabled | VPS overlay disables it by default |
| Audit report says 23/23 clean and no issues | Current lint, SCA, workflow, security, and output evidence contradicts it |
| Dependencies are pinned/latest | Python ranges are broad; n8n and other docs/versions drift; frontend has critical/high advisories |
| n8n does not store credentials | Tokens are sent in workflow input, which can be retained in execution history |
| Content pipeline has a stable 11-step DALL-E flow and older hashtag policy | Current implementation/model/provider and master policy differ |
| StrictHostKeyChecking=no is safe because a key is pinned | Disabling host verification does not pin the host |
| All generated assets are professionally clean | Historical QA and current visual inspection show high reject/redo rates |

### 17.2 Documentation risks

- Public/personal IPs, a machine name, host topology, and a public key are committed in VPS guides.
- Firewall/root-access instructions are unsafe or contradictory.
- README references nonexistent requirements.txt files and an npm test script the frontend does not define; its 8 GB RAM prerequisite is below the configured full-stack memory plus host overhead.
- UPGRADE_LOG is useful history but not a canonical current-state source.
- MASTER_UPGRADE_SPEC has strong goals but describes several capabilities as implemented or production-enabled when they are not.
- AI server docs normalize a public Forge endpoint and an at-logon scheduled task.
- Local image docs acknowledge a text guard catching only a small minority of invented text and sometimes shipping the original.
- Test guide is substantially manual and preview workflows log data while leaving ambiguous publish state.
- Architecture and implementation plans mix dated design intent with current operational instructions.
- SEQUENCE_MAP claims completeness while depicting X publishing, Qdrant retrieval, and working evaluation/adaptation more strongly than current behavior supports; its clickable div navigation is not keyboard-semantic.
- Meta setup documentation and committed n8n nodes reference different Graph API versions.

Additional material findings:

- The implementation/setup plan instructs Fabric item-picture ingestion, but the later production probe establishes that the lakehouse item table has no picture/media/image field and BC Tenant Media is not replicated. The recorded coverage is 39 web-search images, one missing, and zero BC-sourced images. Web search is therefore being treated as a silent downgrade from product truth.
- BC-COLUMNS.txt stringifies values and includes sentinel dates, negative inventory examples, and no native type/nullability/key/freshness/company-scope contract.
- FABRIC-TABLES.txt proposes mappings across all discovered tables, including backup/dev/test/old/temp and sensitive business domains, instead of a curated allowlist.
- AUDIT-FIX-LOOP-AGENT-PROMPT.md authorizes broad process killing, dependency upgrades, migrations, cache clearing, and looping until “zero defects” without target validation, backup, staging, external-side-effect authority, or rollback.
- universal-audit-loop-prompt.md is broader and more thoughtful, but still prescribes implement/commit/push/tag behavior without a separate authorization gate.
- Existing QA reports contain strong analysis but are mutable narrative files without commit SHA, asset/source hashes, model/prompt/settings, deterministic rule outputs, reviewer identity, or signed disposition.
- Several audit documents cite exact source line numbers but omit the commit SHA, so their evidence drifts as files change.
- “Minor because invisible at feed size” is used as a quality rationale in places; this is inadequate for paid, reusable, zoomable, or client-delivered professional assets.

### 17.3 Documentation target

Maintain:

- one generated architecture/service catalog
- one deployment runbook per environment
- one authoritative schema/migration guide
- one current channel capability matrix
- one state-machine specification generated into backend/agents/frontend tests
- ADRs for security/tenant/publishing/provenance decisions
- an operator runbook per alert and external provider
- a model/prompt/tool/policy registry
- data dictionary and retention/rights map
- incident, backup, restore, and disaster-recovery evidence
- versioned client-facing report methodology and confidence definitions

Automatically validate documentation claims against Compose services, environment schema, API routes, model registry, channel adapters, migrations, and test results.

For audit-agent prompts, separate:

1. read-only evidence collection;
2. an approved remediation plan;
3. explicitly authorized code/data/infrastructure mutations;
4. independently authorized commit, push, migration, deployment, notification, and publishing actions.

Every action phase needs exact scope, backup, rollback, environment, data classification, and stop conditions. “Zero defects” is not an auditable completion criterion.

---

## 18. Runtime log analysis

### 18.1 Forge log supplied by the user

Observed:

- Uvicorn starts and listens on 127.0.0.1:9100 behind a relay/proxy.
- Health, image, and job requests complete successfully.
- No application error appears in the excerpt.
- Unrelated external clients request /, /favicon.ico, and /robots.txt.

Interpretation:

- The generation service was functional for the captured requests.
- External scanner traffic confirms the relayed endpoint was publicly discoverable; it is not merely a theoretical topology concern.
- The log does not include enough production telemetry: no timestamps, structured request/job correlation, tenant/actor, duration, model/version, queue time, cost, auth decision, or redaction marker.

Action:

- Remove public exposure or put the service behind private workload identity/VPN.
- Add structured redacted logging and a trace spanning request → Forge job → asset hash.

### 18.2 ComfyUI log supplied by the user

Observed:

- RTX 4090 with about 24.5 GB VRAM, 192 GB system RAM, CUDA and PyTorch is detected.
- ComfyUI 0.33 starts; Triton is absent.
- SQLite reports non-transactional DDL.
- Multiple prompts complete successfully in roughly 13.28, 21.10, 22.24, 31.88, and 32.79 seconds.
- Model loading repeatedly consumes about 19–20.5 GB VRAM.
- No generation error appears in the excerpt.

Interpretation:

- Local image inference is viable and reasonably fast on the captured host.
- The leading Alembic plugin messages belong to ComfyUI internals, not evidence that MarkAI’s backend migrations ran.
- Repeated loading suggests an opportunity to measure warm/cold model residency and throughput.
- The log lacks job/campaign/tenant correlation, prompt/model/workflow hashes, output asset hash, queue time, utilization, cost allocation, and quality result.

Action:

- Add a local-provider adapter with explicit model/version/capability, warm pool, concurrency, timeout, and health telemetry.
- Treat the GPU worker as replaceable compute; keep authoritative job/artifact state in MarkAI.

### 18.3 Historical frontend.log

The ignored root frontend.log contains 7,359 lines and appears to be a stale Next 15 development log:

- 941 occurrences of “error”
- at least 575 HTTP 500 responses, depending on log-line pattern
- OAuth timeouts
- six retained OAuth callback URLs containing authorization-code parameters
- broken .next cache/required-server-files paths

It has no dependable timestamps and does not prove current production failure. It does prove that historical development logs can grow, persist in the repo directory, and be hard to interpret.

Action: treat the file as sensitive, review it under the incident/retention policy, rotate anything still usable, and remove it through an authorized secure-cleanup workflow. Adopt structured environment-tagged logs, rotation/retention, correlation IDs, secret redaction, callback-query filtering, and no persistent ad hoc dev log in the workspace.

---

## 19. Target architecture: governed campaign operating system

### 19.1 Design principle

MarkAI should become a deterministic campaign control plane around specialized, replaceable agents.

Agents may research, propose, draft, adapt, inspect, and evaluate. Policy gates determine what is allowed. A non-LLM executor performs public, costly, destructive, or irreversible actions using an exact approved payload.

~~~text
Identity / tenant / capability / consent / policy control plane
                              |
          Versioned campaign brief and objective graph
                              |
                +-------------+-------------+
                |                           |
         Evidence plane                DAM / rights plane
     sources, claims, snapshots     assets, releases, licenses,
       freshness, confidence          renditions, provenance
                +-------------+-------------+
                              |
                    Durable workflow engine
       leases, budgets, retries, checkpoints, outbox, cancellation
                              |
                    Bounded specialist agents
 Research -> Grounding -> Strategy -> Creative -> Claims/Compliance
          -> Channel Adaptation -> Editorial/Visual QA
                              |
                 Immutable artifact + policy decision
                              |
            Human approval bound to exact hashes/version
                              |
                Deterministic publishing executor
      idempotency, provider receipts, reconciliation, takedown
                              |
           Event warehouse, experiments, attribution, cost
                              |
              Eval-gated learning and version promotion
~~~

### 19.2 Campaign graph

The durable graph should be:

~~~text
Objective
  -> Audience
  -> Proposition
  -> Evidence and claim set
  -> Strategy hypothesis
  -> Channel plan
  -> Creative brief
  -> Concept and variant
  -> Asset rendition
  -> Policy decision
  -> Approval receipt
  -> Publish attempt
  -> Exposure and outcome
  -> Learning proposal
~~~

No stage should depend on an unversioned JSON blob or an implicit “latest available” prompt, model, strategy, product, evidence set, or asset.

### 19.3 Control-plane invariants

1. Every record is tenant-owned and every action is capability-checked.
2. Every artifact is immutable and content-addressed.
3. Every workflow step has typed inputs/outputs and pinned versions.
4. Every external effect has an idempotent intent, attempt, and provider receipt.
5. Every factual claim has evidence or is explicitly a hypothesis/placeholder.
6. Every asset has rights, provenance, and accessibility status.
7. Every approval binds the exact artifact, evidence set, policy, model, prompt, and channel payload.
8. Every failure is explicit: pass, repair, quarantine, exception, permanent failure, or cancellation.
9. Every autonomous action operates inside declared risk, tool, time, turn, spend, and scope budgets.
10. Every learned change is reversible and regression-tested.

### 19.4 Durable workflow requirements

- persisted DAG state
- transactional outbox and idempotent inbox
- stable workflow/step/attempt IDs
- heartbeat leases and fencing tokens
- bounded retries with jitter and retry classification
- deadlines, maximum turns/tool calls, compute and spend budgets
- pause/resume/cancel
- compensation and remote reconciliation
- immutable input/output snapshots
- durable review tasks
- step-level tracing and redaction
- DLQ and operator replay

Exit test: killing any worker at any step must neither lose the job nor duplicate an external action.

### 19.5 Evidence and claims

EvidenceSnapshot fields:

- canonical source URL or system identifier
- publisher/owner and source class
- title
- publication/effective/retrieval dates
- geography/jurisdiction
- immutable snapshot hash
- excerpt boundaries
- license/usage basis
- supersession and freshness state

Claim fields:

- normalized claim
- category and risk
- supporting and contradicting evidence
- relationship/entailment
- confidence and uncertainty
- owner/reviewer
- valid-from, expiry, locale, and jurisdiction
- every artifact location using the claim

The FTC’s advertising guidance requires claims to be truthful, non-deceptive, and evidence-based, and endorsements to reflect real experience with material relationships disclosed: https://www.ftc.gov/business-guidance/advertising-marketing

Acceptance:

- 100% of price, specification, availability, offer, and regulated claims come from an approved current source.
- Unsupported, contradicted, or expired high-risk claims are hard blockers.
- A reviewer can reconstruct why each published factual sentence was allowed.

### 19.6 Approval receipt

ApprovalReceipt must reference:

- artifact/version/content hash
- evidence-set hash
- product/price/inventory snapshot
- prompt/model/tool versions
- policy version and decision
- exact channel payload and preview
- rights/provenance/accessibility status
- reviewer identity, authority, decision, reason, and timestamp
- expiration/invalidation rules

Changing any material byte or dependency invalidates approval.

### 19.7 Publisher executor

The publisher is not an agent. It may:

- read one approved PublishIntent
- resolve one vault connection
- preflight one immutable payload
- upload/publish/reconcile according to a deterministic adapter
- record exact receipts and state transitions

It may not rewrite copy, swap media, choose an audience, change schedule/budget, or waive a failed policy.

### 19.8 Rights-aware DAM

Required:

- upload quarantine and technical validation
- content and perceptual hashes
- immutable originals and derivatives
- product/brand/campaign relationships
- source, creator, rights owner, license, territory, purpose, channel, expiry
- person/model/property releases
- crop/safe-zone and channel renditions
- duplicate detection
- accessibility text/captions/transcript
- AI generation/edit metadata and C2PA manifest
- takedown and rights-expiry propagation

### 19.9 Zero-trust services

- service identity and least-privilege credentials
- explicit inbound and outbound policy
- no trust based solely on the Docker/private network
- KMS/vault-backed secrets
- signed, versioned messages/webhooks
- tenant-aware storage and database policies
- append-only audit
- consent/preference and retention enforcement
- private auxiliary services

### 19.10 Localization

A localization is a versioned adaptation, not a translated string. Store:

- locale and market
- currency and timezone
- hemisphere/seasonality
- approved glossary and prohibited terms
- cultural constraints
- offer/price/date validity
- legal disclosures
- reviewer language/jurisdiction competence

Initial product-quality languages should match the operating market: English, French, and Mauritian Creole, each with native review and separate golden evaluations.

---

## 20. Prioritized implementation roadmap

The roadmap deliberately fixes trust before adding more creative agents, channels, or autonomous decisions.

### Phase 0 — Containment, 0–72 hours

Owner group: Security/Platform + Operations

1. Disable unattended publishing and adaptation promotion.
2. Restrict Forge, browser-worker, notification service, n8n webhook/admin, storage, queues, databases, and observability endpoints to private access.
3. Run one scheduler instance only.
4. Remove audit hard-delete capability.
5. Disable readable credential responses and n8n credential payloads.
6. Snapshot current schema and database revision state.
7. Inventory and rotate exposed/long-lived application and platform credentials after migration planning.
8. Patch or temporarily isolate the critical frontend dependency path.
9. Label Learning, auto-approval, report confidence, preview metrics, and unsupported channels as experimental/incomplete.
10. Create an incident runbook and global publish kill switch.
11. Restrict and classify frontend.log, BC-COLUMNS.txt, FABRIC-TABLES.txt, and environment-specific setup/probe documents; replace raw samples with synthetic fixtures.

Exit gate:

- No anonymous auxiliary-service action.
- No automatic public post or adaptation.
- No credential appears in a new job/execution/browser response.
- Operators can stop every queued/running publish path.

### Phase 1 — P0 trust foundation, weeks 1–4

Owner group: Platform/Security + Workflow + Data

1. Organization/workspace/membership/capability model and scoped repositories.
2. Tenant-aware database keys/constraints and a generated cross-tenant negative-test matrix.
3. Vault-backed ChannelConnection model and write-only OAuth connection APIs.
4. PublishIntent/PublishAttempt/provider-receipt state machine.
5. Transactional outbox/inbox and idempotent message envelope.
6. HMAC/timestamp/event-ID/attempt-bound webhook verification.
7. Durable LangGraph checkpoint and authenticated review/resume.
8. Immutable ContentVersion/MediaAsset/ApprovalReceipt binding.
9. Brand/channel/global kill switches and fenced worker leases.
10. Complete Alembic baseline and empty-to-head/upgrade/restore CI.
11. Central URL/media egress and upload policy.
12. Append-only audit.
13. Dependency patching, locked Python environments, fail-closed configuration.

Exit gate:

- Zero cross-tenant access in the test matrix.
- Zero credential leakage in API/message/log/trace/n8n checks.
- Zero duplicate publish in concurrency/crash/replay tests.
- Human pause survives restart and resumes the same run once.
- Clean database can migrate to head and restore.

### Phase 2 — Canonical workflow and reliable control plane, weeks 5–8

Owner group: Workflow + Backend + Frontend

1. One lifecycle/state-machine package and generated transition tests for all layers.
2. Versioned Research, Strategy, Plan, Content, Media, and Adaptation artifacts.
3. Campaign as the main workspace and required scope for new production work.
4. Async command/job API with progress stream and central query cache.
5. DLQ, replay, cancel, pause, retry, reconcile, and incident UI.
6. Server-side batch jobs for catalog, content, document, and media operations.
7. Truthful empty/partial/stale/error UI contracts.
8. Frontend unit/component/E2E/axe harness and zero lint errors.
9. Service readiness checks and a working trace/log/metric backend.
10. Provider/model changes through draft/eval/canary/activate/rollback.

Exit gate:

- Every lifecycle state renders and transitions consistently.
- All critical user journeys pass at desktop/mobile with keyboard and axe.
- Worker death/redelivery produces no lost work.
- Every run is reconstructible from immutable inputs and decisions.

### Phase 3 — Professional content system, months 2–4

Owner group: Product/Editorial + ML Quality + Design

1. EvidenceSource/EvidenceSnapshot/Claim graph and citation UX.
2. Product grounding from systems of record, with current price/inventory/specification.
3. Rights-aware DAM with immutable renditions and takedown/expiry propagation.
4. CreativeBriefVersion, per-channel requirements, and channel-native editors.
5. Deterministic claim, copy, platform, visual, product/logo, audio/video, rights, and accessibility validators.
6. Claims/Compliance, Editorial QA, and Visual QA review lanes.
7. Professional report export, source appendix, version diff, and methodology.
8. Golden datasets for all channels/formats and known failure cases.
9. English/French/Mauritian Creole localization pipeline.
10. C2PA/IPTC-compatible generated-media provenance.
11. Versioned provider adapters with processing and reconciliation.

Exit gate:

- At least 95% gold-set end-to-end pass rate with zero safety/claim regressions.
- At least 80% first-pass human approval, segmented by channel/format/locale.
- 100% of publishable assets have rights, provenance, and accessibility status.
- 100% of externally verifiable claims link to evidence; price/spec/regulated claims are exact.

### Phase 4 — Measurement and controlled learning, months 4–8

Owner group: Data/Analytics + Experimentation + Product

1. Immutable cross-channel event and metric-snapshot warehouse.
2. Consent-aware first-party conversions and governed campaign identifiers.
3. Clear observed/derived/attributed/incremental/inferred metric layers.
4. Experiment registry, sticky assignment, exposure logging, and analysis.
5. Cost/tokens/model/tool/provider metrics linked to campaign outcomes.
6. Typed AdaptationProposal/Execution/Evaluation/Rollback.
7. Regression/trace grading and model-judge calibration against blind human labels.
8. Shadow/canary prompt/model/policy promotion.
9. Outcome and causal-lift dashboards.
10. Campaign closeout and reusable learning curation.

Exit gate:

- Every campaign has a primary outcome, baseline, target, window, guardrails, and cost budget.
- Every promoted learning passes regression and a declared canary.
- No strategy/prompt changes are driven solely by raw engagement.
- Adaptation effects are measured and reversible.

### Phase 5 — Bounded autonomy and scale, months 8–12+

Owner group: Product Governance + Platform + Data Science

1. Automatic scheduling only for low-risk, proven templates.
2. Bounded time/channel/variant optimization inside approved limits.
3. Dual approval for spend, sensitive claims, new audiences, crisis content, and high-risk domains.
4. Portfolio allocation based on incremental value with explicit brand-risk constraints.
5. Multi-region/HA design where business requirements justify it.
6. Enterprise access: SCIM/group mapping, temporary access, delegated approval limits.
7. Privacy/retention/erasure automation across prompts, evidence, audiences, telemetry, exports, and provider copies.
8. Continuous red-team, chaos, content-quality, and disaster-recovery exercises.

Exit gate:

- Every autonomous change is bounded, reversible, policy-compliant, causally evaluated, and traceable to immutable versions.

---

## 21. Prioritized engineering backlog

Effort: S = days, M = 1–2 weeks, L = 3–6 weeks, XL = multi-team/quarter. Effort is directional and assumes focused owners.

| ID | Priority | Work item | Primary owner | Effort | Acceptance |
|---|---|---|---|---|---|
| R-001 | P0 | Freeze autonomous publish/adaptation | Operations | S | No unattended external write |
| R-002 | P0 | Private auxiliary-service networking | SRE/Security | M | Only authenticated workload paths reach services |
| R-003 | P0 | Rotate and vault channel credentials | Security/Backend | L | No secret in DB/API/job/log/execution |
| R-004 | P0 | Tenant/workspace membership model | Backend/Security | XL | Cross-tenant matrix passes |
| R-005 | P0 | Tenant-scoped storage/media | Backend/Security | L | Arbitrary/cross-tenant keys denied |
| R-006 | P0 | PublishAttempt and atomic claim | Backend | L | Concurrency yields one remote identity |
| R-007 | P0 | Transactional outbox/inbox | Backend/Workflow | L | Crash/redelivery loses no stage |
| R-008 | P0 | Replay-safe webhook verification | Backend/Security | M | Tamper/replay/regression tests pass |
| R-009 | P0 | Durable HITL pause/resume | Workflow | L | Restart/approve/reject/idempotency tests pass |
| R-010 | P0 | Disable/fix adaptation loop | Workflow/Data | L | Real typed change plus measurement |
| R-011 | P0 | Immutable content/assets/approval | Data/Backend | XL | Any material edit invalidates approval |
| R-012 | P0 | Hierarchical kill switches | Backend/Workflow | M | Queued/running/retry paths stop |
| R-013 | P0 | Append-only audit | Security/Data | L | Sensitive actions 100% recorded; no ordinary delete |
| R-014 | P0 | Complete Alembic baseline | Data/Backend | L | Empty/current/restore migration tests pass |
| R-015 | P0 | Central SSRF/egress policy | Security/Platform | L | Full bypass corpus denied |
| R-016 | P0 | Safe upload/media pipeline | Backend/Security | L | Malicious/oversized/active files quarantined |
| R-017 | P0 | Patch frontend production dependencies | Frontend/Security | M | No unexcepted critical/high |
| R-018 | P0 | Fail-closed environment validation | Platform | S | Invalid config exits nonzero |
| R-018A | P0 | Remove/govern sensitive workspace diagnostics | Security/Data Governance | M | No unapproved PII/auth code/infrastructure identity in tracked or ignored workspace files |
| R-019 | P1 | Canonical lifecycle definition | Architecture | L | Backend/agent/UI transition parity |
| R-020 | P1 | Versioned message envelope | Workflow | M | Schema, ID, tenant, causation, signature enforced |
| R-021 | P1 | DLQ and replay tooling | Workflow/Ops | M | Poison and transient failures recoverable |
| R-022 | P1 | Worker leases/fencing | Workflow | M | Shutdown/reaper affect owned work only |
| R-023 | P1 | Campaign first-class aggregate | Product/Backend | XL | New content pins brief/objective/campaign |
| R-024 | P1 | Evidence and claim graph | Product/Data | XL | Every factual sentence traceable |
| R-025 | P1 | Product DTO/source reconciliation | Data/Workflow | L | No truncation/mismatch; provenance persists |
| R-026 | P1 | StrategyVersion and approval | Workflow/Product | L | Planning pins approved objective/KPI version |
| R-027 | P1 | Staged atomic PlanVersion | Workflow/Data | L | Partial generation never replaces good plan |
| R-028 | P1 | Per-channel deliverable contracts | Product/Workflow | L | Missing mandatory artifact quarantines |
| R-029 | P1 | Final still-image validator | ML Quality | L | Known QA blockers caught |
| R-030 | P1 | Final video/audio validator | ML Quality | L | Text/CTA/audio/duration/codec gates block |
| R-031 | P1 | Rights-aware DAM | Product/Backend | XL | No publish without valid rights |
| R-032 | P1 | Channel adapter registry | Integrations | L | UI capability equals contract-tested support |
| R-033 | P1 | Instagram media readiness polling | Integrations | M | Publish waits for finished state |
| R-034 | P1 | Native Facebook photo path | Integrations | M | Verified native image result |
| R-035 | P1 | LinkedIn image upload/URN path | Integrations | M | Image post retains approved media |
| R-036 | P1 | Provider remote reconciliation | Integrations | L | Ambiguous timeout resolved before retry |
| R-037 | P1 | Professional approval workspace | Frontend/Product | XL | Evidence/rights/diff/authority/mobile included |
| R-038 | P1 | Server batch-job framework | Backend/Frontend | L | Partial results visible and retryable |
| R-039 | P1 | Typed frontend query/command layer | Frontend | L | Timeouts, schemas, correlation, idempotency |
| R-040 | P1 | Frontend test and accessibility harness | Frontend/QA | L | Critical journeys/axe/keyboard gated |
| R-041 | P1 | Truthful error/partial/stale UI | Frontend | M | No failure rendered as zero/not-found/healthy |
| R-042 | P1 | Provider/model governance | ML Platform | L | Eval/canary/approve/rollback required |
| R-043 | P1 | Real OTel trace backend and propagation | SRE | L | End-to-end correlated trace available |
| R-044 | P1 | Alertmanager/on-call routing | SRE | M | Synthetic incident reaches owner |
| R-045 | P1 | Complete encrypted offsite backup | SRE/Security | L | All authoritative stores included |
| R-046 | P1 | Automated clean restore drill | SRE/Data | L | RPO/RTO evidence produced |
| R-047 | P1 | CI security/supply-chain gates | DevEx/Security | L | SCA/SBOM/secrets/container/license block |
| R-048 | P1 | Integration and chaos environment | QA/Platform | XL | Crash/redelivery/partial-failure suite passes |
| R-049 | P1 | Documentation consolidation/generation | Architecture/DevEx | L | Current topology/state/capability generated |
| R-050 | P2 | Report citations/version/export | Frontend/Product | L | Decision-grade PDF/source appendix |
| R-051 | P2 | Platform-native editors/previews | Product/Frontend | XL | Exact constraints and accessible simulation |
| R-052 | P2 | English/French/Creole localization | Product/Editorial | XL | Native-reviewed golden sets pass |
| R-053 | P2 | C2PA/IPTC provenance | DAM/ML Platform | L | Generated/edited assets carry metadata |
| R-054 | P2 | Immutable event/metric warehouse | Data | XL | No double counts; dated snapshots |
| R-055 | P2 | Conversion and cost attribution | Data/Product | XL | Campaign-to-outcome/cost trace |
| R-056 | P2 | Experiment registry/assignment | Data Science | XL | Predeclared sticky experiments |
| R-057 | P2 | Evaluation datasets/trace grading | ML Quality | XL | Same suite gates every change |
| R-058 | P2 | Calibrate model graders | ML Quality/Editorial | L | Agreement monitored against blind humans |
| R-059 | P2 | Typed reversible adaptation executor | Workflow/Data | XL | Canary, measurement, rollback |
| R-060 | P2 | Consent/preferences/retention ledger | Privacy/Backend | XL | Withdrawal/erasure propagation tested |

### 21.1 Critical-path dependencies

~~~text
Tenant + vault + audit
        |
        +--> immutable artifacts + approval
        |            |
Outbox + lifecycle   +--> publish attempt + reconciliation
        |                         |
        +--> durable HITL         +--> safe channel expansion
        |
Evidence + product grounding
        |
Quality gates + DAM rights
        |
Professional production
        |
Event warehouse + experiments
        |
Measured reversible adaptation
        |
Bounded autonomy
~~~

Adding channels or more generative agents before the first four rows are stable will multiply risk and rework.

---

## 22. Proposed north-star metrics and release targets

These are recommended targets, not claims about current industry averages.

### Trust and safety

| Metric | Target |
|---|---:|
| Cross-tenant disclosure or mutation | 0 |
| Duplicate public publish | 0 |
| External action with valid artifact-bound approval | 100% |
| High-risk claim with approved evidence and qualified human review | 100% |
| Price/specification/offer claim from current system of record | 100% |
| Sensitive audit-event completeness | 100% |
| Secret present in application data/job/log/trace | 0 |

### Content quality

| Metric | Target |
|---|---:|
| Gold-set end-to-end quality pass | at least 95% |
| Safety/unsupported-claim regression | 0 |
| First-pass human approval | at least 80%, segmented |
| Median human edit time for standard post | under 10 minutes |
| Product/logo fidelity blockers reaching review | 0 |
| Meaningful images with approved alt text | 100% |
| Videos with captions and transcript | 100% |
| Publishable assets with valid rights/provenance | 100% |

### Reliability and operations

| Metric | Target |
|---|---:|
| Publish attempts remotely reconciled | 100% |
| Publish success excluding provider-declared outage | at least 99.5% |
| Crash/redelivery recovery without lost workflow | 100% in chaos suite |
| Workflow steps within declared hard budget | 100% |
| Unexplained provider/model cost | below 0.5% |
| Critical SLO alert delivered to owner | 100% in synthetic tests |
| Restore drill meets declared RPO/RTO | 100% |

### Business value

| Metric | Target |
|---|---:|
| Campaigns with primary outcome/baseline/target/window | 100% |
| Brief-to-first-reviewable campaign system | P50 under 30 minutes |
| Cost per approved and published asset | Trended down without quality regression |
| Human edit distance | Trended down by content type/locale |
| Controlled-experiment-backed eligible optimization | at least 70% after measurement maturity |
| Attributed conversion/revenue coverage | Explicit and increasing; never implied when absent |
| Incremental value/iROAS | Report only where causal design supports it |

### Accessibility

| Metric | Target |
|---|---:|
| WCAG 2.2 AA critical-journey conformance | 100% |
| Keyboard completion of every critical journey | 100% |
| Charts with accessible data alternative | 100% |
| Critical mobile viewport visual regressions | 0 |

---

## 23. Definition of “world-class professional content”

A MarkAI artifact is world-class only when it is:

- Correct — factual, product-accurate, current, and cited
- Distinctive — recognizably from the brand, not generic AI stock
- Strategic — tied to a campaign objective, audience, proposition, and funnel stage
- Native — adapted to the channel/placement rather than copied across platforms
- Crafted — strong hook, hierarchy, composition, pacing, CTA, and editing
- Accessible — alt text, captions, transcript, contrast, reading order, safe typography
- Compliant — claims, endorsements, disclosures, rights, consent, and jurisdiction rules pass
- Reproducible — model, prompt, tools, evidence, versions, inputs, and transformations are recorded
- Reviewable — a qualified person can verify the exact artifact and why it is allowed
- Measurable — connected to declared exposure, outcome, cost, and experiment semantics
- Reversible — can be taken down, rolled back, or superseded without destroying history

Model confidence alone cannot establish any of these properties.

---

## 24. Governance and ownership

Recommended accountable owners:

| Domain | Accountable owner |
|---|---|
| Tenant/security/secrets | Security & Platform lead |
| Workflow/state/idempotency | Workflow Platform lead |
| Data/schema/provenance | Data Architecture lead |
| Campaign/editorial product | Product lead |
| Claims/compliance/rights | Content Governance lead |
| Creative quality/evals | ML Quality + Creative Director |
| Channel publishing | Integrations lead |
| UI/accessibility | Frontend/Design lead |
| Analytics/experiments | Data Science lead |
| SLO/incident/recovery | SRE lead |
| Documentation/release evidence | Architecture/DevEx lead |

Weekly trust review until the P0 gate closes:

- P0 burn-down and blocker decisions
- cross-tenant/security test results
- publish-attempt and workflow chaos evidence
- content golden-set failures
- secret/dependency scan
- migration/restore status
- incidents and near misses
- quality, edit-distance, and approval metrics

No roadmap item should be marked complete without its acceptance evidence.

---

## 25. Final recommendation

Do not discard the existing application. The architecture, UX skeleton, media pipeline, and test investment justify an incremental hardening program.

Do not spend the next quarter primarily adding channels, models, or agent personas. That would scale the current trust defects.

The highest-leverage move is to build the campaign/evidence/artifact/approval/publish spine, then force every existing workflow through it. Once that spine, the quality gates, and the measurement layer are reliable, MarkAI can safely exploit its strongest differentiator: a deep, specialized creative pipeline that learns within explicit boundaries.

The product should market itself honestly during this transition:

- “AI-assisted marketing production with human approval” now
- “Measured, policy-bounded automation” after Phase 4
- “Autonomous optimization within approved constraints” only after the Phase 5 exit gate

---

## Appendix A — Exact every-file coverage ledger

Legend:

- R: fully read and semantically reviewed
- R-structure: generated metadata or structured lock/build file read/parsed and assessed
- R-media: binary inspected through metadata and visual/audio sampling
- R-secret-safe: key names/configuration state inspected without reproducing secret values

Generated vendor/build/cache trees are separately inventoried in Section 2 and are not repository-authored source.

### A.1 Root and GitHub — 19/19

- [R] .editorconfig
- [R-secret-safe] .env
- [R] .env.example
- [R] .env.vps.example
- [R] .gitattributes
- [R] .gitignore
- [R] azure-pipelines.yml
- [R] docker-compose.override.yml
- [R] docker-compose.vps.yml
- [R] docker-compose.yml
- [R] frontend.log
- [R] README.md
- [R] SEQUENCE_MAP.html
- [R] VPS_CONNECTION_GUIDE.md
- [R] VPS_DEPLOYMENT_GUIDE.md
- [R] VPS_SSH_FIX_FOR_OTHER_AGENT.md
- [R] VPS_SSH_TROUBLESHOOT.md
- [R] .github/workflows/ci.yml
- [R] .github/workflows/deploy.yml

### A.2 Agents — 137/137

Root:

- [R] agents/-
- [R] agents/.dockerignore
- [R] agents/Dockerfile
- [R] agents/pyproject.toml
- [R] agents/worker.py
- [R] agents/__init__.py

Music assets:

- [R] agents/assets/music/README.md
- [R] agents/assets/music/bold/.gitkeep
- [R-media] agents/assets/music/bold/bold_1.m4a
- [R-media] agents/assets/music/bold/bold_2.m4a
- [R-media] agents/assets/music/bold/bold_3.m4a
- [R] agents/assets/music/calm/.gitkeep
- [R-media] agents/assets/music/calm/calm_1.m4a
- [R-media] agents/assets/music/calm/calm_2.m4a
- [R-media] agents/assets/music/calm/calm_3.m4a
- [R] agents/assets/music/elegant/.gitkeep
- [R-media] agents/assets/music/elegant/elegant_1.m4a
- [R-media] agents/assets/music/elegant/elegant_2.m4a
- [R-media] agents/assets/music/elegant/elegant_3.m4a
- [R] agents/assets/music/upbeat/.gitkeep
- [R-media] agents/assets/music/upbeat/upbeat_1.m4a
- [R-media] agents/assets/music/upbeat/upbeat_2.m4a
- [R-media] agents/assets/music/upbeat/upbeat_3.m4a
- [R] agents/assets/music/warm/.gitkeep
- [R-media] agents/assets/music/warm/warm_1.m4a
- [R-media] agents/assets/music/warm/warm_2.m4a
- [R-media] agents/assets/music/warm/warm_3.m4a

Shared modules:

- [R] agents/shared/brand_context.py
- [R] agents/shared/color_names.py
- [R] agents/shared/config.py
- [R] agents/shared/editorial.py
- [R] agents/shared/image_processing.py
- [R] agents/shared/image_subject.py
- [R] agents/shared/image_text_guard.py
- [R] agents/shared/language_guard.py
- [R] agents/shared/llm.py
- [R] agents/shared/nats_consumer.py
- [R] agents/shared/placement.py
- [R] agents/shared/product_swap.py
- [R] agents/shared/prompt_enhancer.py
- [R] agents/shared/sanitize.py
- [R] agents/shared/state.py
- [R] agents/shared/suppliers.py
- [R] agents/shared/url_validator.py
- [R] agents/shared/video.py
- [R] agents/shared/vision_payload.py
- [R] agents/shared/visual_brief.py
- [R] agents/shared/__init__.py

Shared tools:

- [R] agents/shared/tools/bc_api.py
- [R] agents/shared/tools/bc_images.py
- [R] agents/shared/tools/browser.py
- [R] agents/shared/tools/database.py
- [R] agents/shared/tools/fabric.py
- [R] agents/shared/tools/image_search.py
- [R] agents/shared/tools/social.py
- [R] agents/shared/tools/storage.py
- [R] agents/shared/tools/vector.py
- [R] agents/shared/tools/web_search.py
- [R] agents/shared/tools/__init__.py

Agent tests:

- [R] agents/tests/conftest.py
- [R] agents/tests/test_anchor_frames.py
- [R] agents/tests/test_audio_assembly.py
- [R] agents/tests/test_bc_api.py
- [R] agents/tests/test_bc_first_sourcing.py
- [R] agents/tests/test_color_names.py
- [R] agents/tests/test_copy_visual_contract.py
- [R] agents/tests/test_editorial_guards.py
- [R] agents/tests/test_end_card.py
- [R] agents/tests/test_english_rule.py
- [R] agents/tests/test_image_prompt_hygiene.py
- [R] agents/tests/test_image_subject.py
- [R] agents/tests/test_image_text_guard.py
- [R] agents/tests/test_language_guard.py
- [R] agents/tests/test_llm_parsing.py
- [R] agents/tests/test_local_image_forge.py
- [R] agents/tests/test_logo_placement.py
- [R] agents/tests/test_overlay_budget.py
- [R] agents/tests/test_overlay_copy.py
- [R] agents/tests/test_overlay_design.py
- [R] agents/tests/test_picture_grade.py
- [R] agents/tests/test_planning_campaigns.py
- [R] agents/tests/test_planning_products.py
- [R] agents/tests/test_plan_language.py
- [R] agents/tests/test_product_region.py
- [R] agents/tests/test_product_swap.py
- [R] agents/tests/test_product_swap_guard.py
- [R] agents/tests/test_reel_audio.py
- [R] agents/tests/test_render_quality.py
- [R] agents/tests/test_run_lock_errors.py
- [R] agents/tests/test_sanitize.py
- [R] agents/tests/test_storage_paths.py
- [R] agents/tests/test_suppliers.py
- [R] agents/tests/test_swap_reference_discipline.py
- [R] agents/tests/test_video_multishot.py
- [R] agents/tests/test_video_native_multishot.py
- [R] agents/tests/test_video_overlay.py
- [R] agents/tests/test_video_providers.py
- [R] agents/tests/test_video_workflow.py
- [R] agents/tests/test_vision_payload.py
- [R] agents/tests/test_worker_dispatch.py
- [R] agents/tests/test_worker_shutdown.py
- [R] agents/tests/test_worker_video_guard.py
- [R] agents/tests/__init__.py

Workflow packages:

- [R] agents/workflows/__init__.py
- [R] agents/workflows/adaptation/graph.py
- [R] agents/workflows/adaptation/nodes.py
- [R] agents/workflows/adaptation/state.py
- [R] agents/workflows/adaptation/__init__.py
- [R] agents/workflows/content/graph.py
- [R] agents/workflows/content/image_sourcing.py
- [R] agents/workflows/content/nodes.py
- [R] agents/workflows/content/state.py
- [R] agents/workflows/content/__init__.py
- [R] agents/workflows/evaluation/graph.py
- [R] agents/workflows/evaluation/nodes.py
- [R] agents/workflows/evaluation/state.py
- [R] agents/workflows/evaluation/__init__.py
- [R] agents/workflows/planning/graph.py
- [R] agents/workflows/planning/nodes.py
- [R] agents/workflows/planning/state.py
- [R] agents/workflows/planning/__init__.py
- [R] agents/workflows/product_intel/graph.py
- [R] agents/workflows/product_intel/nodes.py
- [R] agents/workflows/product_intel/state.py
- [R] agents/workflows/product_intel/__init__.py
- [R] agents/workflows/research/discover_competitors.py
- [R] agents/workflows/research/graph.py
- [R] agents/workflows/research/nodes.py
- [R] agents/workflows/research/state.py
- [R] agents/workflows/research/__init__.py
- [R] agents/workflows/strategy/graph.py
- [R] agents/workflows/strategy/nodes.py
- [R] agents/workflows/strategy/state.py
- [R] agents/workflows/strategy/__init__.py
- [R] agents/workflows/video/graph.py
- [R] agents/workflows/video/nodes.py
- [R] agents/workflows/video/__init__.py

### A.3 Existing audit artifacts — 5/5

- [R] AUDIT_ARTIFACTS/bc_image_coverage.md
- [R] AUDIT_ARTIFACTS/final_reaudit.md
- [R] AUDIT_ARTIFACTS/image_qa_fancyfinds.md
- [R] AUDIT_ARTIFACTS/image_qa_healthspan.md
- [R] AUDIT_ARTIFACTS/image_qa_naturespan.md

### A.4 Backend — 134/134

Root and migrations:

- [R] backend/.dockerignore
- [R] backend/alembic.ini
- [R] backend/docker-entrypoint.sh
- [R] backend/Dockerfile
- [R] backend/pyproject.toml
- [R] backend/alembic/env.py
- [R] backend/alembic/versions/.gitkeep
- [R] backend/alembic/versions/0001_baseline.py
- [R] backend/alembic/versions/0002_video_foundation.py
- [R] backend/alembic/versions/0003_event_annual_repair.py
- [R] backend/alembic/versions/0004_brand_model_profiles.py

Application root:

- [R] backend/app/config.py
- [R] backend/app/deps.py
- [R] backend/app/main.py
- [R] backend/app/__init__.py
- [R] backend/app/api/router.py
- [R] backend/app/api/__init__.py

API v1:

- [R] backend/app/api/v1/agents.py
- [R] backend/app/api/v1/analytics.py
- [R] backend/app/api/v1/approvals.py
- [R] backend/app/api/v1/brands.py
- [R] backend/app/api/v1/calendar.py
- [R] backend/app/api/v1/campaigns.py
- [R] backend/app/api/v1/content.py
- [R] backend/app/api/v1/dashboard.py
- [R] backend/app/api/v1/events.py
- [R] backend/app/api/v1/files.py
- [R] backend/app/api/v1/intelligence.py
- [R] backend/app/api/v1/learning.py
- [R] backend/app/api/v1/notifications.py
- [R] backend/app/api/v1/products.py
- [R] backend/app/api/v1/prompts.py
- [R] backend/app/api/v1/providers.py
- [R] backend/app/api/v1/settings.py
- [R] backend/app/api/v1/system.py
- [R] backend/app/api/v1/users.py
- [R] backend/app/api/v1/webhooks.py
- [R] backend/app/api/v1/__init__.py

Authentication:

- [R] backend/app/auth/entra.py
- [R] backend/app/auth/models.py
- [R] backend/app/auth/permissions.py
- [R] backend/app/auth/__init__.py

Models:

- [R] backend/app/models/adaptation.py
- [R] backend/app/models/agent_run.py
- [R] backend/app/models/ai_model.py
- [R] backend/app/models/approval.py
- [R] backend/app/models/base.py
- [R] backend/app/models/brand.py
- [R] backend/app/models/calendar_item.py
- [R] backend/app/models/campaign.py
- [R] backend/app/models/channel_model_fallback.py
- [R] backend/app/models/competitor.py
- [R] backend/app/models/content.py
- [R] backend/app/models/engagement.py
- [R] backend/app/models/event.py
- [R] backend/app/models/media_asset.py
- [R] backend/app/models/product.py
- [R] backend/app/models/prompt_version.py
- [R] backend/app/models/trending_topic.py
- [R] backend/app/models/video_job.py
- [R] backend/app/models/__init__.py

Schedulers:

- [R] backend/app/scheduler/bc_sync.py
- [R] backend/app/scheduler/engagement_puller.py
- [R] backend/app/scheduler/linkedin_token_alert.py
- [R] backend/app/scheduler/model_discovery.py
- [R] backend/app/scheduler/morning_jobs.py
- [R] backend/app/scheduler/publish_checker.py
- [R] backend/app/scheduler/stale_run_reaper.py
- [R] backend/app/scheduler/__init__.py

Schemas:

- [R] backend/app/schemas/adaptation.py
- [R] backend/app/schemas/agent_run.py
- [R] backend/app/schemas/ai_model.py
- [R] backend/app/schemas/approval.py
- [R] backend/app/schemas/brand.py
- [R] backend/app/schemas/calendar_item.py
- [R] backend/app/schemas/campaign.py
- [R] backend/app/schemas/competitor.py
- [R] backend/app/schemas/content.py
- [R] backend/app/schemas/engagement.py
- [R] backend/app/schemas/event.py
- [R] backend/app/schemas/product.py
- [R] backend/app/schemas/prompt_version.py
- [R] backend/app/schemas/user.py
- [R] backend/app/schemas/__init__.py

Services:

- [R] backend/app/services/ai_model_service.py
- [R] backend/app/services/analytics_service.py
- [R] backend/app/services/approval_service.py
- [R] backend/app/services/audit_service.py
- [R] backend/app/services/bc_api.py
- [R] backend/app/services/bc_image_service.py
- [R] backend/app/services/brand_service.py
- [R] backend/app/services/calendar_service.py
- [R] backend/app/services/content_service.py
- [R] backend/app/services/engagement_service.py
- [R] backend/app/services/event_service.py
- [R] backend/app/services/fabric_service.py
- [R] backend/app/services/gemini_service.py
- [R] backend/app/services/minio_service.py
- [R] backend/app/services/nats_service.py
- [R] backend/app/services/notification_service.py
- [R] backend/app/services/product_service.py
- [R] backend/app/services/prompt_service.py
- [R] backend/app/services/publish_service.py
- [R] backend/app/services/qdrant_service.py
- [R] backend/app/services/trends_service.py
- [R] backend/app/services/__init__.py

Publisher services:

- [R] backend/app/services/publishers/base.py
- [R] backend/app/services/publishers/linkedin.py
- [R] backend/app/services/publishers/meta.py
- [R] backend/app/services/publishers/registry.py
- [R] backend/app/services/publishers/youtube.py
- [R] backend/app/services/publishers/__init__.py

Utilities:

- [R] backend/app/utils/sanitize.py
- [R] backend/app/utils/url_validator.py
- [R] backend/app/utils/__init__.py

Backend tests:

- [R] backend/tests/conftest.py
- [R] backend/tests/test_api_health.py
- [R] backend/tests/test_approval_state_machine.py
- [R] backend/tests/test_auth_permissions.py
- [R] backend/tests/test_bc_images.py
- [R] backend/tests/test_content_versioning.py
- [R] backend/tests/test_event_service.py
- [R] backend/tests/test_file_proxy.py
- [R] backend/tests/test_model_discovery.py
- [R] backend/tests/test_morning_topup.py
- [R] backend/tests/test_product_service.py
- [R] backend/tests/test_publishers_meta.py
- [R] backend/tests/test_publishers_yt_li.py
- [R] backend/tests/test_publish_dispatch.py
- [R] backend/tests/test_regenerate_image_gate.py
- [R] backend/tests/test_route_auth_sweep.py
- [R] backend/tests/test_stale_run_reaper.py
- [R] backend/tests/test_utils.py
- [R] backend/tests/__init__.py

### A.5 Database scripts — 2/2

- [R] db/init.sql
- [R] db/migrations/2026-08-20_analytics_and_adaptations.sql

### A.6 Frontend — 112/112

Root/configuration:

- [R] frontend/.dockerignore
- [R] frontend/Dockerfile
- [R] frontend/eslint.config.mjs
- [R-structure] frontend/next-env.d.ts
- [R] frontend/next.config.ts
- [R-structure] frontend/package-lock.json
- [R] frontend/package.json
- [R] frontend/postcss.config.mjs
- [R] frontend/tsconfig.json
- [R-structure] frontend/tsconfig.tsbuildinfo

Routes, pages, styles, and assets:

- [R] frontend/src/app/analytics/page.tsx
- [R] frontend/src/app/api/auth/[...nextauth]/route.ts
- [R] frontend/src/app/approvals/page.tsx
- [R] frontend/src/app/auth/signin/page.tsx
- [R] frontend/src/app/brands/[id]/page.tsx
- [R] frontend/src/app/brands/new/page.tsx
- [R] frontend/src/app/brands/page.tsx
- [R] frontend/src/app/content/[id]/page.tsx
- [R] frontend/src/app/content/calendar/page.tsx
- [R] frontend/src/app/content/page.tsx
- [R] frontend/src/app/content/stage/[status]/page.tsx
- [R] frontend/src/app/error.tsx
- [R] frontend/src/app/events/page.tsx
- [R] frontend/src/app/globals.css
- [R-media] frontend/src/app/icon.svg
- [R] frontend/src/app/intelligence/page.tsx
- [R] frontend/src/app/intelligence/products/page.tsx
- [R] frontend/src/app/intelligence/report/[id]/page.tsx
- [R] frontend/src/app/layout.tsx
- [R] frontend/src/app/learning/page.tsx
- [R] frontend/src/app/not-found.tsx
- [R] frontend/src/app/page.tsx
- [R] frontend/src/app/prompts/page.tsx
- [R] frontend/src/app/providers-wrapper.tsx
- [R] frontend/src/app/providers/page.tsx
- [R] frontend/src/app/settings/page.tsx
- [R] frontend/src/app/settings/users/page.tsx
- [R] frontend/src/app/system/audit/page.tsx
- [R] frontend/src/app/system/page.tsx

Components:

- [R] frontend/src/components/analytics/EngagementChart.tsx
- [R] frontend/src/components/analytics/EngagementChartInner.tsx
- [R] frontend/src/components/analytics/PerformanceGrid.tsx
- [R] frontend/src/components/analytics/PostingHeatmap.tsx
- [R] frontend/src/components/approval/ApprovalActions.tsx
- [R] frontend/src/components/approval/ApprovalHistory.tsx
- [R] frontend/src/components/brand/BrandCard.tsx
- [R] frontend/src/components/brand/BrandForm.tsx
- [R] frontend/src/components/brand/BrandOnboarding.tsx
- [R] frontend/src/components/brand/ColorPalette.tsx
- [R] frontend/src/components/brand/CompetitorTracker.tsx
- [R] frontend/src/components/brand/EditDocumentsModal.tsx
- [R] frontend/src/components/brand/WorkflowStatus.tsx
- [R] frontend/src/components/brand/tabs/ChannelsTab.tsx
- [R] frontend/src/components/brand/tabs/CompetitorsTab.tsx
- [R] frontend/src/components/brand/tabs/EditBrandTab.tsx
- [R] frontend/src/components/brand/tabs/IntelligenceTab.tsx
- [R] frontend/src/components/brand/tabs/LogosTab.tsx
- [R] frontend/src/components/brand/tabs/OverviewTab.tsx
- [R] frontend/src/components/brand/tabs/PerformanceTab.tsx
- [R] frontend/src/components/brand/tabs/ProductsTab.tsx
- [R] frontend/src/components/brand/tabs/index.ts
- [R] frontend/src/components/content/AssetPreview.tsx
- [R] frontend/src/components/content/CalendarView.tsx
- [R] frontend/src/components/content/ChannelPreview.tsx
- [R] frontend/src/components/content/ContentCard.tsx
- [R] frontend/src/components/content/ContentEditor.tsx
- [R] frontend/src/components/content/KanbanBoard.tsx
- [R] frontend/src/components/content/KanbanBoardInner.tsx
- [R] frontend/src/components/content/LogoEditor.tsx
- [R] frontend/src/components/content/PlatformMockups.tsx
- [R] frontend/src/components/content/WorkingStageTracker.tsx
- [R] frontend/src/components/events/DetectEventsDialog.tsx
- [R] frontend/src/components/events/EventDialog.tsx
- [R] frontend/src/components/intelligence/ContentCalendarStrategy.tsx
- [R] frontend/src/components/intelligence/ReportCharts.tsx
- [R] frontend/src/components/intelligence/ReportChartsInner.tsx
- [R] frontend/src/components/intelligence/ReportContentEditor.tsx
- [R] frontend/src/components/layout/BrandSwitcher.tsx
- [R] frontend/src/components/layout/Header.tsx
- [R] frontend/src/components/layout/Sidebar.tsx
- [R] frontend/src/components/system/QueueDepth.tsx
- [R] frontend/src/components/system/ServiceHealth.tsx
- [R] frontend/src/components/system/WorkflowMonitor.tsx
- [R] frontend/src/components/ui/avatar.tsx
- [R] frontend/src/components/ui/badge.tsx
- [R] frontend/src/components/ui/button.tsx
- [R] frontend/src/components/ui/card.tsx
- [R] frontend/src/components/ui/confirm-dialog.tsx
- [R] frontend/src/components/ui/dialog.tsx
- [R] frontend/src/components/ui/dropdown-menu.tsx
- [R] frontend/src/components/ui/input.tsx
- [R] frontend/src/components/ui/label.tsx
- [R] frontend/src/components/ui/safe-render.tsx
- [R] frontend/src/components/ui/select.tsx
- [R] frontend/src/components/ui/separator.tsx
- [R] frontend/src/components/ui/skeleton.tsx
- [R] frontend/src/components/ui/switch.tsx
- [R] frontend/src/components/ui/table.tsx
- [R] frontend/src/components/ui/tabs.tsx
- [R] frontend/src/components/ui/textarea.tsx

Libraries, state, and types:

- [R] frontend/src/lib/api.ts
- [R] frontend/src/lib/auth.ts
- [R] frontend/src/lib/brand-selection.ts
- [R] frontend/src/lib/constants.ts
- [R] frontend/src/lib/hooks.ts
- [R] frontend/src/lib/notification-toaster.ts
- [R] frontend/src/lib/opened-content.ts
- [R] frontend/src/lib/post-watch.ts
- [R] frontend/src/lib/utils.ts
- [R] frontend/src/stores/brand-store.ts
- [R] frontend/src/types/index.ts
- [R] frontend/src/types/next-auth.d.ts

### A.7 Browser worker — 9/9

- [R] browser-worker/.dockerignore
- [R] browser-worker/Dockerfile
- [R] browser-worker/pyproject.toml
- [R] browser-worker/app/capture.py
- [R] browser-worker/app/config.py
- [R] browser-worker/app/main.py
- [R] browser-worker/app/product_image.py
- [R] browser-worker/app/social_scraper.py
- [R] browser-worker/app/__init__.py

### A.8 Documentation and n8n workflows — 26/26

- [R] docs/AI_SERVER_PROGRAM.md
- [R] docs/CHANGELOG_ENHANCEMENTS.md
- [R] docs/CONTENT_PIPELINE_SEQUENCE.md
- [R] docs/LOCAL_IMAGE_MODELS.md
- [R] docs/MASTER_UPGRADE_SPEC.md
- [R] docs/META_SETUP_GUIDE.md
- [R] docs/TEST_GUIDE_ENHANCEMENTS.md
- [R] docs/UPGRADE_LOG.md
- [R] docs/VIDEO_LANES_RESEARCH.md
- [R] docs/VPS_DEPLOY_CACHE_FIX.md
- [R] docs/VPS_DEPLOY_SHARED_TRAEFIK.md
- [R] docs/build-files/AUDIT-FIX-LOOP-AGENT-PROMPT.md
- [R] docs/build-files/AUDIT-REPORT.md
- [R-structure] docs/build-files/BC-COLUMNS.txt
- [R] docs/build-files/DEPENDENCY-AUDIT.md
- [R-structure] docs/build-files/FABRIC-TABLES.txt
- [R] docs/build-files/MARKAI-Implementation-Plan-v2.md
- [R] docs/build-files/MARKAI-n8n-Workflows-v2.md
- [R] docs/build-files/MARKAI-Setup-Guide-v2.md
- [R] docs/build-files/SETUP-REMAINING.md
- [R] docs/build-files/SYSTEM-ARCHITECTURE.md
- [R] docs/build-files/TECHNOLOGY_RESEARCH_MARCH_2026.md
- [R] docs/build-files/universal-audit-loop-prompt.md
- [R-structure] docs/n8n-workflows/markai-publish-preview.json
- [R-structure] docs/n8n-workflows/markai-publish.json
- [R] docs/n8n-workflows/README.md

### A.9 Prompt evaluations — 4/4

- [R] eval/promptfooconfig.yaml
- [R] eval/prompts/content_generation.txt
- [R] eval/prompts/research_summary.txt
- [R] eval/tests/.gitkeep

### A.10 LiteLLM — 1/1

- [R] litellm/config.yaml

### A.11 Notifications — 8/8

- [R] notifications/.dockerignore
- [R] notifications/Dockerfile
- [R] notifications/pyproject.toml
- [R] notifications/app/config.py
- [R] notifications/app/main.py
- [R] notifications/app/portal.py
- [R] notifications/app/teams.py
- [R] notifications/app/__init__.py

### A.12 Observability — 8/8

- [R] observability/grafana/grafana.ini
- [R] observability/grafana/provisioning/dashboards/dashboards.yaml
- [R] observability/grafana/provisioning/datasources/datasources.yaml
- [R] observability/loki/loki-config.yaml
- [R] observability/otel-collector/otel-collector-config.yaml
- [R] observability/prometheus/prometheus.yml
- [R] observability/prometheus/rules/alerts.yml
- [R] observability/promtail/promtail-config.yaml

### A.13 Review assets and generator — 29/29

- [R] review/generate_posts.py
- [R-media] review/final_posts/educational_image.png
- [R] review/final_posts/educational_post.md
- [R-media] review/final_posts/ringconn_image.png
- [R] review/final_posts/ringconn_post.md
- [R-media] review/final_posts/sibionics_image.png
- [R] review/final_posts/sibionics_post.md
- [R-media] review/final_posts/mockups/educational_facebook.png
- [R-media] review/final_posts/mockups/educational_instagram.png
- [R-media] review/final_posts/mockups/educational_linkedin.png
- [R-media] review/final_posts/mockups/educational_x.png
- [R-media] review/final_posts/mockups/ringconn_facebook.png
- [R-media] review/final_posts/mockups/ringconn_instagram.png
- [R-media] review/final_posts/mockups/ringconn_linkedin.png
- [R-media] review/final_posts/mockups/ringconn_x.png
- [R-media] review/final_posts/mockups/sibionics_facebook.png
- [R-media] review/final_posts/mockups/sibionics_instagram.png
- [R-media] review/final_posts/mockups/sibionics_linkedin.png
- [R-media] review/final_posts/mockups/sibionics_x.png
- [R-media] review/product_images/ringconn_2.png
- [R-media] review/product_images/sibionics_1.jpg
- [R-structure] review/prompts/all_prompts.json
- [R-media] review/prompts/educational_step1_scene.png
- [R-media] review/prompts/healthspan_logo.svg
- [R-media] review/prompts/healthspan_logo_primary.png
- [R-media] review/prompts/ringconn_step1_scene.png
- [R-media] review/prompts/ringconn_step2_replaced.png
- [R-media] review/prompts/sibionics_step1_scene.png
- [R-media] review/prompts/sibionics_step2_replaced.png

### A.14 Sample reports — 4/4

- [R] sample-reports/calendar_strategy_report.html
- [R] sample-reports/planning_report.html
- [R] sample-reports/research_report.html
- [R] sample-reports/strategy_report.html

### A.15 Sample videos — 10/10

- [R-media] samples/naturespan_olive_oil_reel.mp4
- [R-media] samples/naturespan_olive_oil_reel_v10_pipeline.mp4
- [R-media] samples/naturespan_olive_oil_reel_v2.mp4
- [R-media] samples/naturespan_olive_oil_reel_v3.mp4
- [R-media] samples/naturespan_olive_oil_reel_v4_native.mp4
- [R-media] samples/naturespan_olive_oil_reel_v5_native.mp4
- [R-media] samples/naturespan_olive_oil_reel_v6_native.mp4
- [R-media] samples/naturespan_olive_oil_reel_v7_myscript.mp4
- [R-media] samples/naturespan_olive_oil_reel_v8_pipeline.mp4
- [R-media] samples/naturespan_olive_oil_sora2pro_benchmark_20s.mp4

### A.16 Scripts — 6/6

- [R] scripts/bc-image-coverage.py
- [R] scripts/bc-table-discovery.py
- [R] scripts/column-discovery.py
- [R] scripts/nightly-backup.sh
- [R] scripts/seed-dev.py
- [R] scripts/vps-redeploy.sh

### A.17 Traefik — 2/2

- [R] traefik/traefik.yml
- [R] traefik/dynamic/security-headers.yml

### A.18 Ledger reconciliation

| Group | Count |
|---|---:|
| Root and GitHub | 19 |
| Agents | 137 |
| Existing audit artifacts | 5 |
| Backend | 134 |
| Database scripts | 2 |
| Frontend | 112 |
| Browser worker | 9 |
| Documentation and n8n | 26 |
| Prompt evaluations | 4 |
| LiteLLM | 1 |
| Notifications | 8 |
| Observability | 8 |
| Review assets | 29 |
| Sample reports | 4 |
| Sample videos | 10 |
| Scripts | 6 |
| Traefik | 2 |
| Total | 516 |
