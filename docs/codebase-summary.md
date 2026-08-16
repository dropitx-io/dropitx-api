# Codebase Summary

## Overview

DropItX API is a FastAPI application (v0.3.0, ~3,800 LOC across 50+ source files) providing file/text sharing with team collaboration, end-to-end encryption, discovery features, and file requests. Authentication via Firebase ID tokens (JWT) and API keys. Data stored in Supabase (Postgres + Storage).

## Directory Structure

```
dropitx-api/
├── core/                          # Shared utilities & services (366 LOC)
│   ├── config.py                 # Pydantic BaseSettings from .env
│   ├── supabase.py               # Client factory (user/admin/anon)
│   ├── security.py               # JWT, API key, password utilities
│   ├── encryption.py             # AES-256-GCM, PBKDF2 (e2e)
│   ├── extract_text.py           # Plain text from HTML/Markdown
│   ├── nanoid.py                 # Slug/token generation
│   ├── rate_limit.py             # Postgres RPC rate limiting
│   ├── language_detect.py        # Language detection via ngram
│   ├── thumbnail.py              # Image thumbnail generation
│   ├── exceptions.py             # Custom error types
│   ├── logging_config.py         # Structured JSON logging
│   └── middleware.py             # Request tracking, security headers
│
├── app/
│   ├── main.py                   # FastAPI app, CORS, routers, health
│   ├── dependencies.py           # Auth Depends (JWT, API key, IP)
│   │
│   ├── v1/                       # API-key-authenticated (541 LOC)
│   │   ├── router.py             # Route registration
│   │   ├── documents.py          # Document CRUD via API key
│   │   ├── document_helpers.py   # Shared document logic
│   │   ├── keys.py               # API key management (CRUD)
│   │   └── revisions.py          # Version history endpoints
│   │
│   ├── dashboard/                # JWT-authenticated team mgmt (850+ LOC)
│   │   ├── router.py             # Route registration
│   │   ├── teams.py              # Team + member CRUD
│   │   ├── team_helpers.py       # Role checks, team lookups
│   │   ├── team_invites.py       # Invites, events, shares
│   │   ├── invitations.py        # User's received invites
│   │   └── domains.py            # Custom domain management
│   │
│   ├── internal/                 # Authenticated upload/publish (800+ LOC)
│   │   ├── router.py             # Route registration
│   │   ├── upload.py             # File upload (HTML/MD, 50MB max)
│   │   ├── multi_upload.py       # Batch upload / share groups
│   │   ├── publish.py            # Editor publish (custom slugs)
│   │   ├── images.py             # Embedded image upload
│   │   ├── download.py           # Bulk download (ZIP)
│   │   ├── file_requests.py      # Upload request links (auth)
│   │   └── cli_upload.py         # CLI-specific upload
│   │
│   ├── public/                   # Unauthenticated endpoints (1000+ LOC)
│   │   ├── router.py             # Route registration
│   │   ├── shares.py             # Share delete, password, unlock
│   │   ├── search.py             # Full-text search (RPC)
│   │   ├── analytics.py          # View tracking
│   │   ├── oembed.py             # oEmbed discovery
│   │   ├── qrcode.py             # QR code generation
│   │   ├── comments.py           # Share comments
│   │   ├── versions.py           # Version history (read-only)
│   │   ├── encryption.py         # E2E encryption endpoints
│   │   ├── preview.py            # File preview (images, PDF, text, etc)
│   │   ├── explore.py            # Gallery feed (trending, tags)
│   │   ├── stars.py              # Star/unstar shares
│   │   ├── profiles.py           # Public user profiles
│   │   ├── languages.py          # Language tagging
│   │   └── file_requests.py      # Public upload to requests
│   │
│   └── services/
│       └── cleanup.py            # Background cleanup (expired shares/requests)
│
├── models/                        # Pydantic DTOs (298 LOC)
│   ├── share.py                  # Share models (input/output)
│   ├── team.py                   # Team models
│   ├── api_key.py                # API key models
│   ├── analytics.py              # Analytics models
│   ├── domain.py                 # Custom domain models
│   └── file_request.py           # File request models
│
├── tests/                         # Test suite (~8 files, ~25-30% coverage)
│   ├── test_all_endpoints.py     # Endpoint validation
│   ├── test_encryption.py        # E2E encryption
│   ├── test_file_requests.py     # Upload requests
│   ├── test_custom_domains.py    # Domain verification
│   ├── test_preview.py           # File preview
│   ├── test_one_time_download.py # Burn-after-read
│   └── test_public_api_validation.py
│
├── supabase/                      # Supabase migrations
│   ├── migrations/
│   │   ├── 20260529_base_schema.sql          # Core tables, auth
│   │   ├── 20260530_competitor_features.sql # Multi-file, encryption, comments
│   │   ├── 20260531_file_requests.sql       # File request tables
│   │   └── 20260531_fix_schema_mismatches.sql
│   └── config.toml                # Supabase CLI config
│
├── migrations/                    # Additional migrations (alternate location)
│   ├── 001_add_encryption_columns.sql
│   ├── 001_create_share_files.sql
│   ├── 002_create_share_comments.sql
│   ├── 003_create_share_revisions.sql
│   ├── 004_custom_domains.sql
│   ├── 004_explore_gallery.sql
│   ├── 005_add_one_time_download.sql
│   └── 006_add_language_column.sql
│
├── cli/                           # Standalone npm CLI (Commander-based JS)
│   ├── package.json
│   ├── bin/dropitx.js
│   ├── lib/commands/              # login, upload, download, list, delete
│   └── lib/api.js
│
├── docs/                          # Documentation
├── render.yaml                    # Render deployment blueprint
├── requirements.txt               # Python 3.12+ dependencies
├── pyproject.toml                # Project metadata & test config
├── CLAUDE.md                      # Developer instructions
└── README.md                      # Quick start guide
```

