# DropItX API

FastAPI backend for file/text sharing with team collaboration. Upload HTML/Markdown content, share via public URLs, and collaborate in teams.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Commands](#commands)
- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Authentication](#authentication)
- [Deployment](#deployment)
- [Project Structure](#project-structure)

## Quick Start

```bash
# Clone
git clone https://github.com/<org>/dropitx-api.git
cd dropitx-api

# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Supabase credentials

# Run dev server
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`. Interactive docs at `/docs`.

## Configuration

Create `.env` in the project root:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
FRONTEND_URL=http://localhost:3000
```

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anon/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service-role key (bypasses RLS) |
| `ALLOWED_ORIGINS` | Yes | Comma-separated CORS origins |
| `FRONTEND_URL` | Yes | Frontend base URL (used for invite links) |

## Commands

| Command | Purpose |
|---------|---------|
| `uvicorn app.main:app --reload` | Dev server with hot reload |
| `pytest` | Run all tests |
| `pytest tests/test_foo.py -v` | Single test file |
| `pytest -k "test_name" -v` | Single test by name |
| `pip install -r requirements.txt` | Install production deps |
| `pip install -e ".[dev]"` | Install with test deps |

## Architecture

```
Client → FastAPI → [JWT/API Key Auth] → Route Handler
                                        → Supabase Client (asyncio.to_thread)
                                            ├── Postgres (data)
                                            └── Storage (files)
```

### Key Patterns

- **asyncio.to_thread()** — wraps sync Supabase client calls for async compatibility
- **Compensating transactions** — storage files cleaned up if DB insert fails
- **Rate limiting** — Postgres RPC with configurable fail-open/fail-closed
- **Role hierarchy** — `owner (3) > editor (2) > viewer (1)` for team permissions
- **API keys** — `shk_` (personal) / `sht_` (team) prefixes, SHA-256 hashed
- **Storage buckets** — `html-files` (upload/publish), `shares` (v1 documents)

## API Reference

Interactive Swagger docs at `/docs`, ReDoc at `/redoc`.

### Public Endpoints (no auth)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/search?q=` | Full-text search across public shares |
| `POST` | `/api/analytics/track` | View tracking (always returns 200) |
| `GET` | `/api/oembed?url=` | oEmbed discovery for share URLs |
| `POST` | `/api/shares/{slug}/unlock` | Verify share password |
| `DELETE` | `/api/shares/{slug}` | Delete share (owner or delete_token) |
| `POST` | `/api/shares/{slug}/set-password` | Set or clear share password |

### Authenticated Endpoints (JWT)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload HTML/MD file (optional JWT) |
| `POST` | `/api/publish` | Publish editor content |
| `POST` | `/api/images/upload` | Upload embedded image (PNG/JPG/GIF/WebP, 5MB max) |
| `GET` | `/api/dashboard/teams` | List user's teams |
| `POST` | `/api/dashboard/teams` | Create a team (caller becomes owner) |
| `GET` | `/api/dashboard/teams/{slug}` | Get team details (member only) |
| `PATCH` | `/api/dashboard/teams/{slug}` | Update team name/slug (owner only) |
| `DELETE` | `/api/dashboard/teams/{slug}` | Delete team (owner only) |
| `GET` | `/api/dashboard/teams/{slug}/members` | List team members |
| `PATCH` | `/api/dashboard/teams/{slug}/members` | Change member role (owner only) |
| `DELETE` | `/api/dashboard/teams/{slug}/members` | Remove member |
| `GET` | `/api/dashboard/teams/{slug}/invites` | List team invites |
| `POST` | `/api/dashboard/teams/{slug}/invites` | Create invite (editor+) |
| `DELETE` | `/api/dashboard/teams/{slug}/invites` | Revoke invite (editor+) |
| `POST` | `/api/dashboard/teams/{slug}/invites/bulk` | Bulk invite up to 50 emails (editor+) |
| `POST` | `/api/dashboard/teams/{slug}/invites/{id}/resend` | Resend invite (editor+) |
| `GET` | `/api/dashboard/teams/{slug}/events` | List team events (paginated) |
| `GET` | `/api/dashboard/teams/{slug}/shares` | List team shares (paginated) |
| `GET` | `/api/dashboard/invitations` | List received invites |
| `POST` | `/api/invite/accept` | Accept team invite |
| `POST` | `/api/invite/decline` | Decline team invite |

### API Key Endpoints (Bearer `shk_`/`sht_`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents` | Create document |
| `GET` | `/api/v1/documents` | List documents (paginated) |
| `GET` | `/api/v1/documents/{slug}` | Get document |
| `PATCH` | `/api/v1/documents/{slug}` | Update document |
| `DELETE` | `/api/v1/documents/{slug}` | Delete document |

### JWT Endpoints — API Key Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/keys` | Create API key (returns raw key once) |
| `GET` | `/api/v1/keys` | List API keys (optionally filter by team) |
| `DELETE` | `/api/v1/keys/{id}` | Revoke API key (soft delete) |

### Example: Upload a file

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@document.html" \
  -H "Authorization: Bearer <jwt-token>"
```

### Example: Create a document via API key

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer shk_..." \
  -H "Content-Type: application/json" \
  -d '{"content": "<h1>Hello</h1>", "title": "My Doc"}'
```

### Example: Create an API key

```bash
curl -X POST http://localhost:8000/api/v1/keys \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Script Key"}'
```

### Example: Search

```bash
curl "http://localhost:8000/api/search?q=hello&page=1&limit=10"
```

## Authentication

| Method | Header | Endpoints |
|--------|--------|-----------|
| JWT (Supabase) | `Authorization: Bearer <jwt>` | Dashboard, upload, publish, images, invites, v1 keys |
| API Key | `Authorization: Bearer shk_...` or `sht_...` | v1 documents only |
| Optional JWT | `Authorization: Bearer <jwt>` | Upload (associates with user if present) |
| None | — | Search, analytics, oEmbed, health, share unlock |

JWT tokens are verified against Supabase JWKS (`/auth/v1/.well-known/jwks.json`) with 10-minute key caching. API keys are stored as SHA-256 hashes; the raw key is returned only once on creation.

## Deployment

### Render

Blueprint included in `render.yaml`. Connect repo, Render auto-detects config. Set env vars in the Render dashboard.

### Requirements

- Python 3.12+
- Supabase project with Auth, Postgres, and Storage configured
- Storage buckets: `html-files`, `shares`
- Required Postgres RPCs: `check_rate_limit`, `search_shares`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`, `increment_share_views`

## Project Structure

```
core/                   Shared utilities
  config.py             Settings (Pydantic BaseSettings)
  supabase.py           Supabase client factory (user/admin/anon)
  security.py           JWT verification, API key hashing, passwords
  extract_text.py       Plain text extraction from HTML/Markdown
  nanoid.py             Slug and token generation
  rate_limit.py         Postgres RPC rate limiting

app/
  main.py               FastAPI app, CORS, router registration
  dependencies.py       Auth providers (get_current_user, get_api_key)
  v1/                   API-key document endpoints + JWT key management
  dashboard/            JWT team management (teams, invites, events, shares)
  internal/             Authenticated upload/publish/image endpoints
  public/               Unauthenticated public endpoints (shares, search, analytics, oembed)

models/                 Pydantic DTOs (share, team, api_key, analytics)
tests/                  Test suite (pytest + pytest-asyncio)
supabase/               Supabase migrations and config
```

## License

Private — all rights reserved.
