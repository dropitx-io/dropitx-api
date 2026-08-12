<!-- refreshed: 2026-08-12 -->
# Architecture

**Analysis Date:** 2026-08-12

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI ASGI entrypoint                       │
│                       `app/main.py` (`app.main:app`)                 │
│  CORS + `RequestTrackingMiddleware` + `SecurityHeadersMiddleware`    │
├──────────────┬──────────────┬───────────────┬───────────────────────┤
│  /api/v1     │ /api/dashboard│   /api/public │  /api/internal  /api/auth │
│  v1_router   │ dashboard_   │  public_router│ internal_router auth_router│
│              │ router       │               │                   │
│ `app/v1/`    │ `app/        │ `app/public/` │ `app/internal/`  `app/auth/`│
│              │  dashboard/` │               │                   │
└──────┬───────┴──────┬───────┴───────┬───────┴─────────┬────────────┘
       │              │               │                 │
       ▼              ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Route handlers (async)                         │
│  Pydantic DTOs in `models/` · shared helpers (`team_helpers.py`,     │
│  `document_helpers.py`) · auth deps in `app/dependencies.py`         │
└────────────────────────────┬────────────────────────────────────────┘
                             │  every DB/storage call wrapped in
                             │  `await asyncio.to_thread(...)`
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│        PostgREST-compatible shim — `core/db.py` (DatabaseClient)     │
│   .table(name).select/insert/update/delete()  · .rpc(name, params)   │
│   .storage.from_(bucket).upload/download/remove()                    │
│   Runs its own background event-loop thread driving asyncpg pool     │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────┐   ┌──────────────────────────────────────┐
│  Local PostgreSQL        │   │  MinIO / S3 (`StorageBucket`, boto3) │
│  asyncpg pool (2–10)     │   │  buckets: `html-files`, `shares`     │
│  `infra/init/*.sql` +    │   │                                      │
│  `migrations/*.sql`      │   │                                      │
└──────────────────────────┘   └──────────────────────────────────────┘

External (auth only):
  Firebase Auth → `core/security.py` fetches Google x509 certs
  (`https://www.googleapis.com/robot/v1/metadata/x509/securetoken@…`)
  to verify RS256 ID tokens for `FIREBASE_PROJECT_ID`.
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| ASGI app | Router registration, CORS, health endpoint, OpenAPI metadata | `app/main.py` |
| Auth dependencies | Firebase JWT verification, API-key validation, client IP | `app/dependencies.py` |
| DB shim | PostgREST-style query/storage builder over asyncpg + boto3 | `core/db.py` |
| Supabase façade | Thin re-export of `get_admin_client` / `get_anon_client` / `get_user_client` | `core/supabase.py` |
| Security primitives | Firebase cert fetch/cache, API-key gen+hash, bcrypt passwords | `core/security.py` |
| Settings | Pydantic `BaseSettings` (Firebase, DB, S3, CORS, frontend URL) | `core/config.py` |
| Rate limiting | Postgres RPC `check_rate_limit` wrappers | `core/rate_limit.py` |
| Request logging | Per-request ID contextvar, JSON formatter | `core/logging_config.py`, `core/middleware.py` |
| Exceptions | `RateLimitError`, `ShareNotFoundError`, `SharePasswordRequired`, `ErrorResponse` | `core/exceptions.py` |
| v1 documents/keys | API-key-auth document CRUD, revisions, key management | `app/v1/documents.py`, `app/v1/keys.py`, `app/v1/revisions.py`, `app/v1/document_helpers.py` |
| Dashboard | JWT-auth team mgmt, invites, invitations, custom domains | `app/dashboard/teams.py`, `team_invites.py`, `invitations.py`, `domains.py`, `team_helpers.py` |
| Public endpoints | Shares, search, analytics, oEmbed, comments, versions, encryption, preview, QR, profiles, explore, stars, languages | `app/public/*.py` |
| Internal endpoints | Upload, batch upload, publish, images, download, file requests, CLI upload | `app/internal/*.py` |
| Auth session | `GET /api/auth/session` — provisions Firebase user via RPC | `app/auth/session.py` |
| Background tasks | Cleanup of expired file-request uploads + old revisions | `app/services/cleanup.py` |
| Pydantic DTOs | Share, team, API-key, analytics, domain, file-request models | `models/*.py` |

## Pattern Overview

**Overall:** Layered FastAPI monolith with a PostgREST-compatible data-access shim. Routes are thin async handlers; all persistence goes through one synchronous fluent client that mimics `supabase-py`.

