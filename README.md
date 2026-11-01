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
STORAGE_PUBLIC_URL=http://localhost:9000
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
FRONTEND_URL=http://localhost:3000
```

| Variable | Required | Description |
|----------|----------|-------------|
| `STORAGE_PUBLIC_URL` | No | Browser-facing base URL of the object store (default `http://localhost:9000`); anonymous reads are limited to `html-files/public/` |
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
- **Rate limiting** — Postgres RPC with configurable fail-open/fail-closed. Every 429 carries `Retry-After` as whole seconds until the window resets (RFC 9110 delay-seconds), and CORS exposes it to the browser
- **Role hierarchy** — `owner (3) > editor (2) > viewer (1)` for team permissions
- **API keys** — `shk_` (personal) / `sht_` (team) prefixes, SHA-256 hashed
- **Storage buckets** — `html-files` (upload/publish), `shares` (v1 documents)

## API Reference

Interactive Swagger docs at `/docs`, ReDoc at `/redoc`.

### Public Endpoints (no auth)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (liveness) |
| `GET` | `/health/deep` | Deep health check (includes database ping) |
| `GET` | `/api/search?q=` | Full-text search across public shares |
| `GET` | `/api/explore?tag=&sort=` | Public gallery (trending, tag-filtered) |
| `GET` | `/api/u/{username}` | Public profile (`username`, `display_name`, `avatar_url`, `bio`, share stats; never the email). 404 unless the owner set `is_public` |
| `GET` | `/api/u/{username}/shares` | The profile's open shares (`page`, `limit`, `sort=recent\|views\|stars`): no private, password-protected, burned, expired, burn-after-reading or one-time-download shares |
| `GET` | `/api/shares/{slug}` | Share metadata and access state (no content, no view counted) |
| `GET` | `/api/shares/{slug}/content` | View share content |
| `GET` | `/api/shares/{slug}/download-status` | Check download status |
| `GET` | `/api/shares/{slug}/download` | Download share as file (`Content-Disposition: attachment`, `Cache-Control: no-transform` so a CDN cannot rewrite the bytes) |
| `GET` | `/api/shares/{slug}/versions` | Read-only version history |
| `GET` | `/api/shares/{slug}/preview` | File preview (images, PDF, code, text, media) |
| `GET` | `/api/shares/{slug}/qrcode` | Generate QR code (SVG or PNG) |
| `GET` | `/api/shares/{slug}/comments` | List comments on share |
| `POST` | `/api/shares/{slug}/unlock` | Verify share password |
| `POST` | `/api/shares/{slug}/burn` | Burn a share (owner JWT or `delete_token` in the body): deletes its content (file, thumbnails, multi-file files, version snapshots, v1 revisions) and keeps the row as a burned tombstone that answers 410; 410 if already burned |
| `POST` | `/api/shares/{slug}/comments` | Add comment to share |
| `DELETE` | `/api/shares/{slug}` | Delete share and all its stored files (owner or delete_token) |
| `POST` | `/api/shares/{slug}/set-password` | Set or clear share password |
| `POST` | `/api/shares/{slug}/encrypt` | Encrypt share with password |
| `POST` | `/api/shares/{slug}/reencrypt` | Re-encrypt with new password |
| `POST` | `/api/analytics/track` | Record one share view (`{slug, referrer?, is_embed?}`; always 204 unless rate-limited) |
| `GET` | `/api/oembed?url=` | oEmbed discovery for embeds |
| `POST` | `/api/encryption/generate-key` | Generate encryption key bundle |
| `POST` | `/api/requests/{slug}/upload` | Public upload to request link |

