# Coding Conventions

**Analysis Date:** 2026-08-12

## Naming Patterns

**Files:**
- `snake_case.py` throughout `app/`, `core/`, `models/`. One module per resource/feature — e.g. `app/internal/file_requests.py`, `app/public/oembed.py`, `core/rate_limit.py`.
- Group routers as `router.py` inside each subpackage (`app/v1/router.py`, `app/public/router.py`, `app/internal/router.py`, `app/auth/router.py`) that aggregates the feature sub-routers.
- Feature subpackages live under a top-level domain prefix: `app/public/` (no-auth endpoints), `app/internal/` (JWT-authenticated), `app/dashboard/` (team management, JWT), `app/v1/` (API-key-authenticated document CRUD), `app/auth/` (Firebase session), `app/services/` (background tasks).
- Cross-cutting infra lives in `core/` (`core/db.py`, `core/security.py`, `core/config.py`, `core/middleware.py`, `core/logging_config.py`, `core/exceptions.py`, `core/encryption.py`, `core/rate_limit.py`, `core/nanoid.py`).
- Pydantic DTOs live in `models/<entity>.py` (`models/share.py`, `models/team.py`, `models/api_key.py`, `models/file_request.py`, `models/analytics.py`, `models/domain.py`).

**Functions:**
- `snake_case` for all functions and methods: `get_current_user`, `generate_slug`, `verify_firebase_jwt`, `check_upload_rate_limit`.
- Route handlers are named after the verb: `get_session`, `health_check`, `create_file_request`, `list_documents`.
- Async functions are the default for route handlers and anything touching the DB/storage: `async def get_session(...)`. Sync helpers run via `asyncio.to_thread(...)` (see `app/auth/session.py:42`, `app/dependencies.py:60`).
- Private helpers prefixed with underscore: `_extract_bearer`, `_fetch_firebase_certs`, `_check_rpc`, `_get_pool`, `_run_async`.

**Variables:**
- `snake_case` for locals and module-level constants.
- Module-level constants in `UPPER_SNAKE`: `_FIREBASE_CERTS_URL`, `_CERTS_TTL`, `_VALID_PREFIXES`, `_ALLOWED_TYPES`, `_STORAGE_BUCKET`. Private constants are prefixed with `_` (`_STORAGE_BUCKET`, `_EXT_MAP`).

**Types:**
- Pydantic models are `PascalCase`: `ShareCreate`, `ShareResponse`, `SessionProfile`, `DocumentUpdate`, `RateLimitResult`.
- Pydantic models use `BaseModel`; settings use `pydantic_settings.BaseSettings` (see `core/config.py:4`).
- Frozen dataclasses for value-object auth identities: `@dataclass(frozen=True) class User`, `class ApiKeyAuth` in `app/dependencies.py:21`.
- Exception classes are `PascalCase` and inherit from `Exception`: `RateLimitError`, `ShareNotFoundError`, `SharePasswordRequired` (`core/exceptions.py`).

## Code Style

**Formatting:**
- No formatter config committed (no `.style.yapf`, `pyproject.toml` has no `[tool.black]`/`[tool.isort]`/`[tool.ruff]` section). Match surrounding style by hand: 4-space indent, line width ~100–110, double quotes for strings, trailing commas in multi-line collections.
- All modules begin with `from __future__ import annotations` (consistent across `app/auth/session.py`, `app/dependencies.py`, `core/security.py`, `core/db.py`, `app/v1/documents.py`, etc.) so type hints can use the `X | None` syntax on Python 3.12+.
- Use modern union syntax `str | None`, `dict[str, Any]`, `list[str]` everywhere — not `Optional[str]` / `Dict[str, Any]`.

**Linting:**
- No linter config committed (no `.flake8`, `.ruff.toml`, `.pylintrc`, `mypy.ini`). Treat the existing style as the de-facto baseline; do not introduce a linter in a surgical change.
- `requires-python = ">=3.12"` is enforced in `pyproject.toml`; rely on 3.12+ syntax (PEP 604 unions, PEP 585 generics, `type` aliases).

## Import Organization

**Order** (observed in every module — keep this exact grouping):
1. `from __future__ import annotations` (always first when present).
2. Standard library (`asyncio`, `logging`, `hashlib`, `datetime`, `time`, `uuid`, `dataclasses`, `typing`).
3. Third-party (`fastapi`, `pydantic`, `pydantic_settings`, `jose`, `bcrypt`, `asyncpg`, `httpx`, `boto3`).
4. Local app code (`from app.dependencies import ...`, `from core.config import settings`, `from core.supabase import get_admin_client`, `from models.share import ...`).

