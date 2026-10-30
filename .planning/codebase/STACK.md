# Technology Stack

**Analysis Date:** 2026-08-12

## Languages

**Primary:**
- Python 3.12+ (pinned via `requires-python = ">=3.12"` in `pyproject.toml`, `python:3.12-slim` base in `Dockerfile`, `PYTHON_VERSION=3.12.0` in `render.yaml`) — all backend code in `app/`, `core/`, `models/`

**Secondary:**
- SQL — schema (`infra/init/01_schema.sql`, `infra/init/02_rpc_functions.sql`), legacy Supabase migrations (`supabase/migrations/*.sql`), incremental patches (`migrations/*.sql`), k8s auth stub (`k8s/auth-stub.sql`)
- YAML — `docker-compose.yml`, `render.yaml`, `k8s/*.yaml`
- Shell — `k8s/create-secret.sh`, migration Job inline script in `k8s/migrate-job.yaml`
- Node.js — separate `cli/` package (not part of Python build)

## Runtime

**Environment:**
- Python 3.12 runtime; ASGI server is `uvicorn[standard]`
- Containers: `python:3.12-slim` (multi-stage `Dockerfile`); infra containers `postgres:16-alpine`, `minio/minio:latest`, `minio/mc:latest` (`docker-compose.yml`)

**Package Manager:**
- `pip` against `requirements.txt` (authoritative for runtime deps)
- `uv` for reproducible installs (`uv.lock` present); Dockerfile installs via `uv pip install --system`
- Lockfile: `uv.lock` present (committed)

## Frameworks

**Core:**
- FastAPI `>=0.115.0` — HTTP API framework; app instance in `app/main.py`
- Uvicorn `>=0.34.0` (`[standard]` extras) — ASGI server; start cmd `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Pydantic Settings `>=2.7.0` — `core/config.py:Settings(BaseSettings)` loads `.env`
- Starlette — transitive via FastAPI; used directly for `BaseHTTPMiddleware` in `core/middleware.py`

**Testing:**
- pytest `>=8.0` (dev extra in `pyproject.toml`)
- pytest-asyncio `>=0.24` — `asyncio_mode = "auto"` in `pyproject.toml`
- httpx `>=0.28.0` — used both as runtime HTTP client and as ASGI test transport in `tests/test_all_endpoints.py`

**Build/Dev:**
- setuptools `>=75.0` (`pyproject.toml` build backend, packages `app*`, `core*`, `models*`)
- Docker (multi-stage build, `Dockerfile`)
- Docker Compose (`docker-compose.yml`) for local Postgres + MinIO + bucket bootstrap
- Kubernetes manifests in `k8s/` (newer deployment path)

## Key Dependencies

**Critical:**
- `asyncpg>=0.30.0` — async Postgres driver; pooled in `core/db.py` (`min_size=2, max_size=10, command_timeout=30`), driven from a dedicated background event loop thread so sync `execute()` works inside `asyncio.to_thread()` callers
- `boto3>=1.35.0` — S3/MinIO object storage client, lazily constructed per-call in `core/db.py:StorageBucket._client()` (`signature_version="s3v4"`, `region_name="us-east-1"`)
- `python-jose[cryptography]>=3.3.0` — Firebase ID token (RS256 JWT) verification in `core/security.py:verify_firebase_jwt`
- `bcrypt>=4.2.0` — password hashing (12 rounds) in `core/security.py`
- `cryptography>=42.0.0` — AES-256-GCM E2E encryption + PBKDF2-SHA256 key derivation in `core/encryption.py`
- `httpx>=0.28.0` — fetches Firebase public x509 certs (`core/security.py:_fetch_firebase_certs`)
- `python-multipart>=0.0.18` — `UploadFile`/`Form` parsing for upload/image/publish endpoints

**Infrastructure:**
- `qrcode[pil]>=8.0` — share QR code generation (`app/public/qrcode.py`)
- `Pillow` (via `qrcode[pil]`) — thumbnail generation (`core/thumbnail.py:from PIL import Image`)
- `dnspython>=2.6.0` — custom domain DNS verification (`app/dashboard/domains.py:dns.resolver`)
- `psycopg2-binary>=2.9.0` — installed in Docker image only (used by ad-hoc psql/ops, not imported by the app)

**Dev-only (`[project.optional-dependencies].dev`):**
- `pytest>=8.0`, `pytest-asyncio>=0.24`, `httpx>=0.28.0`

## Configuration

**Environment:**
- Pydantic `BaseSettings` in `core/config.py` — reads `.env` (`env_file_encoding="utf-8"`, `extra="ignore"`)
- Single global singleton: `settings = Settings()` at module import
- `.env.example` — Supabase-cloud baseline; `.env.local.example` — local Postgres+MinIO baseline; `.env` present but contents not loaded into this doc (secrets)

**Key config fields (`core/config.py:Settings`):**
- `firebase_project_id: str` — REQUIRED for auth (verified in `verify_firebase_jwt`); empty string default
- `supabase_url: str` — LEGACY, used ONLY to build public storage object URLs (upload/publish/images/preview/thumbnail/oembed), NOT for auth or data
- `database_url: str` — local Postgres DSN, default `postgresql://dropitx:dropitx_local_dev@localhost:5432/dropitx`
- `s3_endpoint`/`s3_access_key`/`s3_secret_key` — MinIO/S3 connection (defaults match `docker-compose.yml`)
- `allowed_origins: str` — CSV CORS list or `"*"`; parsed by `Settings.cors_origins`
- `frontend_url: str` — used in invite links and oEmbed responses

**Build:**
- `pyproject.toml` — build backend, runtime + dev deps, pytest config (`testpaths=["tests"]`, `asyncio_mode="auto"`)
- `requirements.txt` — pip manifest (adds `qrcode[pil]`, `dnspython`, `asyncpg`, `boto3` beyond `pyproject.toml`'s list)
- `Dockerfile` — multi-stage: builder installs `gcc libpq-dev` + `uv`; runtime carries only `libpq5`
- `docker-compose.yml` — Postgres 16, MinIO, `createbuckets` init service (creates `html-files` + `shares` buckets, sets anonymous download)
- `render.yaml` — Render blueprint (`python` runtime, free plan)
- `k8s/*.yaml` — `namespace`, `postgres`, `minio`, `api` (Deployment+Service NodePort 30080), `migrate-job`; `k8s/create-secret.sh` builds the `dropitx-env` Secret from `.env`

## Platform Requirements

**Development:**
- Python 3.12+, Docker (for `docker compose up -d` Postgres+MinIO), optional `uv` for lockfile-driven installs
- Local infra defaults: Postgres on `:5432`, MinIO on `:9000` (S3 API) + `:9001` (console)
- Firebase project required even for local dev (FIREBASE_PROJECT_ID); auth verification hits `googleapis.com` for signing certs

**Production:**
- Render (`render.yaml`) — `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; predates local-Postgres migration, assumes cloud Supabase unless `DATABASE_URL`/`S3_*` overridden
- Kubernetes (`k8s/`) — actively-developed path; Postgres + MinIO deployed in-namespace (`postgresql.dropitx.svc`, `minio.dropitx.svc`); API exposed as NodePort 30080; migrations run via `migrate-db` Job
- Every deployment target requires Firebase Auth reachability (outbound to `www.googleapis.com` and `securetoken.google.com`)

---

*Stack analysis: 2026-08-12*
