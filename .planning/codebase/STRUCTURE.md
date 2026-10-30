# Codebase Structure

**Analysis Date:** 2026-08-12

## Directory Layout

```
dropitx-api/
├── app/                      # FastAPI application — routes, deps, services
│   ├── main.py               # ASGI app, router registration, /health
│   ├── dependencies.py       # Auth deps (Firebase JWT, API key, client IP)
│   ├── auth/                 # /api/auth — session provisioning endpoint
│   ├── dashboard/            # /api/dashboard — JWT-auth team management
│   ├── internal/             # /api/* (internal) — upload/publish/images/download/file-requests
│   ├── public/               # /api/* (public) — shares/search/analytics/oembed/comments/...
│   ├── services/             # Background cleanup tasks
│   └── v1/                   # /api/v1 — API-key-auth documents/keys/revisions
├── core/                     # Cross-cutting infra: DB shim, security, middleware, utils
│   ├── db.py                 # PostgREST-compatible shim over asyncpg + boto3
│   ├── supabase.py           # Thin re-export of get_*_client from db.py
│   ├── config.py             # Pydantic Settings
│   ├── security.py           # Firebase JWT verify, API-key gen/hash, bcrypt
│   ├── rate_limit.py         # Postgres RPC rate limiting
│   ├── middleware.py         # Request tracking + security headers
│   ├── logging_config.py     # JSON logging + request_id ContextVar
│   ├── exceptions.py         # Domain exceptions + ErrorResponse envelope
│   ├── encryption.py         # AES-256-GCM + PBKDF2 helpers
│   ├── extract_text.py       # HTML/Markdown text extraction
│   ├── language_detect.py    # Language detection + listing
│   ├── thumbnail.py          # Thumbnail generation
│   └── nanoid.py             # Slug + delete-token generators
├── models/                   # Pydantic DTOs (share, team, api_key, analytics, domain, file_request)
├── infra/                    # Local infra bootstrap
│   └── init/                 # 01_schema.sql + 02_rpc_functions.sql (mounted into Postgres container)
├── migrations/               # Incremental SQL patches layered on top of init
├── supabase/                 # Legacy Supabase-cloud artifacts
│   └── migrations/           # Original cloud schema history (base + feature migrations)
├── k8s/                      # Kubernetes manifests (namespace/postgres/minio/api/migrate-job) + auth-stub.sql
├── tests/                    # pytest suites (endpoint wiring + integration)
├── cli/                      # Node.js CLI (separate npm package — not part of Python build)
├── docs/                     # Project docs (architecture, roadmap, deployment, etc.)
├── plans/                    # Local planning artifacts and reports
├── .planning/                # GSD workspace (codebase maps, graphs)
├── docker-compose.yml        # Local Postgres + MinIO + createbuckets service
├── Dockerfile                # Container image for API
├── render.yaml               # Render blueprint (legacy cloud-Supabase path)
├── pyproject.toml            # Python project + tool config
├── requirements.txt          # Pip deps (Render build)
├── uv.lock                   # Reproducible install lockfile
├── .env.example              # Supabase-cloud env baseline
└── .env.local.example        # Local Postgres+MinIO env baseline
```

## Directory Purposes

**`app/` — FastAPI presentation layer:**
- Purpose: All HTTP route handlers, auth dependencies, and background task services.
- Contains: One `APIRouter` module per endpoint group; `main.py` aggregator; `dependencies.py`.
- Key files: `app/main.py`, `app/dependencies.py`, `app/v1/router.py`, `app/dashboard/router.py`, `app/public/router.py`, `app/internal/router.py`, `app/auth/router.py`.

**`app/auth/` — Firebase session provisioning:**
- Purpose: `GET /api/auth/session` verifies a Firebase ID token and runs the `provision_firebase_user` RPC.
- Key files: `app/auth/session.py`, `app/auth/router.py`.

**`app/v1/` — API-key-auth document API:**
- Purpose: `/api/v1/documents`, `/api/v1/keys`, `/api/v1/revisions` — all secured by `get_api_key`.
- Key files: `app/v1/documents.py`, `app/v1/keys.py`, `app/v1/revisions.py`, `app/v1/document_helpers.py`, `app/v1/router.py`.

**`app/dashboard/` — JWT-auth team management:**
- Purpose: `/api/dashboard/teams*`, invites, invitations, custom domains, tags, folders, audit events.
- Key files: `app/dashboard/teams.py`, `team_invites.py`, `invitations.py`, `domains.py`, `team_helpers.py`, `router.py`.
- Note: `team_invites.py` registers more handlers onto `teams.router` via import side-effect.