## Module Details

### Core Services

#### config.py
Pydantic `BaseSettings` loading from `.env`. Exposes `settings` singleton with `supabase_url`, `supabase_anon_key`, `supabase_service_role_key`, `allowed_origins`, `frontend_url`. `cors_origins` property splits comma-separated origins.

#### supabase.py
Three client types:
- **`get_user_client(token)`** — per-request, sets JWT, RLS applies
- **`get_admin_client()`** — service-role key, bypasses RLS (used in routes)
- **`get_anon_client()`** — no user context

Base client lazy-initialized, admin client fresh per call (no pooling).

#### security.py
- **JWT**: Fetches x509 certs from Google (Firebase ID token verification), ~1hr cache, RS256 verification
- **API keys**: `shk_`/`sht_` prefix + 48 hex chars, SHA-256 hashed storage
- **Passwords**: bcrypt with 12 rounds

#### encryption.py
- **E2E Encryption**: AES-256-GCM with 12-byte IV
- **Key Derivation**: PBKDF2 (100k iterations, 32-byte salt)
- **Zero-Knowledge**: Server never sees plaintext; client derives key from password

#### extract_text.py
Regex-based plain text extraction from HTML and Markdown. Strips tags, code blocks, formatting. Limited to 100 KB input.

#### language_detect.py
Language detection via character n-grams (no external dependencies). Detects 50+ languages.

#### thumbnail.py
Image thumbnail generation for preview functionality. Supports PNG, JPG, GIF, WebP.

#### rate_limit.py
Postgres RPC `check_rate_limit(p_key, p_max_attempts, p_window_secs)` returns `{success, remaining, reset_at}`. Configurable fail-open vs fail-closed.

### Route Groups

#### v1/ (API Key Auth)
**Document CRUD via API key** (`shk_` personal or `sht_` team).

- **documents.py**: POST (create), GET (list), GET /{slug}, PATCH (update), DELETE
  - Supports team documents via `team_shares` join
  - Compensating transactions: cleanup storage on DB failure
- **keys.py**: API key management
  - POST (create, returns raw key once)
  - GET (list, filter by team)
  - DELETE (revoke via soft-delete)
- **revisions.py**: Version history endpoints
  - GET /shares/{slug}/revisions — list versions
  - GET /shares/{slug}/revisions/{version_num} — fetch specific version

#### dashboard/ (JWT Auth)
**Team collaboration and management**.

- **teams.py**: Team CRUD, member management, role changes
- **team_invites.py**: Invite lifecycle (create, list, revoke, bulk, resend), events, shares
- **invitations.py**: User's received invites (list, accept, decline)
- **domains.py**: Custom domain CRUD, DNS verification, brand configuration

Role hierarchy: `owner (3) > editor (2) > viewer (1)`.

#### internal/ (Authenticated)
**Upload, publish, file operations, and file requests**.

- **upload.py**: File upload (HTML/MD, up to 50 MB), optional JWT, rate-limited
- **multi_upload.py**: Batch upload, share groups, multi-file uploads
- **publish.py**: Editor publish (custom slugs, rate-limited), requires JWT
- **images.py**: Embedded image upload (PNG/JPG/GIF/WebP, 5 MB max)
- **download.py**: Bulk download (ZIP archives for share groups)
- **file_requests.py**: Authenticated file request creation and management
- **cli_upload.py**: CLI-specific upload endpoint

#### public/ (No Auth Required)
**Public endpoints for discovery, sharing, viewing, and file uploads**.

