# Constraints

Extracted from the 2 SPEC-classified documents: `docs/API.md` and `docs/2026-08-12-firebase-auth-backend-api-design.md`.

---

## API.md — DropItX API Reference (Supabase-JWT era)

### Router mounts
- source: docs/API.md
- type: api-contract
- content: All routes aggregated in `app/main.py:150-154`. `/api/v1` → `v1_router` (`app/v1/router.py`, API key + JWT for keys). `/api/dashboard` → `dashboard_router` (`app/dashboard/router.py`, JWT). `/api` → `invite_actions` (`app/dashboard/invitations.py`, JWT). `/api` → `public_router` (`app/public/router.py`, public/optional JWT). `/api` → `internal_router` (`app/internal/router.py`, mixed JWT/optional/API-key). Root → inline `@app.get` (public). The `/api` prefix is shared by `invite_actions`, `public_router`, and `internal_router`; disambiguated by route strings.

### Authentication mechanisms
- source: docs/API.md
- type: api-contract
- content: Two credential mechanisms via `Authorization: Bearer <token>`. JWT (Supabase Auth) — `get_current_user` (`app/dependencies.py:41`) verifies Supabase JWT against JWKS, returns `User(id, email)`; `get_optional_user` (`app/dependencies.py:58`) returns `User | None` without raising. API Key — `get_api_key` (`app/dependencies.py:70`) accepts `shk_`/`sht_` prefixed keys, looks up SHA-256 hash in `api_keys` table, rejects revoked keys and team keys whose owner is no longer a member, returns `ApiKeyAuth(user_id, key_id, team_id)`; raw key returned once at creation, only hash stored; `last_used_at` updated fire-and-forget. Auth labels used per endpoint: Public, JWT, JWT optional, API key, API key optional, Owner token (owner JWT or `delete_token` in body).
- note: <!-- VERIFY --> in source: production base URL referenced as `https://api.dropitx.com` in CLI docstrings — confirm against deployed Render service.

### Error response envelope
- source: docs/API.md
- type: api-contract
- content: All unhandled exceptions normalized by handlers in `app/main.py:92-139` into `ErrorResponse` (`core/exceptions.py:8`): `{"error": "...", "detail": "...", "request_id": "..."}`. Status/code map — 401 (FastAPI default) from `get_current_user`/`get_api_key`; 403 `password_required` from `SharePasswordRequired`; 404 `not_found` from `ShareNotFoundError`; 429 `rate_limit_exceeded` from `RateLimitError` (includes `Retry-After` header); 500 `internal_error` catch-all. `request_id` propagated by `RequestTrackingMiddleware` / `request_id_var` (`core/logging_config.py`).

### Rate limits
- source: docs/API.md
- type: nfr
- content: Delegated to Postgres RPC `check_rate_limit` via `core/rate_limit.py`. Buckets per-IP (per-slug for password unlock), IP resolved `X-Forwarded-For` → `X-Real-IP` → `request.client.host` (`get_client_ip`, `app/dependencies.py:149`). Upload/publish/multi-upload/batch/CLI-upload/comments: 10 req/1 min, fail-open (`core/rate_limit.py:82`). Analytics tracking: 60 req/1 min, fail-open (`core/rate_limit.py:97`). oEmbed: 60 req/1 min, fail-open (`core/rate_limit.py:92`). Password unlock (`/shares/{slug}/unlock`): 5 attempts/10 min, fail-closed (`core/rate_limit.py:87`).

### Health endpoints
- source: docs/API.md
- type: api-contract
- content: `GET /health` (public) — liveness, `{"status":"ok","service":"dropitx-api"}` (`app/main.py:171`). `GET /health/deep` (public) — verifies Supabase DB connectivity + latency, returns `status:"ok"|"degraded"` and `checks.database` block (`app/main.py:177`).

### v1 — Documents / API Keys / Revisions (API key / JWT)
- source: docs/API.md
- type: api-contract
- content: Documents (`app/v1/documents.py`, prefix `/documents` under `/api/v1`, API key required, storage in `shares` bucket): POST `/api/v1/documents` (create, 201), GET `/api/v1/documents` (list, filtered by user or team for `sht_` keys, `page`/`limit` ≤100), GET `/api/v1/documents/{slug}`, PATCH `/api/v1/documents/{slug}` (saves revision first), DELETE `/api/v1/documents/{slug}` (204). `DocumentCreate` fields: `content` (1–5 MB), `filename?`, `title?`, `is_private`, `encrypted`, `encryption_iv?`, `encryption_salt?`, `burn_after_reading`, `one_time_download`, `expires_in?`. API Keys (`app/v1/keys.py`, prefix `/keys`, JWT required): POST `/api/v1/keys` (`ApiKeyCreate(name, team_id?)`, team keys require editor+, returns raw key once, 201), GET `/api/v1/keys` (list non-revoked, optional `team_id` filter), DELETE `/api/v1/keys/{key_id}` (revoke, 204). Revisions (`app/v1/revisions.py`, prefix `/documents/{slug}/revisions`, API key required): GET list (newest-first, paginated), GET `/{revision}`, POST `/{revision}/restore`.

