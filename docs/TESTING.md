<!-- generated-by: gsd-doc-writer -->

# Testing

The DropItX API test suite is a pytest suite in [`tests/`](../tests/) that exercises the FastAPI app and its core logic **without ever hitting a live backend**. The DB/storage client (`get_admin_client` / `get_user_client` / `get_anon_client` from [`core/supabase.py`](../core/supabase.py) — a PostgREST-compatible shim, not an actual Supabase backend), configuration, and Firebase JWT verification are mocked so the suite runs offline and fast.

## Test framework and setup

| Tool | Version constraint | Source |
|------|--------------------|--------|
| pytest | `>=8.0` | [`pyproject.toml`](../pyproject.toml) `[project.optional-dependencies].dev` |
| pytest-asyncio | `>=0.24` | [`pyproject.toml`](../pyproject.toml) `[project.optional-dependencies].dev` |
| httpx | `>=0.28.0` | [`pyproject.toml`](../pyproject.toml) (runtime + test transport) |
| Python | `>=3.12` | [`pyproject.toml`](../pyproject.toml) `requires-python` |

pytest configuration lives in [`pyproject.toml`](../pyproject.toml) under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- `asyncio_mode = "auto"` lets `async def test_*` functions run on pytest's asyncio loop without an explicit marker (existing tests still use `@pytest.mark.asyncio` for clarity).
- `testpaths = ["tests"]` means a bare `pytest` invocation discovers the whole suite — no path arguments needed.

There is **no `conftest.py`** at the project level. Each test file defines its own fixtures.

### One-time setup

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode plus the `dev` extra (pytest, pytest-asyncio). Because `core.config.settings` is mocked in the tests (see [Mocking strategy](#mocking-strategy-for-the-dbstorage-client-and-firebase-auth)), no real `.env` file is required to run the suite.

## Running tests

```bash
# Full suite (testpaths picks up tests/)
pytest

# One file, verbose
pytest tests/test_file_requests.py -v

# One test by name (substring match across files)
pytest -k "test_create_file_request" -v

# Verbose with print output
pytest -v -s
```

All commands run from the repository root (`dropitx-api/`).

## Writing new tests

### File and naming conventions

- Place new tests in `tests/` as `test_<feature>.py` — matching the seven existing files (`test_all_endpoints.py`, `test_custom_domains.py`, `test_encryption.py`, `test_file_requests.py`, `test_one_time_download.py`, `test_preview.py`, `test_public_api_validation.py`).
- Group related cases in a `class Test<Area>:` (e.g. `TestHealth`, `TestPublicEndpoints` in `test_all_endpoints.py`).
- Name test functions `test_<behavior>`.

### Choose a test pattern

The suite uses two patterns; pick the one that matches what you are testing.

**1. HTTP-level tests via ASGI transport** (used by `test_all_endpoints.py`, `test_preview.py`, `test_one_time_download.py`, `test_public_api_validation.py`) — for testing route existence, request validation, and response shape against the real FastAPI app:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_search_missing_q(client):
    resp = await client.get("/api/search")
    assert resp.status_code == 422  # q required
```

For synchronous route logic, `test_file_requests.py` uses Starlette's `TestClient` instead:

```python
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
```

**2. Pure unit tests** (used by `test_encryption.py`) — for pure functions with no I/O, import the module directly and assert on outputs. `test_encryption.py` imports from [`core/encryption.py`](../core/encryption.py) and needs no mocks.

### Mocking strategy for the DB/storage client and Firebase auth

No test makes a real DB/storage call or a real Firebase network call — both are mocked at their respective call sites. Three layers are stubbed:

**a. Mock the Supabase client.** Patch `get_admin_client` / `get_user_client` / `get_anon_client` (defined in [`core/supabase.py`](../core/supabase.py)) at the call site, then chain `MagicMock` to mimic the query builder:

```python
from unittest.mock import patch, MagicMock


@patch("app.internal.file_requests.get_admin_client")
def test_create_file_request(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "fr-1", ...}]
    )
    # ... call the route/function under test ...
```

Patch at the module where the client is **imported and used**, not at `core.supabase` (e.g. `app.internal.file_requests.get_admin_client`, `app.public.file_requests.get_admin_client`). Storage uploads are mocked the same way: `mock_client.storage.from_.return_value.upload.return_value = MagicMock()`.

**b. Mock settings to avoid `.env`.** Inject fake Supabase config via an autouse fixture (pattern from `test_file_requests.py`):

```python
MOCK_SETTINGS = {
    "supabase_url": "https://test.supabase.co",
    "supabase_anon_key": "test-anon-key",
    "supabase_service_role_key": "test-service-key",
    "allowed_origins": "*",
    "frontend_url": "https://dropitx.com",
}


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        for k, v in MOCK_SETTINGS.items():
            setattr(mock, k, v)
        mock.cors_origins = ["*"]
        yield mock
```

**c. Override auth dependencies.** Replace `get_current_user` with FastAPI dependency overrides rather than forging JWTs (pattern from `test_file_requests.py`):

```python
from app.dependencies import User, get_current_user


@pytest.fixture
def mock_user():
    return User(id="user-123", email="test@example.com")


def override_auth(user):
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def cleanup_overrides(client):
    yield
    from app.main import app
    app.dependency_overrides.clear()
```

Helper row builders (e.g. `_make_file_request_row(**overrides)` in `test_file_requests.py`) keep mock Supabase rows consistent — copy this idiom for new domains.

### Async/sync note

The Supabase Python client is synchronous and the app wraps every call in `asyncio.to_thread()` (see [`CLAUDE.md`](../CLAUDE.md) "Async/sync bridge"). Tests that exercise routes through `ASGITransport` are `async def`; tests that mock `get_admin_client` and call handlers directly may be synchronous. Because `asyncio_mode = "auto"` is set, you can mix both in the same file.

## Coverage requirements

No coverage tooling is configured. There is no `pytest-cov` dependency, no `[tool.coverage]` section in [`pyproject.toml`](../pyproject.toml), and no `.coveragerc`. Tests run as pass/fail with no enforced coverage threshold.

To measure coverage ad hoc, install and invoke it manually:

```bash
pip install pytest-cov
pytest --cov=app --cov=core --cov=models --cov-report=term-missing
```

## CI integration

No CI pipeline runs this suite automatically. There is no `.github/workflows/` directory in `dropitx-api/`, and the only CI in the workspace is the sibling CLI repo at `dropitx-cli/.github/workflows/ci.yml`, which does not test the API. Tests must be run locally (or wired into a future pipeline) before merging.

<!-- VERIFY: if a CI pipeline is added for dropitx-api, update this section with the workflow filename, trigger, and the exact pytest command it runs. -->