- **shares.py**: Delete (owner JWT or token), password set/unlock, burn, download status, content view
- **search.py**: Full-text search via `search_shares` RPC
- **analytics.py**: View tracking (always 200, fail-open)
- **oembed.py**: oEmbed discovery for embeds
- **qrcode.py**: QR code generation (SVG or PNG)
- **comments.py**: Add/list comments on shares
- **versions.py**: Read-only version history (client can choose revision)
- **encryption.py**: Encryption endpoints (encrypt, re-encrypt, key generation, zero-knowledge)
- **preview.py**: File preview (images, PDF, code, markdown, video/audio, text, auto-detection)
- **explore.py**: Gallery feed (trending, tag-filtered, language-tagged)
- **stars.py**: Star/unstar shares (requires JWT)
- **profiles.py**: Public user profiles + their shares
- **languages.py**: Language tagging and detection endpoints
- **file_requests.py**: Public upload to file request links

### Services

#### cleanup.py
Background service runs on app startup. Periodically deletes:
- Expired shares (`expires_at` < now)
- Expired file requests
- Burned shares (download_count >= max_downloads)

Runs hourly by default.

## Data Model

### Core Tables

| Table | Purpose |
|-------|---------|
| `shares` | Content (slug, title, content, storage path, view count, password, expiry, encryption metadata) |
| `api_keys` | API key metadata (prefix, hash, user/team, scopes, last_used, expiry) |
| `teams` | Team definitions (name, slug, plan, owner) |
| `team_members` | Team membership (user, role, created_at) |
| `team_invitations` | Pending invites (email, token, role, status, expiry) |
| `team_events` | Audit log (event_type, payload, timestamp) |
| `team_shares` | Share-to-team association |
| `share_views` | View tracking (IP, user agent, country, timestamp) |
| `share_revisions` | Version snapshots (version_num, content, html, timestamp) |
| `share_comments` | Comments (author, content, timestamp) |
| `share_groups` | Multi-file share batches (slug, user_id) |
| `custom_domains` | Domain records (domain, team_id, status, verification_token) |
| `file_requests` | Upload request links (slug, creator, expiry) |
| `profiles` | User profiles (handle, display_name) |

### Postgres RPCs

| RPC | Purpose |
|-----|---------|
| `check_rate_limit` | Sliding-window rate limiting |
| `search_shares` | Full-text search with ranking |
| `create_team_invite` | Atomic invite creation |
| `accept_team_invite` | Accept invite, create membership |
| `decline_team_invite` | Mark invite as declined |
| `change_team_member_role` | Update role with permission check |
| `remove_team_member` | Remove member with cleanup |
| `increment_share_views` | Atomic view count increment |
| `check_download_limit` | Enforce download count limit |

### Storage Buckets

| Bucket | Path Pattern | Purpose |
|--------|------|---------|
| `html-files` | `shares/{slug}.html` or `shares/{slug}.md` | Upload & publish flows |
| `shares` | `{user_id}/{slug}` | v1 API document storage |
| `thumbnails` | `shares/{slug}.jpg` | Generated previews |

## Authentication & Authorization

### Auth Methods

| Method | Header | Usage |
|--------|--------|-------|
| JWT | `Authorization: Bearer <jwt>` | Dashboard, upload, publish, images, invites, v1 keys, stars |
| API Key | `Authorization: Bearer shk_...` or `sht_...` | v1 documents only |
| Optional JWT | `Authorization: Bearer <jwt>` | Upload (associates with user if present) |
| None | — | Search, analytics, oEmbed, health, shares (public ops) |

### Role Hierarchy

`owner (3) > editor (2) > viewer (1)` — numeric comparison for permission checks.

## Key Patterns

- **asyncio.to_thread()** — Supabase sync client in async context
- **Compensating transactions** — Storage cleanup on DB failure
- **Fail-open/fail-closed** — Configurable RPC failure behavior
- **Rate limiting via RPC** — Postgres-backed, distributed
- **Fire-and-forget updates** — `last_used_at` on API key usage
- **Two storage buckets** — `html-files` (public) vs `shares` (private)
- **Background cleanup** — Hourly deletion of expired content

## Testing

**Current coverage**: ~8 test files, ~25-30% estimated coverage.

Tests exist for:
- Encryption (encrypt/decrypt, key derivation)
- File requests (creation, uploads, cleanup)
- Custom domains (verification, CNAME checks)
- Preview (image, PDF, text)
- One-time downloads (burn-after-read)
- Endpoint validation

**Missing coverage**: Most route handlers, core modules (security, extract_text, rate_limit), error paths.

## Deployment

- **Platform**: Render (container, auto-scaling)
- **Language**: Python 3.12+
- **Framework**: FastAPI + uvicorn
- **Database**: Supabase Postgres
- **Storage**: Supabase Storage
- **Auth**: Firebase (JWT, ID token verification)
- **Health**: `/health` (liveness) and `/health/deep` (database check)
- **Config**: `.env` file (Pydantic BaseSettings)
