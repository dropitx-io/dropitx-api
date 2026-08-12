# Testing Patterns

**Analysis Date:** 2026-08-12

## Test Framework

**Runner:**
- pytest >=8.0 (`pyproject.toml` `dev` extra).
- Config: `[tool.pytest.ini_options]` in `pyproject.toml`:
  - `asyncio_mode = "auto"` — async test functions are auto-collected without `@pytest.mark.asyncio`. (Many tests still mark explicitly; both work.)
  - `testpaths = ["tests"]`.
- pytest-asyncio >=0.24 is the async adapter.

**Assertion Library:**
- Plain `assert` and `pytest.raises`. No third-party assertion library (no `assertpy`, no `hamcrest`).
- `unittest.mock` from the stdlib for all mocking (`patch`, `MagicMock`, `AsyncMock`).

**Run Commands:**
```bash
pytest                                   # Run all tests (collects tests/)
pytest tests/test_dependencies.py -v     # Single file
pytest -k "test_claims_valid_token" -v   # Single test by name
pytest tests/test_encryption.py          # Pure-logic test, no DB required
pip install -e ".[dev]"                  # Install test deps into local venv
```

The full suite requires a live local Postgres + MinIO (`docker compose up -d`) for the DB-backed integration tests; the routing/validation tests do NOT. See "Test Types" below.

## Test File Organization

**Location:**
- All tests live in a single flat `tests/` directory at the repo root. There is no `tests/unit/` vs `tests/integration/` split and no per-package co-location.
- There is no `conftest.py` anywhere (not at root, not in `tests/`). Shared fixtures are defined per-file.

**Naming:**
- Files: `tests/test_<feature>.py` — `test_all_endpoints.py`, `test_auth_session.py`, `test_dependencies.py`, `test_encryption.py`, `test_file_requests.py`, `test_custom_domains.py`, `test_one_time_download.py`, `test_preview.py`, `test_public_api_validation.py`.
- Functions: `def test_<behavior>(...)`. Use `test_<state>_<condition>` for variants — `test_create_requires_auth`, `test_current_user_not_provisioned`, `test_rpc_exception_returns_500`.
- Classes group related tests: `class TestCreateFileRequest`, `class TestAESGCM`, `class TestHealth`, `class TestGetSession`. Use a class per endpoint or per concept.

**Structure:**
```
tests/
├── __init__.py
├── test_all_endpoints.py          # ASGI wiring + status-code sweep, no live DB
├── test_auth_session.py           # /api/auth/session, mocked get_admin_client
├── test_dependencies.py           # Unit tests for auth providers
├── test_encryption.py             # Pure crypto roundtrip (no DB, no mocks)
├── test_file_requests.py          # Endpoint tests, full DB shim mocked
├── test_custom_domains.py         # Endpoint tests, mocked client
├── test_one_time_download.py      # Feature tests, ASGI transport
├── test_preview.py
└── test_public_api_validation.py  # 422 validation sweep, ASGI transport
```

## Test Structure

**Suite Organization:**
```python
"""Module docstring — what the file covers, which endpoints, which auth mode."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.dependencies import get_current_user, get_firebase_claims


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        mock.firebase_project_id = "test-project"
        mock.cors_origins = ["*"]
        yield mock


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


class TestCreateFileRequest:
    def test_create_requires_auth(self, client):
        resp = client.post("/api/requests", json={"title": "Test"})
        assert resp.status_code == 401

    @patch("app.internal.file_requests.get_admin_client")
    def test_create_basic_request(self, mock_get_client, client, mock_user):
        override_auth(mock_user)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "req-new", "slug": "newslug", ...}]
        )
        resp = client.post("/api/requests", json={...})
        assert resp.status_code == 200
```
(Canonical pattern from `tests/test_file_requests.py`, `tests/test_auth_session.py`, `tests/test_custom_domains.py`.)

**Patterns:**
- **Settings mock (autouse):** every DB-touching test file starts with an `autouse=True` fixture that patches `core.config.settings` so tests never read `.env`. Mirrors this exactly:
  ```python
  @pytest.fixture(autouse=True)
  def mock_settings():
      with patch("core.config.settings") as mock:
          mock.firebase_project_id = "test-project"
          mock.cors_origins = ["*"]
          yield mock
  ```