**Path Aliases:**
- None. Always use absolute imports rooted at the package: `from app.main import app`, `from core.security import verify_firebase_jwt`, `from app.dependencies import get_current_user`. Do not use relative imports like `..core`.

**Within-group order:** standard lib → third-party → local, alphabetical inside each group (see `app/internal/upload.py:1-19` for the canonical example).

## Error Handling

**Patterns:**
- Raise `fastapi.HTTPException` with explicit `status_code` and `detail` for all client-visible failures inside route handlers and dependencies. Re-raise with `from exc` to preserve the cause:
  ```python
  raise HTTPException(status_code=500, detail="Provisioning failed") from exc
  ```
  (See `app/auth/session.py:51`, `app/v1/documents.py:143`, `app/dependencies.py:53`.)
- Auth failures are centralized in `app/dependencies.py`: `get_firebase_claims`, `get_current_user`, `get_optional_user`, `get_api_key`. They raise `HTTPException(401)`. Do not duplicate JWT/API-key validation in route bodies — depend on these.
- `get_current_user` distinguishes "invalid token" (401) from "DB lookup failure" (500) from "user not provisioned" (401 with a structured `detail={"code": "user_not_provisioned", ...}`) — see `app/dependencies.py:67-78`. When adding new auth states, follow this structured-detail shape.
- Sync DB/storage calls are wrapped in `asyncio.to_thread(...)` and the surrounding `try/except Exception` logs `logger.error(..., exc)` then raises `HTTPException(500, "Failed to <action>")`. See `app/v1/documents.py:140-144`, `app/auth/session.py:46-52`.
- Fire-and-forget background work uses `asyncio.create_task(...)` and the task's own except handler logs — do NOT await it on the request path. Example: last-used API-key update at `app/dependencies.py` (`_update_last_used`).
- Storage cleanup on partial failure is a compensating transaction: if the DB insert fails after a storage upload, log `logger.warning("Storage removal failed for %s: %s", ...)` and continue — do not mask the original error. See `app/v1/documents.py:341`.
- Custom domain exceptions (`core/exceptions.py`: `RateLimitError`, `ShareNotFoundError`, `SharePasswordRequired`) are for mid-stack signaling; route handlers translate them into HTTP responses.
- Uniform error envelope `ErrorResponse` (`core/exceptions.py`) is the model for error responses: `error`, `detail`, `request_id`.

## Logging

**Framework:** Python stdlib `logging` (no third-party logger).

**Patterns:**
- One module-level logger per file: `logger = logging.getLogger(__name__)`. Seen in `app/auth/session.py:15`, `app/dependencies.py:14`, `core/middleware.py:12`, `core/db.py:18`, `core/rate_limit.py:9`, `app/v1/documents.py`, `app/v1/revisions.py`.
- Lazy %-formatting only — never f-strings in log calls: `logger.error("User lookup failed for %s: %s", uid, exc)` (`app/dependencies.py:71`). This is consistent everywhere.
- Levels: `logger.debug` for expected auth failures (`app/dependencies.py:52`), `logger.info` for successful state changes (`app/v1/revisions.py:65`), `logger.warning` for non-fatal downstream failures (`app/v1/documents.py:193,341`), `logger.error` with `exc_info=True` for unexpected exceptions (`core/middleware.py:33`).
- Structured fields are attached via `extra={...}` for fields consumed by `JSONFormatter`: `method`, `path`, `status_code`, `duration_ms`, `client_ip` (`core/middleware.py:53-59`). Only these keys are emitted as top-level JSON fields — extend `JSONFormatter.EXTRA_KEYS` (the loop in `core/logging_config.py`) when adding a new structured field.
- Request IDs: `request_id_var: ContextVar[str]` (`core/logging_config.py`) is set per-request by `RequestTrackingMiddleware` and auto-attached to every log line. Echoed back as `x-request-id` response header.
- Production = JSON lines (`JSONFormatter`), dev = human-readable (`ReadableFormatter`); toggled by `ENV=production` (see `setup_logging`).

## Comments

