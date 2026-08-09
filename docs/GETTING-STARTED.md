<!-- generated-by: gsd-doc-writer -->

# Getting Started

This guide takes you from a fresh clone to a running DropItX API server making its first API call. The DropItX API is a FastAPI backend (Python 3.12+) that uses Supabase for auth, Postgres data, and file storage.

## Prerequisites

Before you begin, you need:

- **Python 3.12 or newer** — pinned via `requires-python = ">=3.12"` in [`pyproject.toml`](../pyproject.toml) and `PYTHON_VERSION: "3.12.0"` in [`render.yaml`](../render.yaml). Check with `python --version`.
- **pip** — comes with Python; used to install [`requirements.txt`](../requirements.txt).
- **A Supabase project** with Auth, Postgres, and Storage enabled. The API expects:
  - Two Storage buckets: `html-files` and `shares`.
  - The Postgres RPCs listed in [`README.md`](../README.md#deployment) (`check_rate_limit`, `search_shares`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`, `increment_share_views`).
- **Your Supabase project URL and keys** — project URL, anon key, and service-role key, available in your Supabase dashboard.

No Node.js, Docker, or Redis is required for local development.

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/phuongddx/dropitx-api.git
   cd dropitx-api
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Linux/macOS
   # .venv\Scripts\activate         # Windows PowerShell
   ```

3. **Install dependencies.** For running the server, install from [`requirements.txt`](../requirements.txt):

   ```bash
   pip install -r requirements.txt
   ```

   To also run the test suite, install the package with the `dev` extra defined in [`pyproject.toml`](../pyproject.toml):

   ```bash
   pip install -e ".[dev]"
   ```

   A [`uv.lock`](../uv.lock) is present for reproducible installs — if you prefer `uv`, substitute `uv sync` and `uv run pytest`.

## Configure environment variables

The API reads all configuration from environment variables at startup via Pydantic `BaseSettings` in [`core/config.py`](../core/config.py). Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Then edit `.env` and fill in your Supabase credentials. The variables that must be set before the server will start are:

- `SUPABASE_URL` — your Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase anon/public key
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service-role key (bypasses RLS; keep secret)

`ALLOWED_ORIGINS` and `FRONTEND_URL` default to `http://localhost:3000` if omitted.

For the complete variable table, defaults, and per-environment notes, see **[CONFIGURATION.md](./CONFIGURATION.md)** — do not duplicate the full list here.

## First run

Start the development server with hot reload:

```bash
uvicorn app.main:app --reload
```

The server starts at `http://localhost:8000`. Interactive API docs are available at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Verify with the health endpoint

The `/health` endpoint is a basic liveness probe defined in [`app/main.py`](../app/main.py) — it always returns ok if the process is alive:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "service": "dropitx-api"}
```

To confirm Supabase connectivity, hit the deep health probe (`/health/deep`), which pings the `shares` table and reports latency:

```bash
curl http://localhost:8000/health/deep
```

A healthy response looks like:

```json
{
  "status": "ok",
  "checks": {"database": {"status": "ok", "latency_ms": 42.1}},
  "service": "dropitx-api"
}
```

If `status` is `"degraded"`, the `checks.database.error` field will describe what failed — usually missing or incorrect Supabase credentials.

## Run the tests

Tests use **pytest** with **pytest-asyncio** (`asyncio_mode = "auto"`, `testpaths = ["tests"]` from [`pyproject.toml`](../pyproject.toml)). Make sure the `dev` extra is installed first (see [Installation](#installation)).

```bash
# Full suite
pytest

# Single file
pytest tests/test_encryption.py -v

# Single test by name
pytest -k "test_name" -v
```

Test files live in [`tests/`](../tests/) and are named `test_*.py` (e.g. `test_all_endpoints.py`, `test_encryption.py`, `test_file_requests.py`).

## Make your first API call

Once `/health` returns ok, try a public endpoint that requires no authentication. Search across public shares:

```bash
curl "http://localhost:8000/api/search?q=hello&page=1&limit=10"
```

For an authenticated call, create an API key through the dashboard flow, then call the v1 documents endpoint using the key as a Bearer token (keys use the `shk_` personal or `sht_` team prefix):

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer shk_..." \
  -H "Content-Type: application/json" \
  -d '{"content": "<h1>Hello</h1>", "title": "My Doc"}'
```

See [`README.md`](../README.md#api-reference) for the full endpoint reference and [`CLAUDE.md`](../CLAUDE.md) for auth patterns.

## Common setup issues

- **Server fails to start with a missing-variable error.** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` are required at startup. Confirm your `.env` file exists in the project root and is filled in. See [CONFIGURATION.md](./CONFIGURATION.md).
- **`python -m venv` or `pip` not found, or Python reports an older version.** The API requires Python 3.12+. Install Python 3.12+ and ensure `python --version` reports `3.12.x` or newer before creating the virtual environment.
- **CORS errors from the frontend.** Add the frontend origin to `ALLOWED_ORIGINS` (comma-separated). The default is `http://localhost:3000`; omitting the frontend's exact origin causes browsers to block requests.
- **`/health/deep` reports `degraded` with a database error.** The Supabase URL or service-role key is wrong, or the `shares` table / required RPCs are not provisioned in your Supabase project. Verify the URL matches `https://<project>.supabase.co` and that the migrations and buckets (`html-files`, `shares`) are set up.
- **`ModuleNotFoundError: No module named 'pytest'` when running tests.** Install the dev extra: `pip install -e ".[dev]"`.

## Next steps

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — system design, module layout, and key patterns (async bridge, role hierarchy, API keys).
- **[CONFIGURATION.md](./CONFIGURATION.md)** — full environment variable reference, defaults, and per-environment overrides.
- **[deployment-guide.md](./deployment-guide.md)** — deploying to Render via [`render.yaml`](../render.yaml).
- **[`README.md`](../README.md)** — full API reference, commands, and project structure.