**Key Characteristics:**
- Every DB/storage call is wrapped in `await asyncio.to_thread(lambda: client.table(...)...execute())` — routes stay async while the shim runs sync.
- The shim (`core/db.py`) owns a single daemon thread with its own event loop, used to run `asyncpg` from sync context via `asyncio.run_coroutine_threadsafe`.
- One `DatabaseClient` singleton (`get_admin_client`) serves admin, anon, and user access — no RLS, no per-user client. Authorization is enforced explicitly inside each route via `user_id` / role checks.
- Auth is delegated to Firebase (RS256 ID tokens); local Postgres only stores a mirror `auth.users` row for FK and provisioning.

## Layers

**Presentation / routing (`app/`):**
- Purpose: HTTP endpoints, request validation, auth extraction, response shaping.
- Location: `app/main.py`, `app/{v1,dashboard,public,internal,auth}/`, `app/dependencies.py`.
- Contains: FastAPI `APIRouter` modules, Pydantic request/response models defined inline or in `models/`.
- Depends on: `app/dependencies.py` for auth, `core/supabase.py` for the DB client, `models/` DTOs, helper modules per area.
- Used by: uvicorn ASGI server (`uvicorn app.main:app`).

**Domain helpers (`app/**/helpers`, `models/`):**
- Purpose: Cross-route business logic (role checks, document text extraction, slug/token generation).
- Location: `app/dashboard/team_helpers.py`, `app/v1/document_helpers.py`, `models/*.py`.
- Depends on: `core/supabase.py`, `core/nanoid.py`, etc.

**Data access (`core/db.py`, `core/supabase.py`):**
- Purpose: Translate fluent `client.table(...).select/insert/update/delete()` calls into parameterised SQL via asyncpg, and S3 ops via boto3.
- Location: `core/db.py` (533 lines), `core/supabase.py` (10-line re-export).
- Contains: `QueryBuilder`, `RPCBuilder`, `StorageBucket`/`StorageNamespace`, `DatabaseClient`, background-loop bootstrap, row serializer, PostgREST select-column parser (handles `"*, teams(id,name)"` JOINs).
- Depends on: `asyncpg`, `boto3`, `core/config.py`.
- Used by: every route module and `app/services/cleanup.py`.

**Cross-cutting (`core/`):**
- Purpose: Security, rate limiting, logging, middleware, text/encryption utilities.
- Location: `core/security.py`, `core/rate_limit.py`, `core/middleware.py`, `core/logging_config.py`, `core/exceptions.py`, `core/encryption.py`, `core/extract_text.py`, `core/language_detect.py`, `core/thumbnail.py`, `core/nanoid.py`.

**Infrastructure / persistence:**
- PostgreSQL (local or in-cluster), schema seeded by `infra/init/01_schema.sql` + `02_rpc_functions.sql`, then patched by `migrations/*.sql`. `supabase/migrations/` is legacy history for the cloud path.
- MinIO/S3 buckets `html-files` and `shares`.

## Data Flow

### Primary Request Path — authenticated share view

1. Request hits ASGI → CORS → `RequestTrackingMiddleware` sets `request_id_var` (`core/middleware.py:22`).
2. Route dispatch to e.g. `GET /api/shares/{slug}/content` (`app/public/shares.py`).
3. Route calls `get_optional_user` dependency (`app/dependencies.py:84`) — may verify Firebase JWT if a Bearer token is present (`core/security.py:58`).
4. Handler runs `await asyncio.to_thread(lambda: client.table("shares").select("*").eq("slug", slug).execute())` — the lambda executes synchronously inside the worker thread, calling `QueryBuilder.execute()` → `_run_async(self._run())` (`core/db.py:300`).
5. `_run_async` submits the coroutine to the background loop thread (`core/db.py:67`); asyncpg fetches the row; `_serialize_row` converts to JSON-safe dict.
6. Handler applies business rules (expiry, password, burn-after-reading) and returns a Pydantic response model.

### Authenticated dashboard mutation

1. `Depends(get_current_user)` verifies Firebase token, then looks up `auth.users` by `uid` and raises `401 user_not_provisioned` if no local row exists (`app/dependencies.py:56-81`).
2. Route handler uses `require_team_member(user.id, team_id, min_role=...)` from `app/dashboard/team_helpers.py:38` to enforce role weight (`owner 3 > editor 2 > viewer 1`).
3. Mutation issues `client.table(...).update({...}).eq(...).execute()` via `asyncio.to_thread`.

