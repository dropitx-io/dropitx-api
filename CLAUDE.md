# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DropItX API — a FastAPI backend for file/text sharing with team collaboration. Users upload HTML/Markdown content, share it via public URLs, and collaborate in teams.

**Backend is hybrid, mid-migration off Supabase cloud (see `7b7b8c3`):**
- **Data + Storage** — local PostgreSQL + MinIO, accessed through a hand-rolled PostgREST-compatible shim (`core/db.py`). No live Supabase project needed for these.
- **Auth** — Firebase ID token verification via `core/security.py`'s `verify_firebase_jwt`: RS256 signature checks against Google's rotating public x509 certs plus `aud`/`iss` claims for the configured `FIREBASE_PROJECT_ID`.

## Commands

```bash
# Start local infra (Postgres + MinIO), applies infra/init/*.sql on first boot
docker compose up -d

# Run dev server
uvicorn app.main:app --reload

# Run tests
pytest
pytest tests/test_foo.py -v        # single test file
pytest -k "test_name" -v           # single test by name

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"            # with test deps
```

`uv.lock` is present for reproducible installs; use `pip` or `uv` as preferred. `tests/test_all_endpoints.py` exercises route wiring/response codes over ASGI transport without a live DB; other test files hit a real local Postgres/MinIO (`docker compose up -d` first).

## Architecture

### API Routes

