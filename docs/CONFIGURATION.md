<!-- generated-by: gsd-doc-writer -->

# Configuration

All runtime configuration for the DropItX API is supplied via environment variables. There is no YAML/TOML application config file — settings are loaded once at startup by Pydantic `BaseSettings` in [`core/config.py`](../core/config.py), with logging knobs read directly from the environment in [`app/main.py`](../app/main.py). Production deployment uses [Render](../render.yaml); local development uses a `.env` file.

> Secret values (Supabase keys) are never committed. Reference them by env var name only and set them in your Render dashboard or local `.env`.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | **Yes** | — | Supabase project URL (e.g. `https://<project>.supabase.co`). Used for Postgres, Storage public URLs, and the JWKS endpoint (`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`). |
| `SUPABASE_ANON_KEY` | **Yes** | — | Supabase anon/public key. Used by the base client (`core/supabase.py`) for user-context and anonymous calls where Row-Level Security applies. |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes** | — | Supabase service-role key. Bypasses RLS. Used by `get_admin_client()` for internal/admin operations. Keep secret. |
| `ALLOWED_ORIGINS` | No | `http://localhost:3000` | Comma-separated CORS origins (e.g. `http://localhost:3000,https://yourdomain.com`). The literal `*` disables credentials and allows all origins. |
| `FRONTEND_URL` | No | `http://localhost:3000` | Frontend base URL. Used to build share (`/s/`), group (`/g/`), request (`/r/`), and invite (`/invite/`) links returned by the API. |
| `ENV` | No | `production` | Environment label. Controls log format only: `production` → JSON lines, anything else → human-readable. Read via `os.getenv` in `app/main.py`. |
| `LOG_LEVEL` | No | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Read via `os.getenv` in `app/main.py`. |

Additional variables injected by Render (defined in [`render.yaml`](../render.yaml)):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PYTHON_VERSION` | No | `3.12.0` | Python runtime version for the Render web service. `pyproject.toml` requires `>=3.12`. |
| `PORT` | No | Render-injected | Port the web service binds to (`uvicorn ... --port $PORT`). Set automatically by Render. |

<!-- VERIFY: actual production values for SUPABASE_URL, ALLOWED_ORIGINS, and FRONTEND_URL are stored in the Render dashboard, not in the repository. -->

## Config file format

Settings are declared as a Pydantic `BaseSettings` subclass in [`core/config.py`](../core/config.py):

```python
class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    allowed_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

Loading behavior:

- A single `settings = Settings()` instance is constructed at import time and reused process-wide.
- `model_config.env_file = ".env"` — values are read from a `.env` file in the current working directory (UTF-8). Environment variables take precedence over `.env` values, which is how Render's injected env vars override the file on deploy.
- Field names map to upper-snake env vars automatically (`supabase_url` → `SUPABASE_URL`).
- `cors_origins` is a computed property (`settings.cors_origins`) that splits `ALLOWED_ORIGINS` on commas and strips whitespace; `*` short-circuits to `["*"]`.

Local `.env` template (matches `.env.example`):

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
FRONTEND_URL=http://localhost:3000
```

The `.env` file is gitignored (see `.gitignore`); copy `.env.example` to `.env` and fill in real values.

## Required vs. optional settings

**Required (startup fails if missing):** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.

These are declared without defaults in `Settings`, so Pydantic raises `ValidationError` at import time if any is absent — the app will not boot. When running locally, copy `.env.example` to `.env` and supply real values. On Render, set all three in the service dashboard (the keys are declared with `sync: false` in `render.yaml`, meaning Render holds them as encrypted env vars rather than deriving them from the blueprint).

**Optional (have defaults):** `ALLOWED_ORIGINS`, `FRONTEND_URL`, `ENV`, `LOG_LEVEL`, `PORT`. The app starts with their defaults if unset.

## Defaults

| Variable | Default | Source |
|----------|---------|--------|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | `core/config.py` (`Settings.allowed_origins`) |
| `FRONTEND_URL` | `http://localhost:3000` | `core/config.py` (`Settings.frontend_url`) |
| `ENV` | `production` | `app/main.py` (`os.getenv("ENV", "production")`) |
| `LOG_LEVEL` | `INFO` | `app/main.py` (`os.getenv("LOG_LEVEL", "INFO")`) |
| `PYTHON_VERSION` | `3.12.0` | `render.yaml` |

Note the implication for local dev: leaving `ENV` unset means JSON logs, which is noisy for terminal use. Set `ENV=development` (or any non-`production` value) in your local `.env` for readable logs.

## Per-environment overrides

There is no `.env.development` / `.env.production` / `.env.test` scheme — Pydantic `BaseSettings` reads a single `.env` file. Environments are differentiated by where the variables live:

