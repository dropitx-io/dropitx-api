<!-- generated-by: gsd-doc-writer -->
# DropItX API — API Reference

This is the canonical HTTP contract for the DropItX FastAPI backend (`app/main.py`, app version `0.3.0`). It is consumed by the Next.js frontend (`dropitx/`), the Python CLI + MCP server (`dropitx-cli/`), and the bundled Node CLI. Every endpoint listed here is verified against the router source under `app/v1/`, `app/dashboard/`, `app/public/`, and `app/internal/`; nothing is inferred or invented.

The live OpenAPI spec is also served by the app at `/docs` (Swagger UI) and `/redoc` (ReDoc).

## How routers are mounted

All routes are aggregated in `app/main.py:150-154`:

| Mount prefix | Router | Source | Auth domain |
|---|---|---|---|
| `/api/v1` | `v1_router` | `app/v1/router.py` | API key + JWT (keys) |
| `/api/dashboard` | `dashboard_router` | `app/dashboard/router.py` | JWT |
| `/api` | `invite_actions` | `app/dashboard/invitations.py` (`invite_actions_router`) | JWT |
| `/api` | `public_router` | `app/public/router.py` | Public / optional JWT |
| `/api` | `internal_router` | `app/internal/router.py` | Mixed (JWT, optional, API-key) |
| _(root)_ | inline `@app.get` | `app/main.py:171,177` | Public |

The `/api` prefix is shared by `invite_actions`, `public_router`, and `internal_router`; paths are disambiguated by their route strings (e.g. `/invite/*`, `/shares/*`, `/publish`).

## Authentication

Two credential mechanisms are injected as FastAPI dependencies in `app/dependencies.py`. Both are transported via `Authorization: Bearer <token>` unless noted.

- **JWT (Firebase Auth)** — `get_current_user` (`app/dependencies.py:56`) verifies the Firebase ID token against Google's certs and returns a `User(id, email)`, requiring the user be provisioned (else `401 user_not_provisioned`). `get_optional_user` (`app/dependencies.py:84`) returns `User | None` without raising, for endpoints that associate content with a user when logged in but remain usable anonymously. Missing/invalid token → `401`.
- **API Key** — `get_api_key` (`app/dependencies.py:70`) accepts raw keys with the `shk_` (personal) or `sht_` (team) prefix, looks up the SHA-256 hash in the `api_keys` table, rejects revoked keys and team keys whose owner is no longer a member, and returns `ApiKeyAuth(user_id, key_id, team_id)`. The raw key is returned **once** at creation; only the hash is stored. A fire-and-forget task updates `last_used_at`.

Per-endpoint auth is labelled in the tables below as:

- **Public** — no credential required.
- **JWT** — valid Firebase ID token required, and the user must be provisioned (`get_current_user`).
- **JWT optional** — `get_optional_user`; works anonymously, enriches when authenticated.
- **API key** — `get_api_key` (Bearer `shk_…` / `sht_…`).
- **API key optional** — header-accepted key (e.g. `X-API-Key`) that links the upload to a user when present.
- **Owner token** — owner JWT **or** a `delete_token` in the request body (share self-service delete/burn/set-password links).

<!-- VERIFY: Production base URL is https://api.dropitx.com (referenced in cli_upload docstrings); confirm against the deployed Render service before relying on it. -->

## Error responses

All unhandled exceptions are normalized by the handlers in `app/main.py:92-139` into the `ErrorResponse` envelope (`core/exceptions.py:8`):

```json
{
  "error": "not_found",
  "detail": "Share not found",
  "request_id": "req_abc123"
}
```

| HTTP status | `error` code | Produced by |
|---|---|---|
| 401 | _(FastAPI default)_ | `get_current_user` / `get_api_key` on missing/invalid credentials |
| 403 | `password_required` | `SharePasswordRequired` — password-protected share accessed without unlock |
| 404 | `not_found` | `ShareNotFoundError` |
| 429 | `rate_limit_exceeded` | `RateLimitError` — includes `Retry-After` header |
| 500 | `internal_error` | Catch-all `Exception` handler |

`request_id` is propagated by `RequestTrackingMiddleware` and the `request_id_var` context variable from `core/logging_config.py`.

## Rate limits