**`app/public/` — Public endpoints (no auth or optional auth):**
- Purpose: Share viewing/QR/preview, search, analytics tracking, oEmbed, comments, versions, encryption metadata, profiles, explore, stars, languages, public file requests.
- Key files: `app/public/shares.py`, `search.py`, `analytics.py`, `oembed.py`, `comments.py`, `versions.py`, `encryption.py`, `preview.py`, `qrcode.py`, `profiles.py`, `explore.py`, `stars.py`, `languages.py`, `file_requests.py`, `router.py`.

**`app/internal/` — Authenticated upload/publish flows:**
- Purpose: Single + batch upload, publish (HTML editor content), images, downloads, file-request intake, CLI upload.
- Key files: `app/internal/upload.py`, `multi_upload.py`, `publish.py`, `images.py`, `download.py`, `file_requests.py`, `cli_upload.py`, `router.py`.

**`app/services/` — Background jobs:**
- Purpose: Periodic cleanup of expired file-request uploads and old share revisions (5-min interval).
- Key files: `app/services/cleanup.py`.

**`core/` — Cross-cutting infrastructure:**
- Purpose: DB/data-access shim, security, rate limiting, logging, middleware, small utilities (text extraction, language detection, thumbnails, nanoid, encryption).
- Key files: `core/db.py`, `core/security.py`, `core/config.py`, `core/supabase.py`, `core/rate_limit.py`, `core/middleware.py`, `core/logging_config.py`, `core/exceptions.py`, `core/encryption.py`, `core/nanoid.py`.

**`models/` — Pydantic DTOs:**
- Purpose: Request/response shapes shared across routes and OpenAPI schema.
- Key files: `models/share.py`, `models/team.py`, `models/api_key.py`, `models/analytics.py`, `models/domain.py`, `models/file_request.py`.

**`infra/init/` — Fresh-DB seed (local source of truth):**
- Purpose: `docker-entrypoint-initdb.d` mounted into the local Postgres container; runs on first boot only.
- Key files: `infra/init/01_schema.sql`, `infra/init/02_rpc_functions.sql`.

**`migrations/` — Incremental SQL patches:**
- Purpose: Layered schema changes (encryption columns, burn-after-reading, custom domains, Firebase uid retype, `provision_firebase_user` RPC, etc.). Applied by `k8s/migrate-job.yaml` against existing DBs.
- Naming: `NNN_<short_slug>.sql` (zero-padded 3-digit index).

**`supabase/migrations/` — Legacy cloud schema:**
- Purpose: Original Supabase-cloud schema history (`20260529_base_schema.sql` through `20260531_*`). Retained for reference and for the cloud-Auth path; not applied by the local stack.

**`k8s/` — Kubernetes deployment:**
- Purpose: Manifests for the local-Postgres/MinIO stack on a cluster.
- Key files: `namespace.yaml`, `postgres.yaml`, `minio.yaml`, `api.yaml`, `migrate-job.yaml`, `create-secret.sh`, `auth-stub.sql` (stubs `auth.users` / `auth.uid()` / `auth.role()` on vanilla Postgres).

**`tests/` — pytest suites:**
- Purpose: Endpoint wiring over ASGI transport (`test_all_endpoints.py`) plus integration tests that need a live local Postgres/MinIO.
- Key files: `tests/test_all_endpoints.py`, `tests/test_file_requests.py`.

**`cli/` — Node.js CLI (separate subproject):**
- Purpose: `dropitx` npm package; not part of the Python build.

**`docs/`, `plans/`, `.planning/`:**
- Purpose: Project documentation, ad-hoc plans/reports, and the GSD workspace (codebase maps under `.planning/codebase/`).

## Key File Locations

**Entry Points:**
- `app/main.py:78`: FastAPI app instantiation and router mounting.
- `app/main.py:115`: `/health` endpoint.
- `Dockerfile`: container entrypoint.
- `render.yaml`: Render start command.
- `k8s/api.yaml`: Kubernetes Deployment for the API.

**Configuration:**
- `core/config.py:4`: `Settings` (Pydantic BaseSettings).
- `docker-compose.yml`: local Postgres + MinIO + `createbuckets`.
- `pyproject.toml`, `requirements.txt`, `uv.lock`: Python deps.
- `.env.example` (Supabase-cloud baseline), `.env.local.example` (local stack baseline). `.env` exists in repo but must never be read or committed.

**Core Logic:**
- `core/db.py:495`: `DatabaseClient` (the singleton used everywhere).
- `core/db.py:176`: `QueryBuilder` (PostgREST-style fluent API).
- `core/db.py:421`: `RPCBuilder`.
- `core/db.py:444`: `StorageBucket` (MinIO/S3 via boto3).
- `core/security.py:58`: `verify_firebase_jwt`.
- `app/dependencies.py:41,56,84,96`: `get_firebase_claims`, `get_current_user`, `get_optional_user`, `get_api_key`.