**When to Comment:**
- The user's global rule applies: comments explain WHY, never WHAT. The codebase mostly obeys — most files have zero inline comments and rely on naming + structure.
- Section dividers in test files and large modules use `# ---------------------------------------------------------------------------` blocks under a heading (e.g. `tests/test_all_endpoints.py`, `app/dependencies.py`, `core/security.py`, `models/share.py`). Follow this existing convention when adding a major new section.
- WHY comments are tolerated for non-obvious business rules: API-key prefix semantics (`shk_` personal vs `sht_` team in `core/security.py`), the background-event-loop bridge rationale (`core/db.py:9-13`), PostgREST shim limitations.

**JSDoc/TSDoc:**
- Module docstrings are mandatory and substantive — every module starts with a `"""..."""` explaining what the module does and any critical constraint. Examples: `core/db.py:1-15` (explains the sync/async bridge), `core/security.py:1` (JWT + API key utilities), `tests/test_all_endpoints.py:1-58` (enumerates every endpoint under test with its auth mode).
- Function docstrings are reserved for non-obvious public helpers and configuration helpers (`setup_logging`, `Settings.cors_origins`, `verify_firebase_jwt`). Most route handlers and trivial helpers are undocumented — name clarity is preferred.
- When adding a docstring, use triple-double-quotes, imperative voice, and one blank line after.

## Function Design

**Size:** Route handlers stay small — extraction of SQL chains and business logic goes into `*_helpers.py` modules (`app/dashboard/team_helpers.py`, `app/v1/document_helpers.py`). Prefer a thin handler that calls a helper over a 200-line handler.

**Parameters:**
- Route handlers take FastAPI `Depends(...)` for auth (`claims: dict = Depends(get_firebase_claims)`, `user: User = Depends(get_current_user)`) and `Request` only when reading headers/IP directly.
- Pydantic models for request bodies; `Query(...)`/`Form(...)` for scalar query/form params; `UploadFile` for multipart.
- Helpers take primitive values (slugs, ids, client objects) — do not thread `Request` into helpers.

**Return Values:**
- Route handlers return Pydantic response models (`-> SessionProfile`, `-> DocumentResponse`) or plain `dict`. Annotated return types are the norm; keep annotating.
- DB access returns the raw PostgREST-shim result (`resp.data` — a list of dicts); routes then shape the dict into the response model.

## Module Design

**Exports:**
- No `__all__` declarations. Modules export via plain `def`/`class`. Import only what you need by name.
- Each feature module exposes a single `router = APIRouter(...)` that its parent `router.py` aggregates. The top-level `app/main.py` mounts five routers under prefixes: `/api/v1`, `/api/dashboard`, `/api` (invite actions), `/api` (public), `/api` (internal), `/api/auth`.

**Barrel Files:**
- Each subpackage has an `__init__.py` that is empty (a marker only). Do not turn `__init__.py` into a re-export barrel — import from the concrete module (`from app.public.shares import router`, not `from app.public import shares`).
- `core/supabase.py` is the one explicit re-export shim: it forwards `get_admin_client`/`get_anon_client`/`get_user_client` from `core/db.py`. Routes and services import from `core.supabase`, not directly from `core.db`.

**Async/Sync Bridge (load-bearing convention):**
- `core/db.py` exposes a synchronous fluent API (`.table().select().eq().execute()`) that internally runs `asyncpg` on a dedicated background event loop (`_start_background_loop`, `_run_async`).
- Therefore every call site MUST wrap the synchronous shim in `asyncio.to_thread(...)` so the background loop is not blocked from the main asyncio loop. Pattern:
  ```python
  resp = await asyncio.to_thread(
      lambda: client.table("auth.users").select("id, email").eq("id", uid).execute()
  )
  ```
  See `app/dependencies.py:60-63`, `app/auth/session.py:42-48`, `app/v1/documents.py`.
- Do not call the shim directly inside an `async def` without `to_thread` — it will block the event loop.

**Settings access:**
- Read config via the singleton `from core.config import settings` — never instantiate `Settings()` twice and never read `os.environ` directly. New config keys are added as annotated attributes on `Settings` with a sensible default.

**PostgREST shim extension rule:**
- When a route needs a new query shape (new filter operator, nested-select join, RPC), extend `core/db.py` (the `DatabaseClient` / `QueryBuilder` classes there) — do not reach for raw SQL or a second DB client in the route. Operators supported today include `eq`, `neq`, `in_`, `is_`, `gt`/`lt`/`gte`/`lte`, `order`, `limit`, `range`, and `rpc`.

---

*Convention analysis: 2026-08-12*
