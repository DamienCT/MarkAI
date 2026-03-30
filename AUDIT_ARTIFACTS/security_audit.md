# MARKAI Security Audit - Phase 4

**Date:** 2026-03-30
**Scope:** Cross-cutting security analysis of authentication, network, data, and infrastructure
**Auditor:** Claude Opus 4.6 (automated)

---

## Executive Summary

The MARKAI system demonstrates a solid security foundation with Microsoft Entra ID (Azure AD) SSO, proper JWT validation with RS256, multi-stage Docker builds with non-root users, production-startup guards for default secrets, and CORS restricted to a single origin. However, several gaps exist, particularly around rate limiting, internal service authentication, file upload validation, and CSP configuration. There are no critical vulnerabilities that enable immediate unauthorized access, but several HIGH-severity issues require attention before production hardening.

**Finding counts:** CRITICAL: 0 | HIGH: 5 | MEDIUM: 10 | LOW: 6

---

## 4.1 Authentication & Session Security

### A-1: JWT Implementation (RS256 with Entra ID JWKS) -- GOOD

**Status: PASS**

The backend validates JWTs issued by Microsoft Entra ID using proper RS256 signature verification via JWKS endpoint (`backend/app/auth/entra.py`):

- Algorithm restricted to `RS256` only (no `none` algorithm, no HS256 confusion)
- Audience (`aud`) verification enabled
- Issuer (`iss`) verification against tenant-specific URL
- Signing key fetched from Microsoft's JWKS endpoint (auto-rotated)

No custom JWT signing is used -- the system relies entirely on Microsoft Entra ID tokens, which is the correct approach.

### A-2: No Password Hashing Required -- N/A

The system uses Microsoft Entra ID SSO exclusively. No local password storage or hashing exists, which eliminates an entire class of vulnerabilities.

### A-3: Session Management via NextAuth JWT Strategy -- GOOD

**File:** `frontend/src/lib/auth.ts`

- NextAuth configured with `strategy: "jwt"` (no server-side sessions to steal)
- Token refresh implemented with 5-minute buffer before expiration
- `NEXTAUTH_SECRET` used for JWT encryption (must be set via env var)
- Refresh token rotation: new refresh tokens from Azure replace old ones

### A-4: NEXTAUTH_SECRET Not Validated at Startup -- MEDIUM

**File:** `frontend/src/lib/auth.ts:127`

```typescript
secret: process.env.NEXTAUTH_SECRET,
```

Unlike the backend which refuses to start with default secrets in production, the frontend does not validate that `NEXTAUTH_SECRET` is set. If missing, NextAuth falls back to a derived secret from other env vars, which may be predictable.

**Recommendation:** Add a startup check that fails if `NEXTAUTH_SECRET` is not set when `NODE_ENV=production`.

### A-5: Auto-Provisioning Admin Role via Security Group -- GOOD with NOTE

**File:** `backend/app/deps.py:79-106`

Users in the configured Entra ID security group are auto-provisioned as `admin` with `is_active=True`. This is a reasonable pattern but means anyone added to the Azure AD group immediately gets full admin access. The fallback Graph API check (`check_user_in_security_group`) ensures this works even without group claims in the JWT.

**Note:** If `ADMIN_SECURITY_GROUP_ID` is misconfigured (e.g., set to a broad group), excessive admin access could result.

### A-6: Role Check Inconsistency -- Pattern vs Dependency -- LOW

**Files:** `backend/app/auth/permissions.py`, various API routes

Two patterns exist for role checking:
1. `require_role` decorator (wrapper-based)
2. Inline `role_has_access()` calls in route handlers

Both work correctly, but the inconsistency could lead to a missed check in a new route. The `require_role_dependency` function exists but is not used anywhere.

**Recommendation:** Standardize on one pattern (preferably FastAPI `Depends`) and enforce via code review.

### A-7: API Key Management -- GOOD

