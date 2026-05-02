# Codebase Summary

## Overview

DropItX API is a FastAPI application (~2,530 LOC across 30 source files) providing file/text sharing with team collaboration. Auth via Supabase Auth (JWT) and API keys. Data stored in Supabase (Postgres + Storage).

## Directory Structure

```
dropitx-api/
├── core/                          # Shared utilities (366 LOC)
│   ├── config.py (18)            # Pydantic BaseSettings
│   ├── supabase.py (33)          # Client factory (user/admin/anon)
│   ├── security.py (122)         # JWT, API key, password utilities
│   ├── extract_text.py (90)      # Plain text from HTML/MD
│   ├── nanoid.py (17)            # Slug/token generation
│   └── rate_limit.py (86)        # Postgres RPC rate limiting
│
├── app/
│   ├── main.py (34)              # FastAPI app, CORS, routers
│   ├── dependencies.py (174)     # Auth Depends providers
│   │
│   ├── v1/                       # API-key-authenticated (541 LOC)
│   │   ├── router.py (11)
│   │   ├── documents.py (273)    # Document CRUD
│   │   ├── document_helpers.py (87)
│   │   └── keys.py (170)         # API key management
│   │
│   ├── dashboard/                # JWT-authenticated team mgmt (654 LOC)
│   │   ├── router.py (21)
│   │   ├── teams.py (204)        # Team + member CRUD
│   │   ├── team_helpers.py (78)  # Role checks, lookups
│   │   ├── team_invites.py (258) # Invites, events, shares
│   │   └── invitations.py (93)
│   │
│   ├── internal/                 # Authenticated upload/publish (463 LOC)
│   │   ├── router.py (11)
│   │   ├── upload.py (179)       # File upload
│   │   ├── publish.py (188)      # Editor publish
│   │   └── images.py (85)        # Image upload
│   │
│   └── public/                   # Unauthenticated endpoints (460 LOC)
│       ├── router.py (13)
│       ├── shares.py (170)       # Share delete, password, unlock
│       ├── search.py (56)        # Full-text search
│       ├── analytics.py (93)     # View tracking
│       └── oembed.py (128)       # oEmbed discovery
│
├── models/                        # Pydantic DTOs (198 LOC)
│   ├── share.py (76)
│   ├── team.py (72)
│   ├── api_key.py (28)
│   └── analytics.py (22)
│
├── tests/                         # Test suite
├── supabase/                      # Supabase migrations
├── render.yaml                    # Render deployment blueprint
├── requirements.txt               # Python dependencies
└── CLAUDE.md                      # Project instructions
```

## Module Details

### core/config.py
Pydantic `BaseSettings` loading from `.env`. Exposes `settings` singleton with `supabase_url`, `supabase_anon_key`, `supabase_service_role_key`, `allowed_origins`, `frontend_url`. `cors_origins` property splits comma-separated origins.

### core/supabase.py
Three client types:
- **`get_user_client(token)`** — per-request, sets JWT on PostgREST, RLS applies
- **`get_admin_client()`** — service-role key, bypasses RLS (used in all routes)
- **`get_anon_client()`** — no user context, base client

Base client is lazy-initialized and reused. Admin client is created fresh each call.

### core/security.py
- **JWT verification**: Fetches JWKS from Supabase Auth (`/auth/v1/.well-known/jwks.json`), caches for 10 min. Verifies RS256 with audience set to Supabase URL.
- **API key generation**: `shk_` (personal) / `sht_` (team) prefix + 48 hex chars. Stored as SHA-256 hash.
- **Password hashing**: bcrypt with 12 rounds.

### core/extract_text.py
Regex-based plain text extraction from HTML and Markdown. Strips tags, code blocks, formatting. Limited to 100 KB input. Produces `content_text` for full-text search indexing.

### core/nanoid.py
- `generate_slug()` — 10-char alphanumeric URL slug (secrets.choice)
- `generate_delete_token()` — 32-char hex token for unauthenticated deletion

