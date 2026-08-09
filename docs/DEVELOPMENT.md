<!-- generated-by: gsd-doc-writer -->
# Development

Day-to-day workflow for working on the DropItX API (FastAPI, Python ≥ 3.12). This doc covers environment setup, running and testing the service, project layout conventions, and the patterns every endpoint follows. For coding style (naming, import order, error handling), see [`code-standards.md`](./code-standards.md); for system structure, see [`ARCHITECTURE.md`](./ARCHITECTURE.md); for environment variables, see [`CONFIGURATION.md`](./CONFIGURATION.md).

## Local setup

The API is a stateless FastAPI process over Supabase. To run it locally you need Python 3.12+ and a Supabase project (Auth + Postgres + Storage) to point at.

1. Clone and enter the repo:
   ```bash
   git clone <repo-url> dropitx-api
   cd dropitx-api
   ```
2. Create a virtual environment and install dependencies:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e ".[dev]"   # adds pytest, pytest-asyncio, httpx
   ```
   A reproducible lockfile (`uv.lock`) is committed — `uv sync` is an acceptable alternative to the `pip` steps if you use [uv](https://docs.astral.sh/uv/).
3. Copy `.env.example` to `.env` and fill in real values. Three variables are **required** for startup (`Settings` has no defaults for them; Pydantic raises `ValidationError` at import time if any is missing):
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   Optional knobs (`ALLOWED_ORIGINS`, `FRONTEND_URL`, `ENV`, `LOG_LEVEL`) are documented in [`CONFIGURATION.md`](./CONFIGURATION.md).
4. For readable terminal logs during development, set `ENV=development` (any non-`production` value switches logging from JSON lines to human-readable) and `LOG_LEVEL=DEBUG`.

The Supabase project must have the two storage buckets (`html-files`, `shares`) and the Postgres RPCs listed in [`CONFIGURATION.md` § Required Supabase resources](./CONFIGURATION.md#required-supabase-resources); otherwise authenticated and write endpoints will fail at runtime.

## Dev server

Start the app with Uvicorn auto-reload:

```bash
uvicorn app.main:app --reload
```

The server boots on `http://127.0.0.1:8000`. Interactive API docs are served at `/docs` (Swagger) and `/redoc` (ReDoc) from `app/main.py`. Health probes: `GET /health` (liveness) and `GET /health/deep` (pings the `shares` table through the admin client — will report `degraded` without a reachable Supabase).

`--reload` watches the source tree and restarts on changes; it does not pick up edits to `.env` (restart manually after changing env vars).

## Commands

There is no `Makefile` and no `[project.scripts]` table in `pyproject.toml`; commands are invoked directly.

| Command | Purpose |
| --- | --- |
| `uvicorn app.main:app --reload` | Dev server with auto-reload on file changes. |
| `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | Production-style start (this is the Render start command). |
| `pytest` | Run the full test suite (`testpaths = ["tests"]`). |
| `pytest tests/test_encryption.py -v` | Run a single test file. |
| `pytest -k "test_name" -v` | Run tests matching a name expression. |
| `pytest --tb=short` | Shorter tracebacks (useful when iterating). |
| `pip install -r requirements.txt` | Install runtime dependencies. |
| `pip install -e ".[dev]"` | Editable install with test dependencies. |

## Testing

### Framework and setup

Tests run on **pytest** with **pytest-asyncio** in `asyncio_mode = "auto"` (configured in `pyproject.toml`; `testpaths = ["tests"]`). Async tests therefore run without an explicit `@pytest.mark.asyncio` decorator, although existing tests keep the decorator for clarity. Install the test extras once: `pip install -e ".[dev]"`.

Most endpoint tests do **not** require a live Supabase connection. They drive the FastAPI app in-process via httpx's `ASGITransport`, so there is no port to manage:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
```

Tests that touch Supabase-typed paths assert against the realistic status set (e.g. `assert resp.status_code in (200, 500)`) rather than mocking the client, so the suite passes whether or not Supabase is reachable. Pure-logic tests (e.g. `tests/test_encryption.py` exercises `core/encryption.py` directly with no network) are fully deterministic.

### Writing new tests

- File naming: `tests/test_*.py` (kebab- or snake-case feature name, e.g. `test_file_requests.py`, `test_public_api_validation.py`).
- Group related cases in a `class TestX:` and name methods `test_*`.
- Inject the app client via the `client` fixture shown above; use `FAKE_TOKEN = "Bearer <jwt>"` / `FAKE_API_KEY = "shk_..."` headers to exercise auth-gated paths without real credentials.
- There are no shared `tests/helpers` or `conftest.py` fixtures today — copy the `client` fixture into the new file or add a `tests/conftest.py` if reuse grows.

### Coverage

No coverage threshold is configured (no `.coveragerc`, no `[tool.coverage]` in `pyproject.toml`, no `--cov` flags). The suite is structural: `tests/test_all_endpoints.py` enumerates every public endpoint and asserts reachability and basic response codes, while feature-specific files cover encryption, custom domains, file requests, one-time downloads, preview, and public-API validation.