### Provisioning flow (new Firebase user)

1. FE obtains a Firebase ID token, calls `GET /api/auth/session` (`app/auth/session.py:27`).
2. `get_firebase_claims` verifies the token; the route calls the Postgres RPC `provision_firebase_user(p_uid, p_email)` (`migrations/008_provision_firebase_user.sql`).
3. The RPC upserts `auth.users` + profile rows and returns the profile dict.

**State Management:**
- No in-memory session state. Per-request state lives only in FastAPI dependencies (`User`, `ApiKeyAuth`).
- Module-level singletons: `_client` (DatabaseClient), `_pool` (asyncpg), `_loop`/`_loop_thread`, Firebase cert cache `_CERTS_CACHE`/`_CERTS_EXPIRES` (`core/security.py`). These persist for the process lifetime.

## Key Abstractions

**DatabaseClient / QueryBuilder:**
- Purpose: Drop-in replacement for `supabase-py`'s `Client`. Lets routes stay framework-agnostic about which backend runs.
- Examples: `core/db.py:495` (`DatabaseClient`), `core/db.py:176` (`QueryBuilder`).
- Pattern: Fluent builder accumulating filters/ops; terminal `.execute()` synchronously runs the query and returns `PostgRESTResponse(data=..., count=...)`.

**Auth dependencies:**
- Purpose: Composable FastAPI `Depends` callables that attach an identity to the request.
- Examples: `app/dependencies.py:56` (`get_current_user`), `:84` (`get_optional_user`), `:96` (`get_api_key`), `:41` (`get_firebase_claims`).
- Pattern: Extract Bearer token → verify (Firebase certs or SHA-256 lookup against `api_keys`) → return a frozen dataclass; raise `HTTPException(401)` on any failure.

**Pydantic DTOs:**
- Purpose: Request validation + response shaping + OpenAPI schema generation.
- Examples: `models/share.py`, `models/team.py`, `models/api_key.py`, `models/analytics.py`, `models/domain.py`, `models/file_request.py`; inline DTOs in route files (e.g. `app/v1/documents.py:32`).
- Pattern: `BaseModel` with `Field(...)` constraints; `Literal` types for enums (`TeamRole`, `TeamPlan`).

## Entry Points

**ASGI app:**
- Location: `app/main.py:78` (`app = FastAPI(...)`).
- Triggers: uvicorn (`uvicorn app.main:app --reload`, `Dockerfile` CMD, `render.yaml` start command, `k8s/api.yaml`).
- Responsibilities: Mounts routers under `/api/v1`, `/api/dashboard`, `/api` (public + internal + invite actions), `/api/auth`; adds CORS, request tracking, security headers; exposes `/health` and `/docs`.

**Local infra bootstrap:**
- `docker-compose.yml` brings up Postgres + MinIO and runs `infra/init/*.sql` on first boot. `createbuckets` service creates the `html-files` and `shares` buckets.

**k8s deployment:**
- `k8s/{namespace,postgres,minio,api,migrate-job}.yaml` plus `auth-stub.sql` (stubs `auth.users`/`auth.uid()`/`auth.role()` on vanilla Postgres so Supabase-style migrations apply).

## Architectural Constraints

- **Threading:** FastAPI runs on the main asyncio loop; every DB/storage call must be offloaded with `asyncio.to_thread()`. The shim itself runs asyncpg on a separate daemon thread + dedicated event loop — only one such loop exists per process.
- **Global state:** `core/db.py` module-level `_pool`, `_loop`, `_loop_thread`, `_client`; `core/security.py` module-level `_CERTS_CACHE`, `_CERTS_EXPIRES`; `core/logging_config.py` `request_id_var` (ContextVar). All process-local; not multi-worker safe without care.
- **Connection pool:** asyncpg pool `min_size=2, max_size=10, command_timeout=30` (`core/db.py:77`). `_run_async` blocks with `future.result(timeout=30)` (`core/db.py:71`).
- **No RLS / no anon distinction:** `get_admin_client` == `get_anon_client` == `get_user_client` (all the same singleton). Authorization must be encoded in each route via explicit `user_id` filters and role checks.
- **Auth backend is Firebase-only:** `verify_firebase_jwt` requires `FIREBASE_PROJECT_ID`; audience/issuer pinned to that project. There is no Supabase JWT path anymore.
- **Sync API inside the shim:** Filters/operators (`eq`, `in_`, `is_`, `like`, `ilike`, `contains`, `overlaps`, `gt`/`gte`/`lt`/`lte`) are implemented inline — adding a new query shape means editing `QueryBuilder` in `core/db.py`, not emitting raw SQL in routes.
- **Circular-import workaround:** `app/dashboard/team_invites.py` imports `teams.router` and registers more routes onto the same `APIRouter` instance via side-effect; `app/dashboard/router.py` imports it under `noqa: F401` to trigger registration.
- **Migrations split across three dirs:** `infra/init/` (fresh local source of truth), `migrations/` (incremental patches, applied by `k8s/migrate-job.yaml`), `supabase/migrations/` (legacy cloud history). New schema changes must update `infra/init/` plus add a patch under `migrations/`.

