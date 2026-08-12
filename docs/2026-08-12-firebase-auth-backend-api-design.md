# Firebase Auth — Backend Auth-API Design

- **Date:** 2026-08-12
- **Status:** Design (awaiting spec sign-off)
- **Scope:** Backend only — identity model, schema migration, user provisioning, `/api/auth/session`
- **Sibling doc:** `docs/2026-08-12-firebase-google-login-implementation.md` (frontend plan — out of scope here, fast-follow spec)
- **Predecessor commit:** `da48448` (Firebase JWT verification shipped in `core/security.py`)

## Context

`verify_firebase_jwt` + `get_current_user` already accept Firebase ID tokens, and 17 route modules use them. But the backend cannot actually serve a Firebase user end-to-end:

1. **No provisioning.** Nothing creates a row in `auth.users` / `user_profiles` on first login.
2. **Schema type mismatch.** The whole `user_id` graph is `UUID` keyed on the assumption (documented in `infra/init/01_schema.sql:10-13`) that JWT `sub` is a UUID — true under Supabase, **false under Firebase**. Firebase Google-sign-in `sub` is a ~28-char string. Every authenticated write that sets `user_id` rejects a Firebase user.
3. **No auth surface.** No `/me` / `/session` endpoint exists; the frontend has no way to fetch or provision a profile.

## Goals

- Make a Firebase (Google) user fully functional against the API: verify → provision → read/write.
- Resolve the UUID/TEXT identity mismatch with the simplest model the constraints allow.
- Expose a minimal, idempotent auth surface the frontend can call on load.

## Non-goals (deferred to FE fast-follow spec)

- Google sign-in wiring, `authenticatedFetch`, ripping Supabase auth (`utils/supabase/*`, `app/(public)/auth/*`, `middleware.ts`).
- Session/cookie vs Bearer-header strategy (frontend concern).
- Additional providers (email/password, GitHub). Firebase uids unify providers, so the model is provider-agnostic for free; wiring is FE work.

## Decisions (locked during brainstorming)

1. **Scope:** backend auth-API first; FE migration is a separate fast-follow spec.
2. **Data preservation:** user store is fresh/disposable — schema may be retyped freely.
3. **Identity model:** Firebase uid stored as `TEXT` everywhere (Option A). No mapping table, no derived UUID.
4. **Provisioning:** explicit `GET /api/auth/session` provisions + returns profile; `get_current_user` verifies and looks up but does **not** write.

## Data model & schema migration

### Identity = Firebase uid (`TEXT`)

`auth.users` becomes minimal, keyed by the Firebase uid:

```
auth.users(id TEXT PRIMARY KEY, email TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())
```

No default on `id` — it comes from the JWT `sub`. Profile fields (display_name, avatar_url, bio, username) stay in `user_profiles` as today; nothing is duplicated.

### Tables to retype (`infra/init/01_schema.sql`)

Every `user_id UUID REFERENCES auth.users(id)` becomes `user_id TEXT REFERENCES auth.users(id)`. Exact set (12 tables):

| Table | Line | ON DELETE | Notes |
|---|---|---|---|
| shares | 41 | SET NULL | |
| api_keys | 79 | CASCADE | |
| team_members | 112 | CASCADE | |
| team_events | 143 | SET NULL | |
| share_groups | 185 | SET NULL | |
| share_revisions | 199 | SET NULL | |
| share_comments | 220 | SET NULL | NULL = anonymous |
| share_stars | 248 | CASCADE | NOT NULL |
| tags | 258 | CASCADE | |
| folders | 279 | CASCADE | |
| user_profiles | 300 | CASCADE | NOT NULL UNIQUE |
| file_requests | 344 | CASCADE | NOT NULL |

### RPC functions to retype (`infra/init/02_rpc_functions.sql` + init)

- Every `p_user_id UUID` parameter → `TEXT` (accept-invite / remove-member / list-user-teams functions).
- `p_invited_by UUID` → `TEXT` (semantic user ref).
- `RETURNS TABLE(... user_id UUID ...)` → `TEXT`.
- `has_user_starred(p_share_id UUID, p_user_id UUID)` (init line 467) → `p_user_id TEXT`.
- Local vars for non-user ids (`v_team_id UUID`, `v_id UUID`) stay UUID — they reference teams/invitations, not users.

### `auth.uid()` stub

`infra/init/01_schema.sql` and `k8s/auth-stub.sql`: `auth.uid()` returns `TEXT` (was `NULL::UUID`). Cosmetic — the PostgREST shim does not enforce RLS — but kept consistent with the new identity type.

### Migration mechanics

`migrations/NNNN_firebase_uid_text.sql` for any existing DB:

1. Drop the 12 FK constraints referencing `auth.users(id)`.
2. `ALTER TABLE auth.users ALTER COLUMN id TYPE TEXT, ALTER COLUMN id DROP DEFAULT;`
3. For each of the 12 tables: `ALTER TABLE <t> ALTER COLUMN user_id TYPE TEXT;`
4. Recreate the 12 FKs (TEXT → TEXT), preserving each `ON DELETE` clause.
5. Recreate the retyped RPC functions (`CREATE OR REPLACE`).
6. Recreate `auth.uid()` returning TEXT.