### core/rate_limit.py
Postgres RPC-based rate limiting via `check_rate_limit` function. Returns `RateLimitResult` with success/limit/remaining/reset. Configurable fail-open (returns success on DB error) vs fail-closed.

Predefined limits:
- Upload: 10/min/IP (fail-open)
- Password unlock: 5/10min/IP+slug (fail-closed)
- oEmbed: 60/min/IP (fail-open)
- Analytics: 60/min/IP (fail-open)

### app/dependencies.py
FastAPI `Depends` providers:
- **`get_current_user`** — extracts JWT from Bearer header, returns `User(id, email)`
- **`get_optional_user`** — same but returns `None` on failure
- **`get_api_key`** — validates `shk_`/`sht_` Bearer token against DB, checks revocation and team membership, fire-and-forget `last_used_at` update
- **`get_client_ip`** — extracts from X-Forwarded-For, X-Real-IP, or request.client

### app/v1/documents.py
Full CRUD for documents via API key auth. Uses `shares` bucket. Supports team documents via `team_shares` join. Compensating transactions: cleans up storage if DB insert fails.

### app/v1/keys.py
API key management. Create (returns raw key once), list (filter by team), revoke (soft-delete via `revoked_at`). Team key creation requires editor+ role.

### app/dashboard/teams.py
Team CRUD (list, create, get, update, delete). Member management (list, change role, remove). Owner-only for destructive operations. Uses `team_helpers.py` for role checks.

### app/dashboard/team_invites.py
Invite management (list, create, revoke, bulk up to 50, resend). Team events and shares listing. Registers routes on the `teams.py` router via side-effect import.

### app/internal/upload.py
File upload endpoint. Accepts HTML/MD files up to 50 MB. Rate-limited. Optional JWT for user association. Uses `html-files` bucket. Compensating transactions on DB failure.

### app/internal/publish.py
Editor publish endpoint. Requires JWT. Supports custom slugs (prepends user handle if available). Rate-limited. Uses `html-files` bucket.

### app/public/shares.py
Unauthenticated share management. Delete via owner JWT or delete_token. Password set/unlock with rate limiting (fail-closed, 5/10min). Uses bcrypt for password verification.

### app/public/search.py
Full-text search via `search_shares` Postgres RPC. Paginated results with snippet and rank.

### app/public/analytics.py
View tracking. Always returns 200. Fail-open rate limiting. Inserts to `share_views` table, increments `view_count` via RPC.

### app/public/oembed.py
oEmbed discovery for share embeds. Rate-limited 60/min/IP.

## Data Model (Inferred from Code)

### Tables

| Table | Purpose |
|-------|---------|
| `shares` | Core content shares (slug, content, storage, views, passwords) |
| `api_keys` | API key metadata (hashed, prefix, user/team association) |
| `teams` | Team definitions (name, slug, plan, owner) |
| `team_members` | Team membership (user, role, joined_at) |
| `team_invites` | Pending invitations (email, token, role, expiry) |
| `team_events` | Team activity log |
| `team_shares` | Share-to-team association |
| `share_views` | View tracking records |
| `user_profiles` | User display info (display_name, avatar_url) |
| `profiles` | User profiles (handle, display_name) |

### Postgres RPCs

| RPC | Purpose |
|-----|---------|
| `check_rate_limit` | Sliding-window rate limiting |
| `search_shares` | Full-text search with ranking |
| `create_team_invite` | Upsert invite with uniqueness check |
| `accept_team_invite` | Accept invite, create membership |
| `decline_team_invite` | Mark invite as declined |
| `change_team_member_role` | Update member role with permission checks |
| `remove_team_member` | Remove member with cleanup |
| `increment_share_views` | Atomic view count increment |

### Storage Buckets

| Bucket | Purpose |
|--------|---------|
| `html-files` | Upload and publish flow files |
| `shares` | V1 API document storage |
