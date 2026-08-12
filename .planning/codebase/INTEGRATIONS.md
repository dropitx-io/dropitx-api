# External Integrations

**Analysis Date:** 2026-08-12

## APIs & External Services

**Firebase Auth (Google Identity):**
- Purpose: Primary auth provider — verifies Firebase ID tokens (RS256 JWTs) issued to the Next.js frontend
- SDK/Client: none (hand-rolled in `core/security.py`); uses `httpx` to fetch Google's public x509 certs
- Endpoints contacted:
  - `https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com` — signing cert download (`core/security.py:_FIREBASE_CERTS_URL`), cached in-process 1h (`_CERTS_TTL=3600`), refetched on `kid` miss
  - `https://securetoken.google.com/<project_id>` — expected JWT issuer (`_FIREBASE_ISSUER_PREFIX`)
- Auth/config: `FIREBASE_PROJECT_ID` env var (verified at `verify_firebase_jwt` call time; raises if empty); used as both JWT `audience` and issuer suffix
- Callers: `app/dependencies.py:get_firebase_claims` → `get_current_user` / `get_optional_user`; `app/auth/session.py:get_session` provisions users via `provision_firebase_user` RPC
- Verification rules (`core/security.py`): alg must be RS256, `kid` must be present, signature/aud/iss validated by `jose.jwt.decode`, `sub` claim required

**Supabase Cloud (LEGACY, partial):**
- Purpose: Remnant of the pre-migration stack. `SUPABASE_URL` is now used ONLY to construct public storage object URLs; NOT used for auth (replaced by Firebase) or data/storage (replaced by local Postgres + MinIO)
- Usage sites (URL string concatenation only):
  - `app/internal/upload.py` (lines 271, 436), `app/internal/publish.py` (110, 359), `app/internal/multi_upload.py` (140), `app/internal/images.py` (81) — pattern: `f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"`
  - `app/public/preview.py` (251, 263), `core/thumbnail.py` (75) — same pattern for preview/thumbnail URLs
  - `app/public/oembed.py:109` — strips `/api` from `supabase_url` to build oEmbed base URL
- Note: `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` are no longer referenced in code (no longer in `core/config.py:Settings`); `core/supabase.py` re-exports the local shim, not a Supabase client

**DNS Resolution:**
- Purpose: Custom-domain ownership verification
- Client: `dnspython` (`dns.resolver`) in `app/dashboard/domains.py`
- Queries: arbitrary user-supplied domain TXT/CNAME records against public DNS

## Data Storage

**Databases:**
- PostgreSQL 16 (`postgres:16-alpine` in `docker-compose.yml`; StatefulSet in `k8s/postgres.yaml`)
  - Connection: `DATABASE_URL` env (default `postgresql://dropitx:dropitx_local_dev@localhost:5432/dropitx`; k8s: `postgresql.dropitx.svc:5432`)
  - Client: `asyncpg` connection pool (`core/db.py:_get_pool`, `min_size=2, max_size=10, command_timeout=30`)
  - Access pattern: hand-rolled PostgREST-compatible fluent shim (`core/db.py:DatabaseClient`) exposing `.table(name).select/insert/update/delete()`, `.rpc(func, params)`, `.storage.from_(bucket)`. Supersedes `supabase-py`; `core/supabase.py` re-exports `get_admin_client`/`get_anon_client`/`get_user_client`, all returning the same singleton
  - Async/sync bridge: shim runs its own background event loop thread (`_start_background_loop`); route handlers wrap calls in `asyncio.to_thread(...)`
  - Schema sources: `infra/init/` (first-boot source of truth), `supabase/migrations/` (legacy base), `migrations/` (incremental patches), `k8s/auth-stub.sql` (stubs `auth.users`/`auth.uid()` for vanilla Postgres)
  - RPC functions used: `check_rate_limit` (rate limiting), `provision_firebase_user` (auth/session provisioning), plus others in `infra/init/02_rpc_functions.sql`