Rate limiting is delegated to the Postgres RPC `check_rate_limit` via the helpers in `core/rate_limit.py`. Buckets are per-IP (and per-slug for password unlock). `get_client_ip` (`app/dependencies.py`) trusts only the `CF-Connecting-IP` header, and falls back to the socket peer (`request.client.host`) when it is absent. `X-Forwarded-For` and `X-Real-IP` are ignored because any client can set them.

- Server-side callers (such as the frontend's SSR requests) share their own IP unless they forward the visitor's `CF-Connecting-IP` header with each request.
- The origin must accept traffic only from Cloudflare's IP ranges. Otherwise a client can reach it directly and set `CF-Connecting-IP` to any value, which defeats per-IP rate limiting.

| Scope | Limit | Window | Fail mode | Source |
|---|---|---|---|---|
| Upload / publish / multi-upload / batch / CLI upload / comments | 10 requests | 1 minute | fail-open | `check_upload_rate_limit` (`core/rate_limit.py:82`) |
| Analytics tracking | 60 requests | 1 minute | fail-open | `check_analytics_rate_limit` (`core/rate_limit.py:97`) |
| oEmbed | 60 requests | 1 minute | fail-open | `check_oembed_rate_limit` (`core/rate_limit.py:92`) |
| Password unlock (`/shares/{slug}/unlock`) | 5 attempts | 10 minutes | fail-closed | `check_password_rate_limit` (`core/rate_limit.py:87`) |

---

## Health

Defined inline on the app in `app/main.py`. No prefix.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | Public | Liveness probe — `{"status":"ok","service":"dropitx-api"}` (`app/main.py:171`). |
| GET | `/health/deep` | Public | Deep probe — verifies Supabase DB connectivity + latency. Returns `status:"ok"\|"degraded"` and a `checks.database` block (`app/main.py:177`). |

---

## v1 — Documents (API key)

Source: `app/v1/documents.py` (router prefix `/documents`, mounted under `/api/v1`). All routes require an API key via `get_api_key`. Documents are stored in the `shares` Supabase Storage bucket. Models `DocumentCreate` / `DocumentUpdate` / `DocumentResponse` are defined inline at `app/v1/documents.py:32,49,59`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/documents` | Create document owned by the API-key holder. Body `DocumentCreate`. Returns `DocumentResponse` (201). |
| GET | `/api/v1/documents` | List documents — filtered to the user, or to the team when a `sht_` key is used. Query: `page`, `limit` (≤100). |
| GET | `/api/v1/documents/{slug}` | Get a single document by slug. |
| PATCH | `/api/v1/documents/{slug}` | Update document; saves a revision first. Body `DocumentUpdate`. |
| DELETE | `/api/v1/documents/{slug}` | Delete document and its storage object (204). |

Team keys (`sht_`): a private or password-protected team share gives the same 404 as a missing document on every route that reads or writes its content (GET, PATCH, revisions, restore), and the listing leaves it out. A team key cannot change a share's privacy: a PATCH that sets `is_private` is refused with 403. PATCH never changes a password. Personal keys (`shk_`) are unchanged.

`DocumentCreate` fields: `content` (1–5 MB), `filename?`, `title?`, `is_private`, `encrypted`, `encryption_iv?`, `encryption_salt?`, `burn_after_reading`, `one_time_download`, `expires_in?` (seconds).

## v1 — API Keys (JWT)

Source: `app/v1/keys.py` (router prefix `/keys`, mounted under `/api/v1`). All routes require a JWT. Models from `models/api_key.py`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/keys` | Create API key. Body `ApiKeyCreate(name, team_id?)`. Team keys (`sht_`) require editor+ membership. Returns `ApiKeyCreateResponse` including the **raw key once** (201). |
| GET | `/api/v1/keys` | List the caller's non-revoked keys; optional `?team_id=` filter. Returns `ApiKeyResponse[]`. |
| DELETE | `/api/v1/keys/{key_id}` | Soft-delete (revoke) a key owned by the caller (204). |

## v1 — Profile (JWT)

Source: `app/v1/profile.py`. Authenticates with a Firebase token, not an API key.

| Method | Path | Description |
|---|---|---|
| PUT | `/api/v1/profile` | Set the caller's display name. Body `ProfileUpdate {display_name}`, trimmed, 1-100 characters (422 otherwise). Creates the caller's `user_profiles` row when missing. Returns `ProfileResponse {display_name, avatar_url}` only. |

## v1 — Revisions (API key)

Source: `app/v1/revisions.py` (router prefix `/documents/{slug}/revisions`, mounted under `/api/v1`). All routes require an API key. Models from `models/share.py` (`ShareRevision`, `RevisionListResponse`) and inline `RestoreResponse`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/documents/{slug}/revisions` | List revisions newest-first. Query: `page`, `limit`. Returns `RevisionListResponse`. |
| GET | `/api/v1/documents/{slug}/revisions/{revision}` | Get a specific revision. Returns `ShareRevision`. |
| POST | `/api/v1/documents/{slug}/revisions/{revision}/restore` | Restore a revision; creates a new revision and overwrites storage. Returns `RestoreResponse`. |

---

## Dashboard — My shares and favorites (JWT)

Sources: `app/dashboard/shares.py`, `app/v1/favorites.py`. Both authenticate with a Firebase token (not an API key), although favorites sit under `/api/v1`. Items are `ShareMeta` (`models/share.py`), built field by field: no content, `password_hash` or `delete_token`; `has_password` instead.

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard/shares?page=1&limit=20` | The caller's own shares, newest first, private and expired included. `page` >= 1, 1 <= `limit` <= 100 (422 otherwise). Returns `{items, total, page, limit}`. |
| GET | `/api/dashboard/analytics/top-shares?limit=10` | `{totals: {share_count, total_views, total_size, unique_views, shares_with_views}, top: [{share_id, slug, title, total_views, unique_views}]}`. `totals` cover all the caller's shares (private, expired and burned included; `total_views` sums `shares.view_count`, a missing size counts as 0; `unique_views` and `shares_with_views` count the last 30 calendar days (UTC) of views across all of them). `top` ranks unexpired shares by views in the last 30 days. 1 <= `limit` <= 50 (422 otherwise). Source: `app/dashboard/analytics.py`. |
| GET | `/api/dashboard/shares/{slug}/analytics?days=30` | Owner only; any other caller gets the same 404 as a missing slug. Returns `{share: {slug, title, filename}, days, summary, timeseries, referrers, geo}`: `summary` = `{total_views, unique_views, views_today, views_7d, avg_daily_views}`, `timeseries` = one `{date, views, unique_views}` per day, zero-filled, oldest first; `referrers` = top 10 `{referrer_source, views}`; `geo` = top 10 `{country_code, views}` (views with no country omitted). 1 <= `days` <= 365 (422 otherwise). |
| GET | `/api/v1/favorites` | The caller's favorites, newest first: `ShareMeta` plus `favorited_at`. Private shares the caller does not own, and burned or expired shares the caller does not own, are omitted. |
| GET | `/api/v1/favorites/{share_id}` | `{favorited: bool}`; `false` for a non-owned private, burned or expired share. |
| POST | `/api/v1/favorites/{share_id}` | Favorite a share. Idempotent; returns `{favorited: true}`. A missing share, a malformed id and a private share that is not the caller's all give the same 404. |
| DELETE | `/api/v1/favorites/{share_id}` | Unfavorite. Idempotent; returns `{favorited: false}`. |

---

## Dashboard — Teams (JWT)

Source: `app/dashboard/teams.py` (no router-level prefix, mounted under `/api/dashboard`). All routes require a JWT. Role enforcement (`owner` / `editor` / `viewer`) is centralized in `app/dashboard/team_helpers.py`. `CreateTeamInput` from `models/team.py`.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/dashboard/teams` | member | List teams the caller belongs to. |
| POST | `/api/dashboard/teams` | any | Create team; caller becomes owner. Body `CreateTeamInput(name, slug?)` (201). |
| GET | `/api/dashboard/teams/{slug}` | member | Get team details plus the caller's `role`. |
| PATCH | `/api/dashboard/teams/{slug}` | owner | Update name/slug. Body: `{name?, slug?}`. |
| DELETE | `/api/dashboard/teams/{slug}` | owner | Delete team and associated data (204). |
| GET | `/api/dashboard/teams/{slug}/members` | member | List members (with display name + avatar). |
| PATCH | `/api/dashboard/teams/{slug}/members` | owner | Change member role via RPC `change_team_member_role`. Body: `{user_id, role}`. |
| DELETE | `/api/dashboard/teams/{slug}/members` | owner\* | Remove member (members can remove themselves). Body: `{user_id}`. |

## Dashboard — Team Invites (JWT)

Source: `app/dashboard/team_invites.py`. Routes are registered onto the `teams_router` via import side-effect (see `app/dashboard/router.py:6`) and thus also live under `/api/dashboard`. All require a JWT; invite mutations require editor+. Backed by RPCs `create_team_invite`.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/api/dashboard/teams/{slug}/invites` | member | List pending invites. Rows carry `token` only when the caller's team role is `owner`; for any other role the `token` key is absent. |
| POST | `/api/dashboard/teams/{slug}/invites` | editor+ | Create invite. Body: `{email, role="viewer"}` (201). |
| DELETE | `/api/dashboard/teams/{slug}/invites` | editor+ | Revoke invite. Body: `{invite_id}`. |
| POST | `/api/dashboard/teams/{slug}/invites/bulk` | editor+ | Bulk invite up to 50 emails. Body: `{emails[], role}`. |
| POST | `/api/dashboard/teams/{slug}/invites/{invite_id}/resend` | editor+ | Resend (rotates token if expired). |
| GET | `/api/dashboard/teams/{slug}/events` | member | Team audit events. Query: `limit` (≤200), `offset`. |
| GET | `/api/dashboard/teams/{slug}/shares` | member | Shares attached to the team. Query: `limit` (≤200), `offset`. |

## Dashboard — Custom Domains (JWT)

Source: `app/dashboard/domains.py` (mounted under `/api/dashboard`). All routes require a JWT; domain mutations require owner. Verification works via TXT record `_dropitx-verify.<domain> → <token>`. Models from `models/domain.py` (`AddDomainInput`, `UpdateDomainBrandInput`, `DomainVerificationStatus`).

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/api/dashboard/teams/{slug}/domains` | owner | Add domain; returns record + verification token. Body `AddDomainInput(domain)` (201). |
| GET | `/api/dashboard/teams/{slug}/domains` | member | List team domains. |
| GET | `/api/dashboard/teams/{slug}/domains/{domain_id}` | member | Get one domain. |
| DELETE | `/api/dashboard/teams/{slug}/domains/{domain_id}` | owner | Remove domain (204). |
| POST | `/api/dashboard/teams/{slug}/domains/{domain_id}/verify` | owner | Trigger DNS verification; returns `DomainVerificationStatus`. |
| PATCH | `/api/dashboard/teams/{slug}/domains/{domain_id}/brand` | owner | Update brand (logo/color/favicon). Body `UpdateDomainBrandInput`. |
| GET | `/api/dashboard/domains/resolve/{domain}` | Public | Internal reverse-proxy lookup (`include_in_schema=False`); resolves a custom domain to its team config. |

## Dashboard — Invitations (JWT)

Source: `app/dashboard/invitations.py`. The `invitations_router` is mounted under `/api/dashboard`; the `invite_actions_router` is exported as `invite_actions` and mounted under `/api` (see `app/main.py:152`). Backed by RPCs `accept_team_invite` / `decline_team_invite`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard/invitations` | List pending invites matching the caller's email. |
| GET | `/api/invites/{token}` | Look up an invite for the accept page: team name/slug, inviter name, role, status, expiry (public). Unknown token 404, pending past expiry 410. The invitee email is returned only when the caller's verified Firebase token email (`email_verified` true) matches; `email_matches` is `null` when anonymous, `false` for a non-match or unverified email. |
| POST | `/api/invite/accept` | Accept by token. Body: `{token}`. |
| POST | `/api/invite/decline` | Decline by token. Body: `{token}`. |

---

## Public — Shares

Source: `app/public/shares.py` (mounted under `/api`). Mixed auth.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/shares/{slug}` | Public (optional auth) | Share metadata and access state (`ShareMeta`): `has_password`, `burned`, `is_owner`, `has_owner`, `group_files[]` (password siblings listed with `has_password`; private, burned and expired ones hidden). Rate limited to 300/min per IP (429). No content, hash or delete token; never counts a view or burns. Private and not owner 404, expired 410. |
| GET | `/api/shares/{slug}/content` | Public (optional auth) | View content. Handles expiration (410), password protection, burn-after-reading, E2E metadata passthrough, and download-limit enforcement. A password-protected share returns `content: ""` and `password_protected: true` to everyone except its signed-in owner, who gets the real `content` (still with `password_protected: true`) and the same view-count, burn and one-time side effects as for an unprotected share. |
| DELETE | `/api/shares/{slug}` | Owner token | Delete share. Body `DeleteShareRequest?` with `delete_token`. A wrong token is 404 on a private share (same as a missing share) and 403 on a public one. |
| POST | `/api/shares/{slug}/set-password` | Owner token | Set or clear password. Body `SetPasswordRequest(password?, delete_token?)`. A wrong token is 404 on a private share (same as a missing share) and 403 on a public one. |
| POST | `/api/shares/{slug}/unlock` | Public | Verify password (rate-limited 5/10min). Body `UnlockRequest`. |
| POST | `/api/shares/{slug}/burn` | Owner token | Mark share consumed; 410 if already burned, for authorised callers only. Body `BurnShareRequest?`. A wrong token is 404 on a private share (same as a missing share, burned or not) and 403 on a public one. |
| GET | `/api/shares/{slug}/download` | Public | Download as file attachment. Supports `?password=` for protected shares. |
| GET | `/api/shares/{slug}/download-status` | Public | Availability, `max_downloads`, `download_count`, `burn_after_reading`, `expired`, `consumed`. |

## Public — Search / Analytics / oEmbed / QR / Languages

Sources: `app/public/search.py`, `app/public/analytics.py`, `app/public/oembed.py`, `app/public/qrcode.py`, `app/public/languages.py` (all mounted under `/api`). All public.

| Method | Path | Description |
|---|---|---|
| GET | `/api/search` | Full-text search via RPC `search_shares`. Query: `q` (2–200 chars), `page`, `limit` (≤100). |
| POST | `/api/analytics/track` | Record one view of a share page as a `share_views` row; does not change `view_count` (the content route counts views). Rate-limited in its own bucket (60/min per IP, separate from content reads; 429 when exceeded). Body `AnalyticsTrack(slug, referrer?, is_embed?)`. Returns **204** whether or not a view was recorded (private and unknown slugs record nothing). |
| GET | `/api/oembed` | oEmbed discovery for a share URL. Query: `url`, `maxwidth?`, `maxheight?`. Rate-limited 60/min. |
| GET | `/api/qr/{slug}` | QR code image for a share. |
| GET | `/api/languages` | Supported languages for syntax highlighting. |

## Public — Comments

Source: `app/public/comments.py`, included with `prefix="/shares"` (`app/public/router.py:28`) so the effective prefix is `/api/shares`. Models `CommentCreate` / `CommentResponse` / `CommentListResponse` inline.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/shares/{slug}/comments` | Public | Paginated comments. Query: `page`, `per_page` (≤100). Returns `CommentListResponse`. |
| POST | `/api/shares/{slug}/comments` | JWT optional | Add comment (rate-limited via upload bucket). Body `CommentCreate(author_name?, content, parent_id?)`. Returns `CommentResponse`. |

## Public — Versions (JWT, owner only)

Source: `app/public/versions.py` (mounted under `/api`). All routes verify share ownership via the JWT. Models inline (`VersionItem`, `VersionListResponse`, `RestoreResponse`).

| Method | Path | Description |
|---|---|---|
| GET | `/api/shares/{slug}/versions` | List versions. Returns `VersionListResponse`. |
| GET | `/api/shares/{slug}/versions/{version_num}` | Get one version. Returns `VersionItem`. |
| POST | `/api/shares/{slug}/versions/{version_num}/restore` | Restore a version (creates a new version). Returns `RestoreResponse`. |

## Public — Encryption

Source: `app/public/encryption.py` (mounted under `/api`). AES-256-GCM + PBKDF2, zero-knowledge (keys never leave the client/URL fragment). Models inline (`KeyBundleResponse`, `EncryptionInfoResponse`, `EncryptShareRequest`, `ReencryptShareRequest`, `EncryptResponse`).

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/encryption/generate-key` | Public | Generate `{key, iv, salt}` bundle for client-side encryption. |
| GET | `/api/shares/{slug}/encryption-info` | Public | Encryption metadata (IV, salt, has_password) — never the key. Returns `EncryptionInfoResponse`. |
| POST | `/api/shares/{slug}/encrypt` | Owner token | Encrypt an existing plaintext share with a password. Body `EncryptShareRequest(password, delete_token?)`. Returns `EncryptResponse`. |
| POST | `/api/shares/{slug}/reencrypt` | Owner token | Re-encrypt with a new password; the signed-in owner or the delete token, plus `old_password`. 401 with neither; a wrong token is 404 on a private share and 403 on a public one. Body `ReencryptShareRequest(old_password, new_password, delete_token?)`. |

## Public — Preview

Source: `app/public/preview.py` (mounted under `/api`). Public. `PreviewType` is `image | pdf | code | markdown | video | audio | text | unsupported`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/shares/{slug}/preview` | Structured preview without downloading. Query: `max_lines` (10–1000, default 100). Returns `PreviewResponse` (`preview_type`, `content_url`, optional `content`/`language`/`thumbnail_url`). |

## Public — Explore / Stars / Profiles

Sources: `app/public/explore.py`, `app/public/stars.py`, `app/public/profiles.py` (mounted under `/api`).

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/explore` | Public | Browse public shares. Query: `page`, `limit` (≤100), `tag?`, `sort` (`trending\|recent\|views\|stars`). |
| GET | `/api/explore/tags` | Public | All tags with counts. Query: `limit` (≤200). |
| GET | `/api/explore/trending` | Public | Top trending shares. Query: `limit` (≤50). |
| GET | `/api/shares/{slug}/star` | JWT optional | Star count + whether the caller has starred. |
| POST | `/api/shares/{slug}/star` | JWT | Star a share. |
| DELETE | `/api/shares/{slug}/star` | JWT | Unstar a share. |
| GET | `/api/u/{username}` | Public | Public profile. |
| GET | `/api/u/{username}/shares` | Public | A user's public shares. Query: `page`, `limit` (≤100), `sort` (`recent\|views\|stars`). |

## Public — File Requests (uploader-facing)

Source: `app/public/file_requests.py` (mounted under `/api`). Public/anonymous — these are the endpoints uploaders hit via a request link.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/requests/{slug}` | Public | Request info for uploaders (title, limits, expiry, `require_name/email`). |
| POST | `/api/requests/{slug}/upload` | Public (anonymous) | Upload a file to a request (rate-limited via upload bucket). Multipart: `file`, optional `uploader_name`, `uploader_email`. |

---

## Internal — Publish (JWT)

Source: `app/internal/publish.py` (mounted under `/api`). Both routes require a JWT and hit the upload rate-limit bucket. Models inline (`PublishRequest`, `UpdatePublishRequest`, `PublishResponse`).

| Method | Path | Description |
|---|---|---|
| POST | `/api/publish` | Publish editor HTML. Body `PublishRequest(content, …)`. Returns `PublishResponse(slug, url, …)`. |
| PUT | `/api/publish/{slug}` | Update an existing share; saves previous version to history. Body `UpdatePublishRequest`. Returns `PublishResponse`. |

`PublishRequest` notable fields: `content` (1–10 MB), `filename?`, `title?`, `custom_slug?`, `max_downloads?`, `expires_in?` (`1h\|6h\|24h\|7d\|30d` or seconds), `encrypted`, `encryption_iv?`, `encryption_salt?`, `burn_after_reading`, `one_time_download`, `password?`, `language?`.

## Internal — Upload (JWT optional)

Source: `app/internal/upload.py` (mounted under `/api`). Optional JWT (associates file with the user when present). Both routes hit the upload rate-limit bucket.

| Method | Path | Description |
|---|---|---|
| POST | `/api/upload` | Upload a single file (multipart `file`). Query/form options include `encrypted`, `encryption_iv`, `encryption_salt`, `burn_after_reading`, `one_time_download`, `expires_in`, `max_downloads`, `password`, `language`. |
| POST | `/api/upload/batch` | Upload up to 20 files as a group; returns a group slug + per-file URLs. Multipart `files[]`, `max_downloads?`, `expires_in?`, `password?`. |

## Internal — Multi-file Upload (JWT optional)

Source: `app/internal/multi_upload.py` (mounted under `/api`). Model `MultiFileResponse` inline.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/upload/multi` | JWT optional | Upload up to 20 files (`_MAX_FILES`) as a single share. Multipart: `files[]`, `title?`, `custom_slug?`, `is_private?`, `password?`. Returns `MultiFileResponse(slug, url, delete_token, files[], file_count)`. |
| GET | `/api/shares/{slug}/files` | Public | List files attached to a multi-file share. |

## Internal — Images (JWT)

Source: `app/internal/images.py` (mounted under `/api`).

| Method | Path | Description |
|---|---|---|
| POST | `/api/images/upload` | Upload an editor image. Max 5 MB; allowed types PNG/JPG/GIF/WebP. Requires JWT. |

## Internal — Download (Public)

Source: `app/internal/download.py` (mounted under `/api`).

| Method | Path | Description |
|---|---|---|
| GET | `/api/download/group/{slug}` | Stream all files in a share group as a single ZIP. 404 if group has no files. |

## Internal — File Requests (owner, JWT)

Source: `app/internal/file_requests.py` (mounted under `/api`). Owner-side management of request links (the uploader-facing pair is under _Public — File Requests_ above). Note: although these are mounted via `internal_router` at `/api`, their paths carry the `/dashboard` segment, so the full paths are `/api/dashboard/requests…`. Models from `models/file_request.py`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/requests` | Create a request link. Body `FileRequestCreate(title?, description?, max_files, max_file_size_mb, expires_in, require_name, require_email)`. |
| GET | `/api/dashboard/requests` | List the caller's file requests. |
| GET | `/api/dashboard/requests/{request_id}/uploads` | List uploads for one request (ownership-verified). |
| PATCH | `/api/dashboard/requests/{request_id}` | Update a request (title/description/limits/active). Body: JSON patch. |
| DELETE | `/api/dashboard/requests/{request_id}` | Delete a request and all its uploads. |

## Internal — CLI Upload (API key optional)

Source: `app/internal/cli_upload.py` (router prefix `/cli`, mounted under `/api`). Designed for `curl`-friendly CLI usage (multipart, raw body, or piped text). Optional `X-API-Key` header links the upload to a user. Both routes hit the upload rate-limit bucket and return the share URL in both the JSON body and `X-DropItX-URL` / `X-DropItX-Slug` headers.

| Method | Path | Description |
|---|---|---|
| POST | `/api/cli/upload` | Upload a file or raw body. Form/query: `file?`, `password?`, `expires?`, `burn?`, `slug?`, `X-API-Key?`. |
| POST | `/api/cli/upload/text` | Upload text directly (for pipes). Form: `content` (required), `filename?`, `password?`, `expires?`, `burn?`, `slug?`, `X-API-Key?`. |

<!-- VERIFY: CLI upload docstrings reference https://api.dropitx.com as the example host — confirm against the production deployment before publishing client examples. -->

---

## Representative request/response shapes

**Create a document (API key):**

```bash
curl -X POST https://api.dropitx.com/api/v1/documents \
  -H "Authorization: Bearer shk_xxx" \
  -H "Content-Type: application/json" \
  -d '{"content": "# hello", "filename": "readme.md"}'
```

```json
{
  "id": "uuid",
  "slug": "abc123",
  "filename": "readme.md",
  "content": "# hello",
  "is_private": false,
  "view_count": 0,
  "encrypted": false,
  "burn_after_reading": false,
  "one_time_download": false,
  "created_at": "2026-08-09T12:00:00Z",
  "updated_at": "2026-08-09T12:00:00Z"
  }
```

**Create an API key (JWT) — raw key returned once:**

```json
{
  "id": "uuid",
  "name": "CI key",
  "key_prefix": "shk_abc",
  "key": "shk_abcdefghijklmnopqrstuvwxyz0123456789",
  "team_id": null,
  "created_at": "2026-08-09T12:00:00Z"
}
```

**Publish from the editor (JWT)** returns `PublishResponse`:

```json
{
  "slug": "abc123",
  "url": "https://dropitx.com/s/abc123",
  "filename": null,
  "title": "My snippet",
  "encrypted": false,
  "burn_after_reading": false,
  "one_time_download": false,
  "expires_at": "2026-08-16T12:00:00Z",
  "password_protected": false
}
```

## OpenAPI / introspection

The full machine-readable contract is generated by FastAPI from the same decorators documented here:

- Swagger UI — `GET /docs`
- ReDoc — `GET /redoc`
- OpenAPI JSON — `GET /openapi.json`

Tag groupings (set in `app/main.py:28-51`) match the section headings above.