## Anti-Patterns

### Routes call the DB client directly instead of a repository layer

**What happens:** Route handlers (`app/public/shares.py`, `app/v1/documents.py`, `app/dashboard/*.py`) inline `client.table("...").select(...).eq(...).execute()` everywhere.
**Why it's wrong:** SQL shape and business rules are scattered across ~30 route files; refactoring a table column touches many handlers; harder to test in isolation.
**Do this instead:** For new features, factor the data access into a module under the area (mirroring `app/dashboard/team_helpers.py` and `app/v1/document_helpers.py`) so handlers stay thin. Do not retrofit unless the area is already being rewritten.

### DB/storage calls not wrapped in `asyncio.to_thread`

**What happens occasionally:** Forgetting the wrap blocks the FastAPI event loop because `QueryBuilder.execute()` is synchronous and calls `future.result(timeout=30)`.
**Why it's wrong:** A single missing `await asyncio.to_thread(...)` stalls every other request on that worker.
**Do this instead:** Always `await asyncio.to_thread(lambda: client.<call>().execute())`. The lint reviewer / code review must reject synchronous shim calls invoked directly from an `async def` handler.

### Registering routes via import side-effect

**What happens:** `app/dashboard/team_invites.py` mutates `app/dashboard/teams.router` at import time, so the router file alone does not show all its routes.
**Why it's wrong:** Route discovery requires reading both files; easy to miss when grepping.
**Do this instead:** For new sub-routers, follow `app/v1/router.py` / `app/public/router.py` — declare an `APIRouter()` in the sub-module and `router.include_router(...)` it from the area's `router.py`. Leave the `team_invites.py` pattern alone unless restructuring that area.

## Error Handling

**Strategy:** Route handlers raise `HTTPException(status_code, detail)` directly; lower layers raise domain exceptions from `core/exceptions.py` which can be caught and translated in the handler.

**Patterns:**
- Auth failures → `HTTPException(401, ...)` with a plain string or `{"code": ..., "message": ...}` dict (see `app/dependencies.py:75` for the `user_not_provisioned` code shape).
- Permission failures → `HTTPException(403, ...)` from `require_team_member` (`app/dashboard/team_helpers.py`).
- Not-found / expired shares → `HTTPException(404)` / `HTTPException(410)` inside `app/public/shares.py`.
- Rate-limit exceeded → `core/rate_limit.py` returns a `RateLimitResult`; handlers translate `success=False` into `HTTPException(429)` with `Retry-After`.
- `RequestTrackingMiddleware` logs unhandled exceptions with `exc_info=True` before re-raising (`core/middleware.py:34`).

## Cross-Cutting Concerns

**Logging:** Structured JSON when `ENV=production`, human-readable otherwise (`core/logging_config.py`). Every request is logged by `RequestTrackingMiddleware` with method, path, status, latency, client IP, and the per-request `request_id` (also echoed back as `x-request-id`).

**Validation:** Pydantic v2 `BaseModel` on every request and response model; `Field(min_length=..., max_length=...)` constraints enforced by FastAPI before the handler runs.

**Authentication:** Two parallel schemes selected by header prefix: Firebase JWT (`Bearer <token>`, verified by `core/security.py`) and API key (`Bearer shk_...` / `Bearer sht_...`, SHA-256 lookup against `api_keys`). Auth is always a FastAPI `Depends(...)` — there is no global auth middleware.

**Rate limiting:** Delegated to the Postgres RPC `check_rate_limit` (per-IP bucketing); fail-open vs fail-closed is per-endpoint (`core/rate_limit.py`).

**Security headers:** `SecurityHeadersMiddleware` injects `strict-transport-security`, `x-content-type-options`, `x-frame-options: DENY`, `referrer-policy`, and a restrictive `permissions-policy` on every response (`core/middleware.py:70`).

---

*Architecture analysis: 2026-08-12*