**Testing:**
- `tests/test_all_endpoints.py`: ASGI-level route wiring.
- Other `tests/test_*.py`: integration tests requiring `docker compose up -d`.

## Naming Conventions

**Files (Python):**
- `snake_case.py` — all modules.
- One `APIRouter` per area file; the area aggregator is always `router.py` (`app/v1/router.py`, `app/public/router.py`, etc.).

**Routers and modules:**
- Route module file name matches its concern: `documents.py`, `keys.py`, `revisions.py`, `teams.py`, `shares.py`, etc.
- Per-area shared logic lives in `<area>_helpers.py` (e.g. `app/dashboard/team_helpers.py`, `app/v1/document_helpers.py`).

**Functions / variables:**
- `snake_case` for functions and locals.
- `get_*` prefix for FastAPI dependency providers (`get_current_user`, `get_api_key`, `get_admin_client`).
- Private helpers prefixed with `_` (`_extract_bearer`, `_fetch_share`, `_serialize_row`, `_run_async`).

**Types / classes:**
- `PascalCase` for classes (`DatabaseClient`, `QueryBuilder`, `StorageBucket`, `User`, `ApiKeyAuth`).
- Pydantic models end in `Create` / `Update` / `Response` (e.g. `DocumentCreate`, `ApiKeyCreateResponse`); `*Base` for shared DB-row shape (e.g. `ShareBase`).
- `Literal` aliases for enum-like unions: `TeamRole`, `TeamPlan` in `models/team.py`.

**Migrations:**
- `infra/init/`: `NN_<slug>.sql` (2-digit, runs in order).
- `migrations/`: `NNN_<slug>.sql` (3-digit, sequential).
- `supabase/migrations/`: `YYYYMMDD_<slug>.sql` (dated, legacy).

**Tests:**
- `tests/test_<feature>.py`; test functions `test_<behavior>`.

## Where to Add New Code

**New HTTP endpoint (existing area):**
- Add a route handler inside the relevant `app/<area>/<feature>.py` (or create a new file there) and register it via the area's `router.py`.
- Define request/response Pydantic models in `models/<entity>.py` (or inline for one-off DTOs).
- Secure with `Depends(get_current_user)`, `Depends(get_optional_user)`, or `Depends(get_api_key)` from `app/dependencies.py`.
- For team endpoints, reuse `require_team_member` / `resolve_team_by_slug` from `app/dashboard/team_helpers.py`.

**New HTTP endpoint (new area):**
- Create `app/<area>/` with one or more route modules plus a `router.py` aggregator.
- Mount it in `app/main.py` via `app.include_router(<area>_router, prefix="/api/<area>")`.

**New DB query shape / operator:**
- Extend `QueryBuilder` (and `_build_where` / `_parse_select_columns`) in `core/db.py`. Do not emit raw SQL in route handlers.

**New Postgres RPC:**
- Define the function in `infra/init/02_rpc_functions.sql` (for fresh DBs) **and** add a patch under `migrations/NNN_<slug>.sql` (for existing DBs). Reference via `client.rpc("fn_name", {...}).execute()`.

**New schema column / table:**
- Update `infra/init/01_schema.sql` and add a `migrations/NNN_<slug>.sql` patch. Update the matching Pydantic model in `models/`. Check whether the cloud-Supabase path needs mirroring.

**New background task:**
- Add a coroutine in `app/services/` and wire its periodic loop into the app startup (alongside `app/services/cleanup.py`).

**New utility:**
- Add to `core/<concern>.py` (e.g. `core/encryption.py`, `core/extract_text.py`). Keep it framework-agnostic and wrap any I/O for async use.

**New test:**
- ASGI-level wiring → `tests/test_all_endpoints.py`. Integration test against live Postgres/MinIO → `tests/test_<feature>.py`.

## Special Directories

**`infra/init/`:**
- Purpose: Source-of-truth schema + RPCs for a fresh local DB.
- Generated: No (hand-authored SQL).
- Committed: Yes.
- Runs: Automatically on first `docker compose up -d`.

**`migrations/`:**
- Purpose: Incremental patches applied on top of any backend.
- Generated: No (hand-authored).
- Committed: Yes.
- Runs: Via `k8s/migrate-job.yaml` (or manually against any existing DB).

**`supabase/migrations/`:**
- Purpose: Legacy Supabase-cloud schema history.
- Generated: No.
- Committed: Yes (reference only).

**`k8s/`:**
- Purpose: Production-shaped deployment manifests for the local-Postgres/MinIO stack.
- Generated: No.
- Committed: Yes.

**`graphify-out/` and `.planning/graphs/`:**
- Purpose: Codegraph knowledge-system output (compass, wiki, memory). Tooling artifacts.
- Generated: Yes.
- Committed: No (or as the project decides).

**`.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`:**
- Purpose: Local tooling caches.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-08-12*