- **Dependency-override cleanup (autouse):** every file that calls `app.dependency_overrides[...] = ...` pairs it with an autouse fixture that clears overrides in teardown:
  ```python
  @pytest.fixture(autouse=True)
  def cleanup_overrides():
      yield
      app.dependency_overrides.clear()
  ```
  Failure to do this leaks overrides between files.
- **Auth override helper:** instead of mocking JWT verification, override the FastAPI dependency:
  ```python
  def override_claims(claims):
      app.dependency_overrides[get_firebase_claims] = lambda: claims
  # or for the full user:
  def override_auth(user):
      app.dependency_overrides[get_current_user] = lambda: user
  ```
  Use `get_firebase_claims` for tests that exercise the `Depends(get_firebase_claims)` path (session endpoint) and `get_current_user` when the route depends on a fully provisioned `User`.

## Mocking

**Framework:** `unittest.mock` (`patch`, `MagicMock`, `AsyncMock`) from the stdlib.

**Patterns:**
- **Patch where used, not where defined.** Mock the import inside the module under test, not the source module:
  ```python
  @patch("app.auth.session.get_admin_client")
  @patch("app.dependencies.verify_firebase_jwt")
  def test_claims_valid_token(mock_verify, ...):
      mock_verify.return_value = {"sub": "uid-1", "email": "a@b.com"}
  ```
  `app.auth.session` imports `get_admin_client` from `core.supabase`, so patch `app.auth.session.get_admin_client` — NOT `core.supabase.get_admin_client`. See `tests/test_auth_session.py:39`, `tests/test_dependencies.py:42`.
- **Mock the PostgREST fluent chain.** The shim returns `MagicMock` whose attribute chain auto-builds itself; assert the terminal `.execute.return_value`:
  ```python
  mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
      data=[{"id": "uid-1", "email": "a@b.com"}]
  )
  ```
  For RPCs: `mock_client.rpc.return_value.execute.return_value = MagicMock(data=[PROFILE_ROW])`. See `tests/test_auth_session.py:48`, `tests/test_dependencies.py:51`.
- **Force a DB error** by setting `side_effect` on the chain (`mock_client.table.side_effect = RuntimeError("db down")`) and asserting the route maps it to HTTP 500. See `tests/test_dependencies.py:65`, `tests/test_auth_session.py:74`.
- **Async dependencies** can be overridden with a plain lambda returning a value (no need for AsyncMock) because FastAPI's dependency injection handles awaiting.

**What to Mock:**
- `core.config.settings` — always, via the autouse fixture.
- `app.dependencies.verify_firebase_jwt` when unit-testing `get_firebase_claims` / `get_current_user` directly.
- `app.<module>.get_admin_client` — anywhere a route touches the DB/storage. The mock returns a `MagicMock` whose chain yields canned rows.
- `core.rate_limit.check_upload_rate_limit` for upload tests that need to bypass the RPC.

**What NOT to Mock:**
- `app.main.app` itself — instantiate the real FastAPI app and exercise it through `TestClient` or `AsyncClient(ASGITransport)`. This is what gives the routing/validation tests their value.
- Pydantic validation — let FastAPI raise 422s natively; do not mock the validators. `tests/test_public_api_validation.py` is the model: it posts empty bodies and asserts the 422 shape.
- Pure crypto/algorithm code (`core/encryption.py`) — test it for real with roundtrips; no mocks. See `tests/test_encryption.py`.

## Fixtures and Factories

**Test Data:**
- Inline dict literals per test, plus local `_make_*` factory helpers for entities with many fields:
  ```python
  def _make_file_request_row(**overrides):
      now = datetime.now(timezone.utc)
      row = {"id": "req-123", "slug": "testslug", "user_id": "user-123", ...}
      row.update(overrides)
      return row
  ```
  (See `tests/test_file_requests.py`.)
- Module-level constant dicts for fully-specified rows: `PROFILE_ROW` in `tests/test_auth_session.py:32`.
- `mock_user`, `mock_team`, `mock_domain_record` fixtures in `tests/test_custom_domains.py:23-58` return canned rows.

**Location:**
- All fixtures and factories live in the test file that uses them (no shared `conftest.py`). When the same fixture is needed across files, it is duplicated today — be aware before reaching for a `conftest.py` (the project has none yet).

**Constants used everywhere:**
- `FAKE_SLUG = "test-slug-abc123"`, `FAKE_TOKEN = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.fake"`, `FAKE_API_KEY = "shk_fakeapikey123456789"` — defined per file in the ASGI test sweepers (`tests/test_all_endpoints.py:71`, `tests/test_one_time_download.py`).