**Non-destructive:** UUID values are valid TEXT, so existing rows survive (the data is disposable anyway, but the migration is safe on non-empty DBs).

### Audit task (planning)

- Confirm `migrations/002_create_share_comments.sql`'s `user_id UUID` (no-FK variant) is dead under init's `CREATE TABLE IF NOT EXISTS` — it is superseded; flag if any DB was bootstrapped from `migrations/` alone.
- Grep code for any `UUID(user_id)` cast / pydantic `UUID` typing on user identity. Identity flows as `str` today (`User.id: str`), so impact is expected to be nil — verify.

## API contract

### `GET /api/auth/session`

New module `app/auth/` (`session.py`, `router.py`), registered in `app/main.py`:

```
app.include_router(auth_router, prefix="/api/auth")
```

**Request**

```
GET /api/auth/session
Authorization: Bearer <firebase_id_token>
```

**Flow**

1. Verify Firebase JWT (`verify_firebase_jwt`) → claims `{ sub, email, email_verified, name, picture }`.
2. `upsert auth.users(id=sub, email=email)` — `ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email` (email may change).
3. `upsert user_profiles(user_id=sub)` — `ON CONFLICT (user_id) DO NOTHING` (never clobber user edits; username/display_name stay NULL until the user sets them).
4. Return the profile.

**200 response**

```json
{
  "id": "<firebase_uid>",
  "email": "user@example.com",
  "email_verified": true,
  "profile": {
    "user_id": "<firebase_uid>",
    "username": null,
    "display_name": null,
    "bio": null,
    "avatar_url": null,
    "is_public": false
  }
}
```

Idempotent; safe to call on every app load and on token refresh.

**Method choice:** `GET` — conventional `/session`/`/me` pattern; the upsert is an idempotent side-effect. Switch to `POST` if the team prefers "this mutates" to be explicit.

## Dependency refactor (`app/dependencies.py`)

- **`get_firebase_claims(request) -> dict`** *(new)* — verify the JWT and return the payload. No DB access.
- **`get_current_user(request) -> User`** — refactored on top of `get_firebase_claims` + one indexed `SELECT` on `auth.users` by `id`. **No writes.** Missing row → `401 {"detail": "User not provisioned", "code": "user_not_provisioned"}` so the FE knows to call `/auth/session`.
- **`get_optional_user`** — unchanged shape; a missing row is treated as anonymous (returns `None`), appropriate for `/api/upload`-style optional auth.

**Cost:** one PK lookup per protected request (sub-ms on a TEXT PK). No cache in v1 (YAGNI); note an in-process LRU keyed by `(uid, token exp)` as a future optimization.

**Identity code unchanged:** `User.id` already comes from `payload["sub"]`, so no route that reads `user.id` needs editing — only the dependency internals change.

## Error handling

| Case | Result |
|---|---|
| Missing / invalid / expired token | `401 Invalid or expired token` (existing) |
| Valid token, un-provisioned user on a protected route | `401 {"code": "user_not_provisioned"}` |
| `/api/auth/session` itself | never returns `user_not_provisioned` (it provisions); only 401 on bad tokens |
| Concurrent first-call race | `ON CONFLICT` absorbs it — no 500 |
| Firebase cert fetch failure (network) | 500 with clear message (existing path; `www.googleapis.com` is HA) |

## Testing

New `tests/test_auth_session.py` (live Postgres + MinIO, like the existing non-ASGI tests — run after `docker compose up -d`):

- `/auth/session` with a mocked-verify Firebase JWT → 200, `auth.users` + `user_profiles` rows created.
- Second call with same uid → same rows, not duplicated; email update is respected.
- Protected route (e.g. `/api/v1/keys`) before `/auth/session` → 401 `user_not_provisioned`; after → succeeds.
- Migration test: apply `NNNN_firebase_uid_text.sql` on a UUID-keyed fixture, assert existing values are preserved (UUID-as-text).

`verify_firebase_jwt` is monkeypatched in tests to return a fixed `{sub, email}` — no real Firebase round-trip in CI. Reuse whatever JWT-mocking fixture pattern already exists in `tests/` (confirm during planning).

## Rollout / environment

- **`FIREBASE_PROJECT_ID=dropitx-io`** — already required by `verify_firebase_jwt`; absence makes every login 401 with *"FIREBASE_PROJECT_ID is not configured"*. Ensure it is set in `.env.example`, `.env.local.example`, and the deployed environment (Dokploy / k8s). This is the single most critical env var.
- **Schema:** fresh boots get TEXT from `infra/init/01_schema.sql`; existing DBs run `migrations/NNNN_firebase_uid_text.sql`.
- No other new env vars.

## Defaults chosen (override during spec review if needed)

- `GET /api/auth/session` (not POST).
- No in-process lookup cache in v1.
- `user_profiles` provisioned with NULL `username` / `display_name` (schema allows); FE prompts later.
- `signOut` / revocation remain client-side (stateless JWT; Firebase SDK owns token lifecycle).

## Out of scope (FE fast-follow spec)

- Google sign-in (popup + redirect fallback), `AuthProvider`, `authenticatedFetch`.
- Removing Supabase auth: `utils/supabase/*`, `app/(public)/auth/{login,callback,confirm,reset-password,update-password}`, `middleware.ts`.
- Profile-completion UX (username picker).