### CI

No CI workflow is defined in this repository (no `.github/workflows/`, no `.gitlab-ci.yml`). Tests are run locally before push. <!-- VERIFY: if a CI pipeline is added outside this repo (e.g. a Render deploy hook or a pipeline defined in a parent workspace), document the trigger and test command here. -->

## Code style

Style is enforced by **convention**, documented in [`code-standards.md`](./code-standards.md) — there is no automated linter or formatter configured. Specifically, the repository contains **no** Ruff, Black, isort, Flake8, Mypy, Pyright, or `.editorconfig` configuration, and no `lint`/`format`/`typecheck` script.

When contributing, follow `code-standards.md` by hand:

- `from __future__ import annotations` at the top of every module; type all function signatures and return types using Python 3.12 syntax (`str | None`, not `Optional[str]`).
- Kebab- or snake-case file names, one responsibility per file (keep under ~200 LOC).
- Import order: stdlib, third-party, local (`core.*`, `app.*`, `models.*`), blank line between groups.
- Use the `logging` module (never `print`); f-strings only.
- FastAPI patterns: group routes by auth surface, inject auth via `Depends(...)`, raise `HTTPException` with specific codes, wrap every Supabase call in `asyncio.to_thread` (see [Async/sync bridge](#asyncsync-supabase-bridge)).

If you want a local safety net, `python -m compileall app core models` will catch syntax errors, and `pytest` is the effective gate before push.

## Project layout

The codebase is split by **auth surface**, not by domain. Each subpackage under `app/` owns an `APIRouter` and is aggregated in `app/main.py`.

```
app/
├── main.py             App factory: middleware, exception handlers, router mounts, startup task, /health
├── dependencies.py     Auth providers: get_current_user (JWT), get_optional_user, get_api_key, get_client_ip
├── v1/                 API-key-authenticated REST (/api/v1) — documents, keys, revisions
├── dashboard/          JWT-authenticated team management (/api/dashboard) — teams, invites, domains
├── public/             Public / optional-JWT endpoints (/api) — shares, search, analytics, encryption, explore
├── internal/           Authenticated upload/publish/image/download flows (/api)
└── services/           Background workers (cleanup loop)
core/                   HTTP-agnostic infrastructure: config, supabase, security, rate_limit, middleware,
                        exceptions, logging_config, encryption, extract_text, language_detect, nanoid, thumbnail
models/                 Flat package of Pydantic DTOs (share, team, api_key, analytics, domain, file_request)
tests/                  pytest suite (asyncio_mode=auto)
migrations/             Per-feature SQL migration fragments
supabase/               Local Supabase project config + base SQL schema
cli/                    Bundled Node.js CLI (separate npm package) — not part of the Python service
```

**Convention:** route handlers stay thin — they extract auth, call into `core/` helpers and per-feature modules, and return Pydantic models. Persistence logic does not live in `app/`; it is pushed into `core/supabase.py` clients and Postgres RPCs. `core/` has no HTTP imports so it can be unit-tested without spinning up the app.

The four auth surfaces map to four prefixes mounted in `app/main.py`:

| Surface | Prefix | Auth |
| --- | --- | --- |
| `app/v1/router.py` | `/api/v1` | API key (`shk_` / `sht_`) |
| `app/dashboard/router.py` | `/api/dashboard` (plus `invite_actions` at `/api`) | JWT required |
| `app/public/router.py` | `/api` | Public / optional JWT |
| `app/internal/router.py` | `/api` | Optional / required JWT |

## Adding a new endpoint or router

The pattern is consistent across all four surfaces. To add endpoints to an existing feature file (e.g. `app/v1/keys.py`):

1. Define or reuse an `APIRouter` with a `prefix` and `tags` (tags drive the OpenAPI grouping declared in `app/main.py::_tags_metadata`):
   ```python
   from fastapi import APIRouter, Depends, HTTPException
   from app.dependencies import User, get_current_user
   from core.supabase import get_admin_client

   router = APIRouter(prefix="/things", tags=["Things"])
   ```
2. Pick the auth dependency for the surface:
   - `user: User = Depends(get_current_user)` — JWT required.
   - `user: User | None = Depends(get_optional_user)` — optional JWT.
   - `auth: ApiKeyAuth = Depends(get_api_key)` — `shk_`/`sht_` API key.
3. Declare request/response shapes with Pydantic. Inline simple DTOs in the route file; put cross-route DTOs in `models/` and import them. Return them via `response_model=`.
4. Wrap **every** Supabase call in `asyncio.to_thread` with a `lambda` to defer execution, and translate failures into `HTTPException`:
   ```python
   @router.get("", response_model=list[ThingResponse])
   async def list_things(user: User = Depends(get_current_user)) -> list[ThingResponse]:
       client = get_admin_client()
       try:
           resp = await asyncio.to_thread(
               lambda: client.table("things").select("*").eq("user_id", user.id).execute()
           )
       except Exception as exc:
           logger.error("List things failed: %s", exc)
           raise HTTPException(status_code=500, detail="Failed to list things") from exc
       return [ThingResponse(**r) for r in resp.data or []]
   ```

To add a **new** feature file under a surface, create the file with its own `router`, then register it in that surface's `router.py` (which `include_router`s the sub-routers) — the surface router is already mounted in `app/main.py`, so no change to `main.py` is needed for new endpoints within an existing surface. Add a new tag entry to `_tags_metadata` in `app/main.py` if you introduce a new OpenAPI group.

For multi-step storage + DB operations, follow the compensating-transaction pattern in `code-standards.md` § Compensating Transactions: if the DB insert fails after a storage upload, clean up the orphaned object and log the cleanup failure at `warning` level.

## Async/sync Supabase bridge

The Supabase Python client is **synchronous**. Every route handler is `async def`, so any blocking Supabase call (table queries, RPCs, storage upload/download) must be offloaded to a thread:

```python
await asyncio.to_thread(lambda: client.table("shares").insert(data).execute())
```

Always wrap the call in a `lambda` so the Postgrest builder executes inside the thread, not at call time. The same convention applies to JWT verification (`get_current_user` calls `await asyncio.to_thread(verify_supabase_jwt, token)`) and rate-limit checks.

For non-critical side effects (e.g. updating `api_keys.last_used_at`, bumping a view counter), use fire-and-forget tasks and swallow/log failures so they never break the request:

```python
asyncio.create_task(_update_last_used(key_id))
```

This bridge is the single most load-bearing convention in the codebase — see [`ARCHITECTURE.md` § Key abstractions](./ARCHITECTURE.md#key-abstractions) for the full list of Supabase client flavors (`get_admin_client`, `get_user_client`, `get_anon_client`) and where each applies.

## Logging

Logging is configured once at import time in `app/main.py` via `core/logging_config.setup_logging`:

- `ENV=production` (the default) → `JSONFormatter` emits one JSON line per record.
- Any other `ENV` → `ReadableFormatter` for terminal-friendly output.
- `LOG_LEVEL` controls the root level (default `INFO`).

Conventions when adding logs:

- One module logger per file: `logger = logging.getLogger(__name__)`.
- Levels: `error` for failures that break the request, `warning` for best-effort cleanup or rate-limit RPC failures, `debug` for auth failures (to avoid noise).
- Never log secrets, tokens, passwords, or the service-role key.
- A `request_id` is propagated per-request via the `request_id_var` context variable set by `RequestTrackingMiddleware`; it appears automatically in JSON logs and in the `x-response-id` header. Noisy third-party loggers (`httpx`, `httpcore`, `uvicorn.access`, `uvicorn.error`) are forced to `WARNING`.

## Debugging tips

- **Wrong log format locally?** Leaving `ENV` unset defaults to `production`, which produces JSON lines in the terminal. Set `ENV=development` and `LOG_LEVEL=DEBUG` in `.env` for readable, verbose output.
- **App fails to boot?** `Settings` validation runs at import — a missing `SUPABASE_URL`, `SUPABASE_ANON_KEY`, or `SUPABASE_SERVICE_ROLE_KEY` raises `ValidationError` before Uvicorn starts. Re-check `.env`.
- **401 on every authenticated request?** JWTs are verified against the Supabase JWKS cached for 10 minutes in `core/security.py`; an invalid `SUPABASE_URL` or a stale/rotated JWKS will fail verification at `debug` level (enable `LOG_LEVEL=DEBUG` to see the reason).
- **Need to inspect a request end-to-end?** Every response carries `x-request-id`; grep the JSON logs for that ID to see the full structured request line (method, path, status, duration, client IP).
- **Endpoint not appearing in `/docs`?** Confirm the new router is `include_router`'d in its surface's `router.py` (and that the surface router is mounted in `app/main.py`), and that the tag is listed in `_tags_metadata` if you want it grouped.
- **Slow Supabase calls blocking the event loop?** Any blocking call not wrapped in `asyncio.to_thread` will stall all concurrent requests — the bridge convention above is mandatory, not optional.

## Branch conventions and PR process

No branch-naming convention, `CONTRIBUTING.md`, or pull-request template is checked into this repository. Until one is added, keep branches short-lived and named descriptively (e.g. `feat/<thing>`, `fix/<thing>`), keep commits focused with conventional-commit-style messages, and run `pytest` locally before opening a PR. <!-- VERIFY: if a branch/PR policy is introduced (or already enforced via the Render/GitHub project settings), update this section with the real rules. -->

## Related docs

- [`code-standards.md`](./code-standards.md) — coding style, error handling, security standards.
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system overview, component diagram, data flow, key abstractions.
- [`CONFIGURATION.md`](./CONFIGURATION.md) — full environment variable reference, logging, rate limits.
- [`README.md`](../README.md) — project overview and complete API reference.