### Authenticated Endpoints (JWT)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload HTML/MD file (optional JWT, 50MB max) |
| `POST` | `/api/upload/batch` | Batch upload: each file becomes its own share in a group (`group_id`), owned by the signed-in caller |
| `POST` | `/api/upload/multi` | Multi-file upload: several files under one share |
| `POST` | `/api/publish` | Publish editor content with custom slug. Stored as `text/markdown` when `language` is `markdown` or the filename ends `.md`, else `text/html` |
| `PUT` | `/api/publish/{slug}` | Update a published share (owner); saves the previous content as a version and keeps the share's content type |
| `GET` | `/api/auth/session` | Provision the signed-in user and return their profile; assigns a username to a profile without one |
| `PUT` | `/api/v1/profile` | Update the caller's `display_name` (required), and optionally `username` (422 malformed or reserved, 409 taken) and `is_public` |
| `POST` | `/api/images/upload` | Upload embedded image (5MB max, PNG/JPG/GIF/WebP) |
| `POST` | `/api/requests` | Create file request/upload link |
| `GET` | `/api/dashboard/requests` | List user's file requests |
| `GET` | `/api/download/group/{slug}` | Bulk download group as ZIP (`Cache-Control: no-transform`) |
| `GET` | `/api/dashboard/shares` | List the caller's own shares, newest first (`page`, `limit` up to 100). Batch-uploaded shares are listed one item each, with their `group_id` |
| `GET` | `/api/dashboard/analytics/top-shares` | Totals over all the caller's shares plus the top shares by recent views (`limit` up to 50) |
| `GET` | `/api/dashboard/shares/{slug}/analytics` | Summary, daily timeseries, referrers and countries for one of the caller's shares (`days` 1-365; owner only) |
| `GET` | `/api/v1/favorites` | List the caller's favorited shares |
| `GET` / `POST` / `DELETE` | `/api/v1/favorites/{share_id}` | Check, add or remove a favorite (add and remove are idempotent) |
| `GET` | `/api/dashboard/teams` | List user's teams |
| `POST` | `/api/dashboard/teams` | Create a team (caller becomes owner) |
| `GET` | `/api/dashboard/teams/{slug}` | Get team details and the caller's `role` (member only) |
| `PATCH` | `/api/dashboard/teams/{slug}` | Update team name/slug (owner only) |
| `DELETE` | `/api/dashboard/teams/{slug}` | Delete team (owner only) |
| `GET` | `/api/dashboard/teams/{slug}/members` | List team members |
| `PATCH` | `/api/dashboard/teams/{slug}/members` | Change member role (owner only) |
| `DELETE` | `/api/dashboard/teams/{slug}/members` | Remove member |
| `GET` | `/api/dashboard/teams/{slug}/domains` | List custom domains (owner only) |
| `POST` | `/api/dashboard/teams/{slug}/domains` | Create custom domain (owner only) |
| `PATCH` | `/api/dashboard/teams/{slug}/domains/{id}` | Update domain config (owner only) |
| `DELETE` | `/api/dashboard/teams/{slug}/domains/{id}` | Delete domain (owner only) |
| `GET` | `/api/dashboard/teams/{slug}/invites` | List team invites |
| `POST` | `/api/dashboard/teams/{slug}/invites` | Create invite (editor+) |
| `DELETE` | `/api/dashboard/teams/{slug}/invites` | Revoke invite (editor+) |
| `POST` | `/api/dashboard/teams/{slug}/invites/bulk` | Bulk invite up to 50 emails (editor+) |
| `POST` | `/api/dashboard/teams/{slug}/invites/{id}/resend` | Resend invite (editor+) |
| `GET` | `/api/dashboard/teams/{slug}/events` | List team events, newest first (paginated; see [Team events](#team-events)) |
| `GET` | `/api/dashboard/teams/{slug}/shares` | List team shares (paginated) |
| `GET` | `/api/dashboard/invitations` | List received invites |
| `GET` | `/api/invites/{token}` | Look up an invite for the accept page (public) |
| `POST` | `/api/invite/accept` | Accept team invite |
| `POST` | `/api/invite/decline` | Decline team invite |
| `POST` | `/api/shares/{slug}/stars` | Star a share (JWT required) |

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

### Usernames

A username is 3-30 characters of lowercase letters, digits and hyphens, starting and ending with a letter or digit, unique, and not one of `admin`, `api`, `dashboard`, `auth`, `s`, `u`, `embed`. `GET /api/auth/session` gives a profile without one a name derived from the email's local part (else the display name, else `user`), adding `2`, `3`, ... when it is taken. `PUT /api/v1/profile` trims and lowercases a submitted `username`. A profile is public only once its owner sets `is_public: true`. Custom publish slugs are not prefixed with the username.

### Team events

`GET /api/dashboard/teams/{slug}/events` returns rows `{id, team_id, user_id, event_type, payload, created_at}`; `user_id` is the member who acted (null for a share that expired).

| `event_type` | Written when | `payload` |
|---|---|---|
| `member.joined` | an invite is accepted | `{role}` |
| `member.left` | a member removes themselves | `{user_id}` |
| `member.removed` | the owner removes a member | `{user_id}` |
| `member.role_changed` | the owner changes a member's role | `{user_id, role, previous_role}` |
| `invite.created` | an invite is created (one per address in a bulk invite) | `{invite_id, email, role}` |
| `invite.revoked` | a pending invite is revoked | `{invite_id, email}` |
| `share.added` | a team API key creates a document | `{share_id, slug}` |
| `share.removed` | a team's share is deleted (v1, owner delete, or expiry) | `{share_id, slug}` |

## Authentication

| Method | Header | Endpoints |
|--------|--------|-----------|
| JWT (Firebase) | `Authorization: Bearer <jwt>` | Dashboard, upload, publish, images, invites, v1 keys |
| API Key | `Authorization: Bearer shk_...` or `sht_...` | v1 documents only |
| Optional JWT | `Authorization: Bearer <jwt>` | Upload (associates with user if present) |
| None | — | Search, analytics, oEmbed, health, share unlock |

JWTs are Firebase ID tokens, verified via RS256 against Google's x509 cert endpoint and cached for ~1 hour (`_CERTS_TTL` in `core/security.py`; the old 10-minute figure was Supabase's JWKS cache interval). API keys are stored as SHA-256 hashes; the raw key is returned only once on creation.

## Deployment

### Render

Blueprint included in `render.yaml`. Connect repo, Render auto-detects config. Set env vars in the Render dashboard.

### Requirements

- Python 3.12+
- Supabase project with Auth, Postgres, and Storage configured
- Storage buckets: `html-files`, `shares`
- Required Postgres RPCs: `check_rate_limit`, `search_shares`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`, `record_share_view`

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
