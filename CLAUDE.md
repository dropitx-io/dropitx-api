# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DropItX API — a FastAPI backend for file/text sharing with team collaboration. Users upload HTML/Markdown content, share it via public URLs, and collaborate in teams. Auth is handled by Supabase Auth (JWT). Data and files live in Supabase (Postgres + Storage).

## Commands

```bash
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

## Architecture

### Route hierarchy (all under `/api`)

| Prefix | Auth | Purpose |
|--------|------|---------|
| `/api/v1/documents` | API key (`shk_`/`sht_`) | Document CRUD (programmatic) |
| `/api/v1/keys` | JWT (cookie) | API key management |
| `/api/dashboard/teams` | JWT | Team + member + invite + event management |
| `/api/dashboard/invitations` | JWT | User's received invites |
| `/api/invite/accept`, `/api/invite/decline` | JWT | Accept/decline invite |
| `/api/upload` | Optional JWT | File upload (HTML/MD) |
| `/api/publish` | JWT | Editor content publish |
| `/api/images/upload` | JWT | Embedded image upload |
| `/api/shares/{slug}` | Optional JWT | Public share delete, password set/unlock |
| `/api/search` | None | Public full-text search |
| `/api/analytics/track` | None | View tracking (always 200) |
| `/api/oembed` | None | oEmbed discovery |

### Key modules

- **`core/`** — Config, Supabase client factory, JWT verification (JWKS), API key hashing, password hashing, rate limiting, text extraction, slug generation
- **`app/dependencies.py`** — FastAPI `Depends` providers: `get_current_user` (JWT), `get_optional_user`, `get_api_key` (key validation), `get_client_ip`
- **`models/`** — Pydantic DTOs for shares, teams, API keys, analytics
- **`app/v1/`** — API-key-authenticated document endpoints
- **`app/dashboard/`** — JWT-authenticated team management. `team_helpers.py` has shared role-check/lookup logic. `team_invites.py` registers on `teams.py` router via side-effect import
- **`app/public/`** — Unauthenticated public endpoints
- **`app/internal/`** — Authenticated upload/publish/image endpoints

### Supabase client types

`core/supabase.py` provides three clients:
- `get_user_client(token)` — per-request, RLS applies
- `get_admin_client()` — service-role, bypasses RLS (used in all routes)
- `get_anon_client()` — no user context

### Patterns

- All DB/Storage calls are wrapped in `asyncio.to_thread()` since the Supabase Python client is synchronous
- Rate limiting delegates to a Postgres RPC `check_rate_limit` with configurable fail-open/fail-closed
- Compensating transactions: if DB insert fails after storage upload, the file is cleaned up
- Dashboard endpoints use role hierarchy: `owner (3) > editor (2) > viewer (1)`
- API keys have prefixes: `shk_` (personal), `sht_` (team). Keys are stored as SHA-256 hashes, raw key returned once on creation
- Two storage buckets: `html-files` (upload/publish flows), `shares` (v1 API documents)

## Deployment

- **Vercel**: `@vercel/python` build, entry point `app/main.py`
- **Render**: `render.yaml` blueprint, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Python 3.12+ required

## Environment Variables

Required in `.env`:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `ALLOWED_ORIGINS` (comma-separated), `FRONTEND_URL`