### Dashboard — Teams / Invites / Domains / Invitations (JWT)
- source: docs/API.md
- type: api-contract
- content: Teams (`app/dashboard/teams.py`, `/api/dashboard`, JWT, role enforcement in `team_helpers.py`): GET/POST `/api/dashboard/teams` (member/any), GET/PATCH/DELETE `/api/dashboard/teams/{slug}` (member/owner/owner), GET `/api/dashboard/teams/{slug}/members` (member), PATCH via RPC `change_team_member_role` (owner), DELETE member (owner, or self-removal). Invites (`team_invites.py`, registered via import side-effect onto `teams_router`): GET/POST/DELETE `/api/dashboard/teams/{slug}/invites` (member/editor+/editor+), POST `.../invites/bulk` (≤50 emails, editor+), POST `.../invites/{invite_id}/resend` (editor+), GET `.../events` (audit, ≤200 limit), GET `.../shares` (≤200 limit). Domains (`domains.py`, JWT, mutations require owner): POST/GET/DELETE `/api/dashboard/teams/{slug}/domains`, POST `.../verify`, PATCH `.../brand`, GET `/api/dashboard/domains/resolve/{domain}` (public, `include_in_schema=False`, reverse-proxy lookup). Invitations (`invitations.py`): GET `/api/dashboard/invitations`, POST `/api/invite/accept` / `/api/invite/decline` (backed by RPCs `accept_team_invite`/`decline_team_invite`).

### Public — Shares / Search / Comments / Versions / Encryption / Preview / Explore / File Requests
- source: docs/API.md
- type: api-contract
- content: Shares (`app/public/shares.py`, mixed auth): GET `/api/shares/{slug}/content` (public; 410 expired, 403 `password_protected`, burn-after-reading, E2E metadata, download-limit enforcement), DELETE (owner token), POST `/set-password` (owner token), POST `/unlock` (public, rate-limited 5/10min), POST `/burn` (owner token, 410 if already burned), GET `/download` (public, supports `?password=`), GET `/download-status` (public). Search/Analytics/oEmbed/QR/Languages (all public): GET `/api/search` (RPC `search_shares`, `q` 2–200 chars), POST `/api/analytics/track` (fail-open 60/min, always 200), GET `/api/oembed`, GET `/api/qr/{slug}`, GET `/api/languages`. Comments (`app/public/comments.py`, effective prefix `/api/shares`): GET (public, paginated), POST (JWT optional, rate-limited via upload bucket). Versions (`app/public/versions.py`, owner-verified JWT): GET list/one, POST `/restore`. Encryption (`app/public/encryption.py`, AES-256-GCM + PBKDF2, zero-knowledge): POST `/generate-key` (public), GET `/encryption-info` (public, never the key), POST `/encrypt` (owner token), POST `/reencrypt` (password holder). Preview (`app/public/preview.py`, public): GET `/preview` (`max_lines` 10–1000, default 100; `PreviewType` = image|pdf|code|markdown|video|audio|text|unsupported). Explore/Stars/Profiles: GET `/api/explore`, `/api/explore/tags`, `/api/explore/trending` (public); GET/POST/DELETE `/api/shares/{slug}/star` (JWT optional / JWT / JWT); GET `/api/u/{username}`, `/api/u/{username}/shares` (public). File Requests (uploader-facing, public): GET `/api/requests/{slug}`, POST `/api/requests/{slug}/upload` (anonymous, rate-limited).