All API keys (OpenAI, Gemini, Meta, LinkedIn, TikTok, X, YouTube, Fabric) are loaded from environment variables via Pydantic `BaseSettings`. No keys are hardcoded in source code. The `.env` file is properly gitignored, and only `.env.example` and `.env.vps.example` are tracked.

### A-8: Webhook Authentication Uses Timing-Safe Comparison -- GOOD

**File:** `backend/app/api/v1/webhooks.py:27`

```python
secrets.compare_digest(incoming_secret, configured_secret)
```

The webhook endpoint correctly uses `secrets.compare_digest` to prevent timing attacks on the shared secret.

---

## 4.2 Network Security

### N-1: CORS Configuration -- GOOD

**File:** `backend/app/main.py:68-77`

```python
_frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
_cors_origins = [_frontend_url]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CORS is restricted to a single configured origin. The comment explicitly notes not to combine `allow_origins=["*"]` with `allow_credentials=True`. Good.

**Minor concern:** `allow_methods=["*"]` and `allow_headers=["*"]` are overly permissive. Consider restricting to actual methods/headers used.

### N-2: CSP Headers -- MEDIUM (unsafe-inline, unsafe-eval)

**File:** `traefik/dynamic/security-headers.yml:15`

```
contentSecurityPolicy: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; ..."
```

The CSP allows `'unsafe-inline'` and `'unsafe-eval'` for scripts. While Next.js often requires `'unsafe-inline'` for styles, `'unsafe-eval'` for scripts significantly weakens XSS protection.

**Severity: MEDIUM**
**Recommendation:** Use nonces for inline scripts instead of `'unsafe-eval'`. Next.js supports CSP nonces via `next.config.js` headers.

### N-3: Security Headers -- GOOD

**File:** `traefik/dynamic/security-headers.yml`

All standard security headers are configured:
- `X-Frame-Options: DENY` (frameDeny)
- `X-Content-Type-Options: nosniff` (contentTypeNosniff)
- `X-XSS-Protection: 1; mode=block` (browserXssFilter)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- `X-Powered-By` and `Server` headers stripped

### N-4: No Rate Limiting -- HIGH

**Severity: HIGH**

No rate limiting is implemented anywhere in the stack:
- No rate limiting middleware on the FastAPI backend
- No rate limiting in Traefik configuration
- No rate limiting on authentication endpoints
- No rate limiting on file upload endpoints
- No rate limiting on LLM proxy endpoints (which cost money per request)

**Impact:** The system is vulnerable to:
- Brute force attacks on the auth flow (though Entra ID has its own protections)
- Denial of service via resource exhaustion
- Financial abuse via excessive LLM API calls
- File upload abuse

**Recommendation:** Add rate limiting at the Traefik layer (middleware `rateLimit`) and/or in FastAPI using `slowapi` or similar. Priority endpoints: `/api/v1/intelligence/*`, `/api/v1/webhooks/*`, file upload routes.

### N-5: No Request Size Limits on Backend -- HIGH

**Severity: HIGH**

**File:** `backend/app/api/v1/products.py:158`

The product image upload endpoint reads the entire file into memory without any size limit:

```python
file_data = await file.read()
```

Unlike the brand logo upload (which checks `len(data) > 5 * 1024 * 1024`), the product image upload has no file size validation, no content-type validation, and stores the user-supplied filename directly.

**Also affected:** No global request body size limit is configured for uvicorn or FastAPI.

**Recommendation:**
1. Add size validation to product upload (match the 5MB limit from brand logos)
2. Add content-type validation (allow only image types)
3. Sanitize filenames before using in MinIO paths
4. Set `--limit-max-request-size` on uvicorn or add middleware

### N-6: Cookie Configuration -- LOW

No explicit cookie configuration exists. NextAuth manages session cookies with its defaults. In production with HTTPS, NextAuth automatically uses `Secure` and `HttpOnly` flags when `NEXTAUTH_URL` uses `https://`.

**Recommendation:** Explicitly set `cookies` in NextAuth config to ensure `SameSite=Lax`, `Secure=true`, `HttpOnly=true`.

### N-7: HTTP to HTTPS Redirect -- GOOD

**File:** `traefik/traefik.yml:12-16`

Traefik redirects all HTTP traffic to HTTPS.

### N-8: Internal Services Not Exposed in Production -- GOOD

**File:** `docker-compose.yml` (base) has no port bindings. `docker-compose.vps.yml` only exposes backend and frontend via Traefik labels. Dev overrides bind internal services to `127.0.0.1` only (except n8n on `5678:5678` and backend on `8000:8000`).

---

## 4.3 Data Security

### D-1: PII Inventory in Database

**File:** `db/init.sql`

| Table | PII Fields | Sensitivity |
|-------|-----------|-------------|
| `users` | `email`, `display_name`, `entra_object_id`, `avatar_url` | HIGH |
| `audit_log` | `ip_address`, `user_agent` | MEDIUM |
| `brands` | `website_url`, business data | LOW |
| `products` | Product/pricing data | LOW |
| `notifications` | User-specific messages | LOW |

The PII footprint is minimal -- only user identity fields from Entra ID. No addresses, phone numbers, or payment data are stored.

### D-2: Data Sent to External LLM Providers -- MEDIUM

**Severity: MEDIUM**

The following brand data is sent to OpenAI/Gemini:

1. **Brand guidelines** (tone, colors, visual style) -- via content generation prompts
2. **Product names and descriptions** -- via content generation and image search
3. **Target audience data** -- via strategy and planning prompts
4. **Competitor information** -- via research workflows
5. **Calendar item details** (themes, pillars, briefs) -- via content generation

**Files:** `agents/shared/tools/database.py:45`, `agents/workflows/content/nodes.py`, `agents/workflows/research/nodes.py`, `backend/app/api/v1/intelligence.py`

This is inherent to the application's purpose, but clients should be informed that their brand data is processed by third-party AI providers.

**Recommendation:** Document data processing in terms of service. Consider offering data processing agreements (DPAs) with LLM providers.

### D-3: Product Image Search Sends Data to DuckDuckGo -- LOW

**File:** `backend/app/services/gemini_service.py:53-56`

Product names and partial descriptions are sent to DuckDuckGo for image search:
```python
query = f"{product_name} {product_description[:50]} product photo"
```

This is expected behavior but worth noting in privacy documentation.

### D-4: Log Sanitization -- GOOD

**File:** `backend/app/main.py:88-92`

The global exception handler sanitizes stack traces by filtering lines containing secret-related keywords:
```python
sanitized_tb = "\n".join(
    line for line in tb_text.splitlines()
    if not any(s in line.lower() for s in ("secret", "password", "api_key", "token", "credential"))
)
```

**Minor gap:** This is keyword-based and could miss secrets in unusual variable names. However, it covers the main patterns.

### D-5: Error Message Sanitization -- GOOD

**File:** `backend/app/main.py:101-102`

The global exception handler returns a generic message to clients:
```python
content={"detail": "Internal server error"}
```

No internal exception details leak to the client.

### D-6: Audit Log Endpoint Exposes IP and User Agent -- LOW

**File:** `backend/app/api/v1/system.py:180-181`

The audit log endpoint returns `ip_address` and `user_agent` to any user with manager role. This is mildly sensitive PII.

**Recommendation:** Consider restricting audit log access to admin role only, or redacting IP addresses for non-admin users.

### D-7: Files Endpoint Has No Authentication -- HIGH

**Severity: HIGH**

**File:** `backend/app/api/v1/files.py:20-26`

```python
@router.get("/{file_path:path}")
async def serve_file(file_path: str):
    """No auth required -- object paths contain UUIDs and are not guessable."""
```

The file serving endpoint has NO authentication. The comment claims security through UUID-based obscurity, but:
1. UUIDs in URLs may appear in logs, browser history, referrer headers
2. If any content URL is shared or leaked, anyone can access it
3. No access control means any generated content is publicly accessible to anyone who knows the path

**Recommendation:** Add authentication to file serving, or implement signed URLs with time-limited tokens. At minimum, add a random token component to file paths.

### D-8: Brand Logo Endpoint Has No Authentication -- MEDIUM

**File:** `backend/app/api/v1/brands.py:310-315`

The `GET /{brand_id}/logos/{label}` endpoint serves logo files without authentication. While logos are less sensitive than generated content, this means anyone who knows a brand UUID can access its logos.

---

## 4.4 Infrastructure Security

### I-1: All Dockerfiles Use Multi-Stage Builds -- GOOD

All five Dockerfiles use multi-stage builds:
- `backend/Dockerfile`: builder -> runtime
- `frontend/Dockerfile`: deps -> builder -> runner
- `agents/Dockerfile`: builder -> runtime
- `browser-worker/Dockerfile`: builder -> runtime
- `notifications/Dockerfile`: builder -> runtime

Build tools and source files are not carried into runtime images.

### I-2: All Containers Run as Non-Root -- GOOD

All custom Dockerfiles create and switch to a non-root user:
- Backend: `appuser` (UID 1001)
- Frontend: `nextjs` (UID 1001, GID nodejs:1001)
- Agents: `appuser` (UID 1001)
- Browser Worker: `appuser` (UID 1001)
- Notifications: `appuser` (UID 1001)

### I-3: No Secrets in Docker Layers -- GOOD

No secrets are baked into Docker images. All secrets are injected via `env_file: .env` at runtime in docker-compose. Build args for the frontend only contain public values (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_AZURE_AD_CLIENT_ID`).

### I-4: Docker Socket Mounted to Traefik -- MEDIUM

**File:** `docker-compose.yml:22`

```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```

The Docker socket is mounted read-only into the Traefik container for service discovery. While `:ro` limits write access, a compromised Traefik container could still enumerate all containers and their environment variables (which include secrets).

**Recommendation:** Use a Docker socket proxy (like `tecnativa/docker-socket-proxy`) to limit Traefik's API access to only the endpoints it needs.

### I-5: Valkey (Redis) Has No Authentication -- HIGH

**Severity: HIGH**

**File:** `docker-compose.yml:97-110`

Valkey is deployed without any password or ACL configuration. Any container on the `markai-net` network can connect to Valkey and read/write data, including cached LLM responses and potentially session data.

**Also applies to:**
- **NATS** (no authentication configured, lines 113-127)
- **Qdrant** (no API key configured, lines 61-74)

While these services are only accessible within the Docker network, a compromised container could access all internal services.

**Recommendation:** Enable authentication for Valkey (`--requirepass`), NATS (token or user/password), and Qdrant (API key).

### I-6: MinIO Uses Insecure Connection -- MEDIUM

**File:** `backend/app/services/minio_service.py:23`

```python
_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=False,
)
```

MinIO connection uses `secure=False` (HTTP). While this is within the Docker network, credentials are transmitted in plaintext. A network-level attack within the container network could intercept MinIO credentials.

**Recommendation:** Enable TLS for MinIO in production, or accept the risk as internal-only traffic.

### I-7: Default Credentials with Production Guards -- GOOD

**File:** `backend/app/config.py:128-159`

The backend refuses to start in production mode if:
- `SECRET_KEY`, `POSTGRES_PASSWORD`, or `MINIO_SECRET_KEY` are at default values
- `AZURE_AD_TENANT_ID`, `AZURE_AD_CLIENT_ID`, or `AZURE_AD_CLIENT_SECRET` are empty

This is excellent defense-in-depth.

**Gap:** The Grafana admin password defaults to `change-me-grafana` (`observability/grafana/grafana.ini:9`) with no startup validation.

### I-8: Loki Auth Disabled -- MEDIUM

**File:** `observability/loki/loki-config.yaml:6`

```yaml
auth_enabled: false
```

Loki runs without authentication. Any container on the network can push arbitrary logs or query all stored logs. The file includes a comment acknowledging this is for single-tenant dev.

**Recommendation:** Enable auth in production or restrict network access.

### I-9: Traefik Dashboard with Hardcoded Bcrypt Hash -- MEDIUM

**File:** `docker-compose.yml:30`

```yaml
- "traefik.http.middlewares.dashboard-auth.basicauth.users=admin:$$2y$$05$$Y6kz..."
```

The Traefik dashboard basic auth hash is hardcoded in the docker-compose file (which is committed to git). While this is a bcrypt hash and not plaintext, the credentials are static and visible to anyone with repo access.

**Recommendation:** Move the basicauth users to an external file or environment variable.

### I-10: .env Handling -- GOOD

- `.env`, `.env.local`, `.env.production` are all in `.gitignore`
- `docker-compose.override.yml` (dev-only port bindings) is gitignored
- `.env.example` and `.env.vps.example` are tracked but contain only placeholder values

### I-11: Production Port Exposure -- GOOD

**File:** `docker-compose.vps.yml`

In production, only frontend and backend are exposed via Traefik labels. No direct port bindings. The bundled Traefik and n8n are disabled (using VPS-level equivalents).

### I-12: Filename Injection in Product Upload -- MEDIUM

**File:** `backend/app/api/v1/products.py:159`

```python
object_name = f"products/{product_id}/{file.filename}"
```

The user-supplied filename is used directly in the MinIO object path without sanitization. While MinIO treats object names as opaque strings (no directory traversal), malicious filenames could cause issues in log parsing, downstream tools, or URL generation.

**Recommendation:** Sanitize or replace the filename with a generated UUID + original extension.

---

## Summary Table

| ID | Finding | Severity | Category |
|----|---------|----------|----------|
| N-4 | No rate limiting anywhere in the stack | HIGH | Network |
| N-5 | No request size limit on product image upload | HIGH | Network |
| D-7 | Files endpoint serves MinIO content without authentication | HIGH | Data |
| I-5 | Valkey, NATS, and Qdrant have no authentication | HIGH | Infrastructure |
| I-9 | Traefik dashboard credentials hardcoded in compose file | HIGH | Infrastructure |
| A-4 | NEXTAUTH_SECRET not validated at startup | MEDIUM | Auth |
| N-2 | CSP allows unsafe-inline and unsafe-eval for scripts | MEDIUM | Network |
| D-2 | Brand/product data sent to external LLM providers | MEDIUM | Data |
| D-8 | Brand logo endpoint has no authentication | MEDIUM | Data |
| I-4 | Docker socket mounted to Traefik container | MEDIUM | Infrastructure |
| I-6 | MinIO connection uses plaintext HTTP | MEDIUM | Infrastructure |
| I-8 | Loki runs without authentication | MEDIUM | Infrastructure |
| I-12 | Unsanitized filename in product image upload | MEDIUM | Infrastructure |
| I-7g | Grafana default admin password not enforced | MEDIUM | Infrastructure |
| A-6 | Inconsistent role-check patterns across routes | LOW | Auth |
| N-6 | No explicit cookie security attributes in NextAuth | LOW | Network |
| D-3 | Product names sent to DuckDuckGo for image search | LOW | Data |
| D-6 | Audit log exposes IP/user-agent to managers | LOW | Data |
| N-1m | CORS allows all methods and headers | LOW | Network |
| N-8d | Dev override exposes n8n (5678) and backend (8000) on 0.0.0.0 | LOW | Network |

---

## Recommended Priority Actions

1. **Add rate limiting** (N-4): Deploy Traefik `rateLimit` middleware for all routes and stricter limits on `/api/v1/intelligence/*` and upload endpoints
2. **Add authentication to file serving** (D-7): Implement signed URLs or require Bearer token for `/api/v1/files/*`
3. **Add file upload validation** (N-5): Size limits, content-type validation, and filename sanitization for product image uploads
4. **Enable internal service authentication** (I-5): Password-protect Valkey, add NATS auth, set Qdrant API key
5. **Move Traefik dashboard credentials to env var** (I-9): Remove hardcoded bcrypt hash from compose file