For a comprehensive API reference (90+ endpoints across health, documents, keys, teams, invites, uploads, shares, search, analytics, encryption, profiles, file requests, and more), see **[README.md § API Reference](./README.md#api-reference)**. Key authentication patterns:

- **API Key (`shk_` / `sht_` prefix)** — `/api/v1/documents` and `/api/v1/keys`
- **JWT (Firebase Auth)** — `/api/dashboard/*`, `/api/invite/*`, `/api/upload`, `/api/publish`, `/api/images/upload`, `/api/v1/keys`
- **Optional JWT** — `/api/upload` (associates file with user if authenticated)
- **Public (no auth)** — `/api/search`, `/api/analytics/track`, `/api/oembed`, `/api/shares/{slug}/content`, `/api/explore`, `/api/profiles/{handle}`

### Key modules

- **`core/db.py`** — PostgREST-compatible shim over `asyncpg`: `.table().select/insert/update/delete()`, `.rpc()`, `.storage.from_()` (MinIO/S3 via `boto3`). Runs its own background event loop thread so sync `execute()` calls work from `asyncio.to_thread()`. Handles nested-select JOIN parsing (`"*, teams(id,name)"`) and PostgREST-style filter operators (`eq`, `is_`, `in_`, etc.) — extend here when a route needs a new query shape, not by reaching for raw SQL in the route.
- **`core/supabase.py`** — thin re-export of `get_admin_client`/`get_anon_client`/`get_user_client` from `core/db.py`. All three currently return the same `DatabaseClient` singleton; local dev has no RLS/anon distinction, so authorization is enforced at the app layer (explicit `user_id`/role checks in routes), not by which client you grab.
- **`core/security.py`** — Firebase ID token and session cookie verification (`verify_firebase_jwt`: RS256 against the x509 cert set chosen by the token's `iss`, one `_CERTS_TTL` 1-hour cache per set with a refetch on `kid` miss), API key hashing, password hashing
- **`core/config.py`** — `Settings` (Pydantic BaseSettings): `firebase_project_id` (auth, required), `database_url` (Postgres), `s3_endpoint`/`s3_access_key`/`s3_secret_key` (MinIO), plus `storage_public_url` (browser-facing base URL of the object store, used by `core.db.public_object_url`)
- **`core/`** (rest) — text extraction, slug/token generation (`nanoid.py`), rate limiting, encryption (AES-256-GCM), exception definitions, structured logging, middleware, language detection, thumbnail generation
- **`app/dependencies.py`** — Auth providers: `get_current_user` (JWT), `get_optional_user`, `get_api_key` (shk_/sht_ validation), `get_client_ip`
- **`app/main.py`** — Router registration, health endpoints (`/health`, `/health/deep`), exception handlers, startup tasks (background cleanup)
- **`models/`** — Pydantic DTOs for shares, teams, API keys, analytics, domains, file requests
- **`app/v1/`** — API-key-authenticated document CRUD endpoints (`/api/v1/documents`, `/api/v1/keys`)
- **`app/dashboard/`** — JWT-authenticated team management. `team_helpers.py` centralizes role checks; `team_invites.py` registers its routes via `teams.py`
- **`app/public/`** — Public endpoints: shares, search, analytics, oEmbed, profiles, galleries, comments, encryption, previews, QR codes, versions
- **`app/internal/`** — Authenticated upload/publish/image endpoints, plus file requests and downloads
- **`app/services/`** — Background tasks (cleanup of expired shares and file request uploads)

### Schema / migrations — three directories, different roles

- **`infra/init/`** — `01_schema.sql`, `02_rpc_functions.sql`, `03_analytics.sql` (applied in lexical order), mounted into the local Postgres container's `docker-entrypoint-initdb.d`. This is the source of truth for a fresh local DB and runs automatically on first `docker compose up -d`.
- **`supabase/migrations/`** — the original Supabase-cloud schema history (base schema + feature migrations), from before the local-Postgres migration.
- **`migrations/`** — later incremental SQL patches (encryption columns, burn-after-reading, revisions, custom domains, etc.) layered on top of either backend.
- When adding a schema change: update `infra/init/` (or add a new file there) for local dev, and check whether it also needs mirroring for the Supabase-cloud path (Auth still lives there).
- **`k8s/`** — Kubernetes manifests for the local-Postgres/MinIO stack, including `auth-stub.sql` which stubs `auth.users`/`auth.uid()`/`auth.role()` on vanilla Postgres so migrations written for Supabase (which reference `auth.*`) still apply.

### Patterns

- **Async/sync bridge** — All DB/Storage calls wrapped in `asyncio.to_thread()`; `core/db.py`'s shim itself runs a dedicated background event loop thread to serve `asyncpg` from that sync context
- **Structured logging** — JSON format in production (`ENV=production`), human-readable in dev. Request ID tracking via `core.logging_config`
- **Exception handling** — Custom exceptions in `core.exceptions` (RateLimitError, ShareNotFoundError, SharePasswordRequired) with global error handlers in `app/main.py`
- **Rate limiting** — Delegates to Postgres RPC `check_rate_limit` with configurable fail-open/fail-closed behavior (per-IP bucketing)
- **Compensating transactions** — If DB insert fails after storage upload, cleanup is triggered to remove orphaned files
- **Role hierarchy** — `owner (3) > editor (2) > viewer (1)` for team permissions (checked via `team_helpers.py`)
- **API keys** — `shk_` (personal), `sht_` (team) prefixes. Stored as SHA-256 hashes; raw key returned once at creation. Last-used timestamp tracked (fire-and-forget async update)
- **Encryption (E2E)** — AES-256-GCM with PBKDF2 key derivation. Shares can be password-protected; passwords unlock but do not grant modification rights
- **Storage buckets** — `html-files` (upload/publish flows), `shares` (v1 API documents) — created automatically by the `createbuckets` service in `docker-compose.yml`. Both are private: only `html-files/public/` allows anonymous download, and only public assets (editor images under `public/uploads/`, thumbnails under `public/thumbnails/`) are stored there and linked by URL. Share content is served by the API, and responses link to the share page (`{FRONTEND_URL}/s/{slug}`), never to a storage URL
- **Background cleanup** — Periodically (5-min interval) deletes expired file request uploads and old share revisions to conserve storage

## Deployment

- **Render**: `render.yaml` blueprint — `python` runtime, `pip install -r requirements.txt` build, `uvicorn app.main:app --host 0.0.0.0 --port $PORT` start command. This path assumes cloud Supabase for data+storage too (predates the local-Postgres migration) — verify `core/db.py`'s `database_url`/`s3_*` settings are reachable from Render before relying on it.
- **Kubernetes**: `k8s/` manifests deploy the local-Postgres/MinIO stack (`namespace.yaml`, `postgres.yaml`, `minio.yaml`, `api.yaml`, `migrate-job.yaml`, `create-secret.sh`) — the newer, actively-developed deployment path.
- **Python**: 3.12+ required (pinned in `render.yaml` and `pyproject.toml`)
- **Auth dependency**: Firebase project credentials (`FIREBASE_PROJECT_ID`) are required in every deployment target

## Environment Variables

Required in `.env` (see `.env.example` for the Supabase-cloud baseline, `.env.local.example` for the local Postgres+MinIO stack):
- `FIREBASE_PROJECT_ID` — Firebase project ID (auth, required); verifies the `aud`/`iss` claims of incoming ID tokens
- `STORAGE_PUBLIC_URL` — browser-facing base URL of the object store (default `http://localhost:9000`); public asset URLs are `{STORAGE_PUBLIC_URL}/{bucket}/{key}`
- `DATABASE_URL` — local Postgres connection string (default `postgresql://dropitx:dropitx_local_dev@localhost:5432/dropitx`)
- `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` — MinIO connection (defaults match `docker-compose.yml`)
- `ALLOWED_ORIGINS` — Comma-separated CORS origins
- `FRONTEND_URL` — Frontend base URL (used in invite links, oEmbed responses)

## Other subprojects in this repo

- **`cli/`** — a separate Node.js CLI (`dropitx` npm package) for the same API. Has its own `package.json`/tests; not part of the Python build.