- **Local development** — populate `.env` in the project root. Override `ENV=development` and `LOG_LEVEL=DEBUG` for readable, verbose logs. Point `ALLOWED_ORIGINS` and `FRONTEND_URL` at your local frontend (default `http://localhost:3000`).
- **Test** — no dedicated test config. `pytest` (configured in `pyproject.toml` with `asyncio_mode = "auto"`, `testpaths = ["tests"]`) inherits whatever environment the test runner sees. Tests that need Supabase should set the required env vars before invoking pytest.
- **Production (Render)** — set all five core variables (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`) plus `ENV`/`LOG_LEVEL` in the Render service dashboard. Environment variables injected by Render take precedence over any `.env` file. `ENV=production` (the default) enables JSON-structured logging for observability.

<!-- VERIFY: production ALLOWED_ORIGINS and FRONTEND_URL values, plus the exact Render service ID and dashboard URL, are not in the repository. Set/verify them in the Render dashboard. -->

## CORS configuration

CORS is applied in [`app/main.py`](../app/main.py) via `fastapi.middleware.cors.CORSMiddleware`, driven by `settings.cors_origins`:

- `ALLOWED_ORIGINS` is a comma-separated list parsed into `cors_origins` by `core/config.py`.
- If `ALLOWED_ORIGINS == "*"`, the middleware allows all origins **and** disables credentials (`allow_credentials=False`).
- Otherwise, only the listed origins are allowed and `allow_credentials=True`. Methods and headers are unrestricted (`["*"]`).

## Logging

Configured by [`core/logging_config.py`](../core/logging_config.py) at import time in `app/main.py`:

- `ENV=production` → `JSONFormatter` emits one JSON line per record (timestamp, level, logger, message, module, function, line, optional `request_id`, plus extras like `status_code`/`method`/`path`/`duration_ms`/`client_ip`).
- Any other `ENV` → `ReadableFormatter` for terminal-friendly output.
- `request_id` is propagated per-request by `RequestTrackingMiddleware` (`core/middleware.py`) via the `request_id_var` context variable.
- Noisy third-party loggers (`httpx`, `httpcore`, `uvicorn.access`, `uvicorn.error`) are forced to `WARNING`.

## Supabase client configuration

[`core/supabase.py`](../core/supabase.py) builds three client types from `settings` — there are no per-client env vars beyond the three Supabase keys:

- `get_user_client(access_token)` — base client (anon key) with `postgrest.auth(token)` applied per request; RLS enforces.
- `get_admin_client()` — new client created with `SUPABASE_SERVICE_ROLE_KEY`; bypasses RLS. Used by most routes and by the rate limiter.
- `get_anon_client()` — the cached base client (anon key, no user context) for public endpoints.

JWT verification (`core/security.py::verify_supabase_jwt`) fetches and caches the JWKS from `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` for 10 minutes (`_JWKS_TTL = 600`) and supports both `RS256` and `ES256` algorithms. No env var controls this — it is derived from `SUPABASE_URL`.

## Rate limiting

Rate limits are **not** env-driven. They are hardcoded constants in [`core/rate_limit.py`](../core/rate_limit.py) and enforced by the Supabase Postgres RPC `check_rate_limit`:

| Bucket | Limit | Window | Fail mode |
|--------|-------|--------|-----------|
| Upload (`upload:<ip>`) | 10 | 60s | Open |
| Password unlock (`pwd:<ip>:<slug>`) | 5 | 600s | Closed |
| oEmbed (`oembed:<ip>`) | 60 | 60s | Open |
| Analytics (`analytics:<ip>`) | 60 | 60s | Open |

To change a limit, edit `core/rate_limit.py` (no env override exists).

## Required Supabase resources

The following must exist in the configured Supabase project for the API to function (not env vars — part of project configuration, documented in [`README.md`](../README.md) and `CLAUDE.md`):

- **Storage buckets:** `html-files` (upload/publish flows), `shares` (v1 API documents).
- **Postgres RPCs:** `check_rate_limit`, `search_shares`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`, `increment_share_views`.

<!-- VERIFY: bucket names, RPC names, and any RLS policy details live in the Supabase project (see supabase/ migrations), not in env vars. Confirm against the deployed Supabase project dashboard. -->

## Runtime requirements

- **Python:** `>=3.12` (declared in [`pyproject.toml`](../pyproject.toml)); Render pins `3.12.0`.
- **Dependencies:** see [`requirements.txt`](../requirements.txt) (`fastapi`, `uvicorn[standard]`, `supabase`, `pydantic-settings`, `python-jose[cryptography]`, `bcrypt`, `python-multipart`, `httpx`, `qrcode[pil]`, `cryptography`, `dnspython`). A reproducible lockfile is available in `uv.lock`.
- **Start command (Render):** `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (from [`render.yaml`](../render.yaml)).