**File Storage:**
- MinIO (S3-compatible) — `minio/minio:latest` in docker-compose, deployed in k8s namespace
  - Connection: `S3_ENDPOINT` (default `http://localhost:9000`; k8s `http://minio.dropitx.svc:9000`), `S3_ACCESS_KEY`, `S3_SECRET_KEY`
  - Client: `boto3` S3 client, `signature_version="s3v4"`, `region_name="us-east-1"`, constructed lazily per operation in `core/db.py:StorageBucket._client()`
  - Buckets: `html-files` (upload/publish flows), `shares` (v1 API documents); created with anonymous-download policy by the `createbuckets` compose service (`docker-compose.yml`)
  - Operations: `upload`/`update` (`put_object`), `download` (`get_object`), `remove` (`delete_objects`), `get_public_url` (returns `{s3_endpoint}/{bucket}/{path}`)

**Caching:**
- In-process only:
  - Firebase x509 certs: module-level dict in `core/security.py` (`_CERTS_CACHE`, 1h TTL)
  - `DatabaseClient` singleton in `core/db.py` (`_client`), asyncpg pool (`_pool`)
- No Redis/memcached/CDN-side caching layer

## Authentication & Identity

**Auth Provider:**
- Firebase Auth (Google) — RS256 ID token verification in `core/security.py:verify_firebase_jwt`
- Implementation: Bearer token extracted in `app/dependencies.py:_extract_bearer`, verified against Firebase's public certs, aud/iss bound to `FIREBASE_PROJECT_ID`
- Two dependent functions in `app/dependencies.py`:
  - `get_current_user` — verifies JWT then confirms the `sub` (uid) exists in local `auth.users` table; raises `401 user_not_provisioned` if absent
  - `get_optional_user` — same, but returns `None` instead of raising (used by `/api/upload`)
- `get_api_key` — secondary auth via `shk_`/`sht_` API keys (SHA-256 hashed, stored in `api_keys` table); not Firebase

**Provisioning flow:**
- Frontend obtains a Firebase ID token, calls `GET /api/auth/session` (`app/auth/session.py`)
- Backend calls Postgres RPC `provision_firebase_user(p_uid, p_email)` which upserts the local user row and returns the profile

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry or equivalent detected)

**Logs:**
- Structured logging via Python `logging` + custom JSON formatter in `core/logging_config.py`
- JSON format in production (`ENV=production`), human-readable otherwise
- Per-request `request_id` propagated via `contextvars.ContextVar` (`core/logging_config.py:request_id_var`), stamped by `core/middleware.py` middleware
- Health endpoints: `GET /health` (liveness, in `app/main.py`); `/docs` used as k8s readiness/liveness probe target (`k8s/api.yaml`)

## CI/CD & Deployment

**Hosting:**
- Render (`render.yaml`) — `python` web service, free plan, port from `$PORT`
- Kubernetes (Docker Swarm / k8s cluster) — newer path; manifests in `k8s/`

**CI Pipeline:**
- None detected in-repo (no `.github/workflows/`, no GitLab CI). Deployments are manual via `docker compose` / `kubectl` / `k8s/create-secret.sh`

**Image build:**
- `Dockerfile` multi-stage → tagged `dropitx-api:local`, `imagePullPolicy: Never` in k8s

## Environment Configuration

**Required env vars** (see `core/config.py`, `k8s/create-secret.sh`, `render.yaml`):
- `FIREBASE_PROJECT_ID` — Firebase Auth verification (required)
- `DATABASE_URL` — local Postgres DSN
- `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` — MinIO/S3
- `ALLOWED_ORIGINS` — CSV or `*`
- `FRONTEND_URL` — frontend base for invite links / oEmbed

**Legacy env vars (still read, narrow use):**
- `SUPABASE_URL` — used ONLY for public storage URL string construction (NOT auth/data/storage)
- `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` — no longer read by code; safe to remove from deployment env

**Secrets location:**
- Local: `.env` (gitignored; not read by this analysis)
- k8s: `dropitx-env` Secret in namespace `dropitx`, materialized by `k8s/create-secret.sh` from a sourced `.env`; DB/S3 overridden to in-cluster service addresses
- Render: env vars configured in `render.yaml` (marked `sync: false` → managed in dashboard)

## Webhooks & Callbacks

**Incoming:**
- None. All endpoints are request/response REST; no third-party webhook receivers

**Outgoing:**
- None. No outbound webhook/subscription publishes; outbound calls limited to Firebase cert fetch (in `core/security.py`) and DNS queries (`app/dashboard/domains.py`)

---

*Integration audit: 2026-08-12*