### Internal — Publish / Upload / Multi-upload / Images / Download / File Requests (owner) / CLI
- source: docs/API.md
- type: api-contract
- content: Publish (`app/internal/publish.py`, JWT, rate-limited): POST `/api/publish` (`PublishRequest`, content 1–10 MB, `custom_slug?`, `max_downloads?`, `expires_in?` presets or seconds, `encrypted`, `burn_after_reading`, `one_time_download`, `password?`, `language?`), PUT `/api/publish/{slug}`. Upload (`app/internal/upload.py`, optional JWT, rate-limited): POST `/api/upload` (multipart, up to 50 MB per README/architecture context), POST `/api/upload/batch` (≤20 files). Multi-upload (`app/internal/multi_upload.py`, optional JWT): POST `/api/upload/multi` (≤20 files, `MultiFileResponse`), GET `/api/shares/{slug}/files` (public). Images (`app/internal/images.py`, JWT): POST `/api/images/upload` (≤5 MB, PNG/JPG/GIF/WebP). Download (`app/internal/download.py`, public): GET `/api/download/group/{slug}` (ZIP stream, 404 if empty). File Requests owner-side (`app/internal/file_requests.py`, mounted via `internal_router` at `/api` but paths carry `/dashboard` segment): POST `/api/requests`, GET `/api/dashboard/requests`, GET `.../{request_id}/uploads`, PATCH/DELETE `.../{request_id}`. CLI Upload (`app/internal/cli_upload.py`, prefix `/cli`, optional `X-API-Key`, rate-limited): POST `/api/cli/upload`, POST `/api/cli/upload/text`.
- note: <!-- VERIFY --> in source: CLI upload docstrings reference `https://api.dropitx.com` as example host — confirm against production deployment.

### Representative request/response shapes & OpenAPI introspection
- source: docs/API.md
- type: api-contract
- content: Example shapes given for POST `/api/v1/documents` (API key), POST `/api/v1/keys` (JWT, raw key returned once), POST `/api/publish` (JWT) → `PublishResponse`. Full machine-readable contract generated by FastAPI: Swagger UI `GET /docs`, ReDoc `GET /redoc`, OpenAPI JSON `GET /openapi.json`. Tag groupings set in `app/main.py:28-51` match the API.md section headings.

---

## Firebase Auth — Backend Auth-API Design (docs/2026-08-12-firebase-auth-backend-api-design.md)

- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- header metadata: Date 2026-08-12; Status "Design (awaiting spec sign-off)" (not Accepted — not a locked ADR); Scope "Backend only — identity model, schema migration, user provisioning, `/api/auth/session`"; Sibling doc `docs/2026-08-12-firebase-google-login-implementation.md` (frontend plan, out of scope here); Predecessor commit `da48448` (Firebase JWT verification shipped in `core/security.py`).

### Context / problem being solved
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: nfr
- content: `verify_firebase_jwt` + `get_current_user` already accept Firebase ID tokens across 17 route modules, but the backend cannot yet serve a Firebase user end-to-end: (1) no provisioning — nothing creates a row in `auth.users`/`user_profiles` on first login; (2) schema type mismatch — `user_id` graph is `UUID`, assumed-true under Supabase but false under Firebase (Firebase Google-sign-in `sub` is a ~28-char string; every authenticated write rejects a Firebase user); (3) no auth surface — no `/me`/`/session` endpoint exists.

### Firebase Auth Backend — Design Decisions (non-ADR, unlocked)
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: schema
- content: Doc's own "Decisions (locked during brainstorming)" list (captured here verbatim since the doc is SPEC-typed, not ADR — see `decisions.md` for the routing rationale): (1) Scope — backend auth-API first, FE migration is a separate fast-follow spec; (2) Data preservation — user store is fresh/disposable, schema may be retyped freely; (3) Identity model — Firebase uid stored as `TEXT` everywhere (Option A), no mapping table, no derived UUID; (4) Provisioning — explicit `GET /api/auth/session` provisions + returns profile, `get_current_user` verifies and looks up but does not write.

### Identity model & schema migration
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: schema
- content: `auth.users` becomes minimal, keyed by Firebase uid: `auth.users(id TEXT PRIMARY KEY, email TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())`, no default on `id` (comes from JWT `sub`). Profile fields stay in `user_profiles`. 12 tables to retype `user_id UUID` → `user_id TEXT` in `infra/init/01_schema.sql`: shares, api_keys, team_members, team_events, share_groups, share_revisions, share_comments, share_stars, tags, folders, user_profiles, file_requests (each with its own `ON DELETE` clause preserved). RPC functions retyped: `p_user_id`/`p_invited_by` params UUID→TEXT, `RETURNS TABLE(... user_id UUID ...)` → TEXT, `has_user_starred(p_share_id UUID, p_user_id UUID)` → `p_user_id TEXT`. `auth.uid()` stub (`infra/init/01_schema.sql`, `k8s/auth-stub.sql`) returns TEXT (was `NULL::UUID`) — cosmetic since the PostgREST shim doesn't enforce RLS. Migration mechanics for existing DBs via `migrations/NNNN_firebase_uid_text.sql`: drop 12 FK constraints → retype `auth.users.id` and the 12 `user_id` columns to TEXT → recreate FKs and RPCs → recreate `auth.uid()`. Non-destructive: UUID values are valid TEXT. Audit task noted: confirm `migrations/002_create_share_comments.sql`'s no-FK `user_id UUID` variant is dead under init's `CREATE TABLE IF NOT EXISTS`; grep code for `UUID(user_id)` casts / pydantic `UUID` typing on user identity (expected nil impact, `User.id: str` today).