## Coverage

**Requirements:** None enforced. No `--cov` flag, no `pytest-cov` dependency, no coverage gate in CI (no CI config detected in-repo).

**View Coverage:**
```bash
pip install pytest-cov
pytest --cov=app --cov=core --cov-report=term-missing
```
(Not part of the default workflow — add ad-hoc when measuring.)

## Test Types

**Unit Tests:**
- `tests/test_dependencies.py` — auth providers (`get_firebase_claims`, `get_current_user`, `get_api_key`) tested synchronously via `asyncio.run(...)` and `unittest.mock.patch`. No HTTP, no app.
- `tests/test_encryption.py` — pure crypto roundtrips (`generate_encryption_key`, AES-GCM `encrypt_data`/`decrypt_data`, password-derived keys, URL key extraction). No mocks, no DB.
- **Run without infra:** `pytest tests/test_dependencies.py tests/test_encryption.py -v`.

**API/Routing Tests (ASGI transport, no live DB):**
- `tests/test_all_endpoints.py` — 50+ endpoint existence + status-code sweep over `ASGITransport(app=app)` with fake tokens. Verifies auth gating (401 vs 422 vs 200) without touching the DB.
- `tests/test_public_api_validation.py` — asserts Pydantic 422 responses for missing/empty fields, using the real FastAPI validation layer.
- `tests/test_one_time_download.py`, `tests/test_preview.py` — feature validation over ASGI.
- Pattern:
  ```python
  @pytest.fixture
  async def client():
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
          yield c
  ```

**Integration Tests (DB mocked at the shim boundary):**
- `tests/test_auth_session.py`, `tests/test_file_requests.py`, `tests/test_custom_domains.py` — use `fastapi.testclient.TestClient(app)` and patch `get_admin_client` to return a `MagicMock`. The PostgREST fluent chain is mocked, NOT a real Postgres.
- No tests in the suite actually connect to a live Postgres/MinIO today, despite `CLAUDE.md` mentioning that some test files need `docker compose up -d`. Treat the `get_admin_client` mock as the integration boundary.

**E2E Tests:**
- Not used. There is no Playwright/Selenium/HTTP-against-running-server harness.

## Common Patterns

**Async Testing:**
- `asyncio_mode = "auto"` lets you write `async def test_x(client):` directly. Many files also add `@pytest.mark.asyncio` explicitly — both work, prefer plain `async def` for new tests.
- For async unit tests of `async def` functions without an event loop of your own, `asyncio.run(get_current_user(...))` is the established pattern in `tests/test_dependencies.py` (synchronous test functions that drive an async callee).
- Async client fixture is session/function-scoped and yields:
  ```python
  @pytest.fixture
  async def client():
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
          yield c
  ```

**Error Testing:**
- `pytest.raises(HTTPException) as exc` and assert on `exc.value.status_code` and `exc.value.detail`:
  ```python
  with pytest.raises(HTTPException) as exc:
      asyncio.run(get_current_user(_req("tok")))
  assert exc.value.status_code == 401
  assert exc.value.detail["code"] == "user_not_provisioned"
  ```
  (From `tests/test_dependencies.py:38-41, 61-65`.)
- For HTTP-level error tests, hit the route through the client and assert `resp.status_code` plus `resp.json()["detail"]`:
  ```python
  def _assert_422(resp, missing_fields: list[str]):
      assert resp.status_code == 422
      errors = resp.json()["detail"]
      reported_fields = {err["loc"][-1] for err in errors if len(err.get("loc", [])) >= 2}
      for field in missing_fields:
          assert field in reported_fields
  ```
  (Reusable helper pattern from `tests/test_public_api_validation.py:30-43`.)

**Custom FakeRequest pattern:**
- When testing FastAPI dependencies without spinning up the app, define a tiny request stub:
  ```python
  class FakeRequest:
      def __init__(self, headers=None):
          self.headers = headers or {}
  ```
  Used in `tests/test_dependencies.py:11-14` to drive `get_firebase_claims(request)` directly.

**Endpoint inventory in the docstring:**
- Large routing test files start with a docstring enumerating every endpoint under test, its auth mode, and its expected status code (see the head of `tests/test_all_endpoints.py` and `tests/test_public_api_validation.py`). When adding endpoints, update that docstring list.

---

*Testing analysis: 2026-08-12*