### API contract — GET /api/auth/session
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: api-contract
- content: New module `app/auth/` (`session.py`, `router.py`), registered `app.include_router(auth_router, prefix="/api/auth")`. Request: `GET /api/auth/session`, `Authorization: Bearer <firebase_id_token>`. Flow: (1) verify Firebase JWT → claims `{sub, email, email_verified, name, picture}`; (2) `upsert auth.users(id=sub, email=email)` with `ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email`; (3) `upsert user_profiles(user_id=sub)` with `ON CONFLICT (user_id) DO NOTHING` (never clobbers user edits); (4) return the profile. 200 response: `{id, email, email_verified, profile: {user_id, username, display_name, bio, avatar_url, is_public}}` (new-user fields NULL/false). Idempotent; safe on every app load / token refresh. Method choice: GET (conventional `/session`/`/me` pattern; upsert is an idempotent side-effect) — doc notes "switch to POST if the team prefers 'this mutates' to be explicit" as an open option.

### Dependency refactor (app/dependencies.py)
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: api-contract
- content: New `get_firebase_claims(request) -> dict` — verifies JWT, returns payload, no DB access. Refactored `get_current_user(request) -> User` — built on `get_firebase_claims` + one indexed `SELECT` on `auth.users` by `id`, no writes; missing row → `401 {"detail": "User not provisioned", "code": "user_not_provisioned"}`. `get_optional_user` — unchanged shape; missing row treated as anonymous (`None`). Cost: one PK lookup per protected request (sub-ms on TEXT PK); no cache in v1 (YAGNI), in-process LRU keyed by `(uid, token exp)` noted as a future optimization. `User.id` already comes from `payload["sub"]`, so no route reading `user.id` needs editing — only dependency internals change.

### Error handling matrix
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: api-contract
- content: Missing/invalid/expired token → 401 "Invalid or expired token" (existing). Valid token, un-provisioned user on a protected route → 401 `{"code": "user_not_provisioned"}`. `/api/auth/session` itself never returns `user_not_provisioned` (it provisions); only 401 on bad tokens. Concurrent first-call race → absorbed by `ON CONFLICT`, no 500. Firebase cert fetch failure (network) → 500 with clear message (existing path; `www.googleapis.com` is HA).

### Testing plan
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: protocol
- content: New `tests/test_auth_session.py` (live Postgres + MinIO, run after `docker compose up -d`): `/auth/session` with mocked-verify Firebase JWT → 200, rows created in `auth.users` + `user_profiles`; second call with same uid → same rows, not duplicated, email update respected; protected route (e.g. `/api/v1/keys`) before `/auth/session` → 401 `user_not_provisioned`, after → succeeds; migration test applies `NNNN_firebase_uid_text.sql` on a UUID-keyed fixture, asserts existing values preserved (UUID-as-text). `verify_firebase_jwt` monkeypatched in tests to return a fixed `{sub, email}` — no real Firebase round-trip in CI.

### Rollout / environment
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: nfr
- content: `FIREBASE_PROJECT_ID=dropitx-io` already required by `verify_firebase_jwt`; absence makes every login 401 with "FIREBASE_PROJECT_ID is not configured" — doc flags this as "the single most critical env var." Must be set in `.env.example`, `.env.local.example`, and the deployed environment (Dokploy / k8s). Schema: fresh boots get TEXT from `infra/init/01_schema.sql`; existing DBs run `migrations/NNNN_firebase_uid_text.sql`. No other new env vars.

### Defaults chosen (open for spec review) / explicit out-of-scope
- source: docs/2026-08-12-firebase-auth-backend-api-design.md
- type: nfr
- content: Defaults pending sign-off: `GET /api/auth/session` (not POST); no in-process lookup cache in v1; `user_profiles` provisioned with NULL `username`/`display_name`; `signOut`/revocation remain client-side (stateless JWT, Firebase SDK owns token lifecycle). Explicit non-goals (deferred to FE fast-follow spec, cross-ref `docs/2026-08-12-firebase-google-login-implementation.md`): Google sign-in wiring, `authenticatedFetch`, ripping out Supabase auth (`utils/supabase/*`, `app/(public)/auth/*`, `middleware.ts`); session/cookie vs Bearer-header strategy; additional providers (email/password, GitHub — Firebase uids are provider-agnostic for free, wiring is FE work); profile-completion UX (username picker).
