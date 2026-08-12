# Firebase Auth Backend API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the API fully serve a Firebase (Google) user end-to-end — retype the UUID user-identity graph to TEXT (Firebase uid), add provisioning, and expose `GET /api/auth/session`.

**Architecture:** Identity = Firebase uid stored as `TEXT` everywhere. A new `provision_firebase_user` RPC upserts `auth.users` + `user_profiles` race-free (`ON CONFLICT`). `GET /api/auth/session` verifies the JWT, calls the RPC, returns the profile. `get_current_user` becomes verify + lookup (no writes); an un-provisioned user gets `401`.

**Tech Stack:** FastAPI, asyncpg (via the hand-rolled PostgREST shim in `core/db.py`), PostgreSQL 16, Pydantic v2, pytest (mocked-DB style — `TestClient` + `dependency_overrides` + `@patch get_admin_client`, no live DB needed for route tests).

**Spec:** `docs/2026-08-12-firebase-auth-backend-api-design.md`

## Global Constraints

- `FIREBASE_PROJECT_ID=dropitx-io` must be set in the running environment (already required by `verify_firebase_jwt`).
- Data is **disposable** — schema may be retyped freely; the non-destructive migration is provided but re-initializing is acceptable.
- Conventional commits, no AI attribution. Branch: `firebase-auth-backend-api`.
- Test style: mocked DB (see `tests/test_file_requests.py`); do **not** introduce live-DB tests or new pytest plugins (no pytest-asyncio — use `asyncio.run` for async unit tests).
- Python 3.12+. No new dependencies.

---

## File Structure

**Schema / migration:**
- Modify: `infra/init/01_schema.sql` — `auth.users.id` → TEXT (15 user-ref columns → TEXT; `has_user_starred` param → TEXT)
- Modify: `infra/init/02_rpc_functions.sql` — retype 5 functions' user params/returns; **append** `provision_firebase_user`
- Modify: `k8s/auth-stub.sql` — `auth.uid()` returns TEXT
- Create: `migrations/007_firebase_uid_text.sql` — non-destructive retype (columns + views + functions)
- Create: `migrations/008_provision_firebase_user.sql` — the new RPC (standalone, for existing DBs)

**Code:**
- Modify: `app/dependencies.py` — add `get_firebase_claims`; refactor `get_current_user` (verify + lookup + `user_not_provisioned`)
- Create: `app/auth/__init__.py` (empty), `app/auth/session.py` (endpoint), `app/auth/router.py` (aggregator)
- Modify: `app/main.py` — register `auth_router` at `/api/auth`; refresh stale "Supabase Auth" copy

**Tests:**
- Create: `tests/test_dependencies.py` — unit tests for `get_firebase_claims` + `get_current_user`
- Create: `tests/test_auth_session.py` — route tests for `GET /api/auth/session`

### The 15 user-identity columns (across 13 tables)

| table.column | line | ON DELETE | nullable |
|---|---|---|---|
| shares.user_id | 41 | SET NULL | yes |
| api_keys.user_id | 79 | CASCADE | yes |
| teams.owner_id | 101 | CASCADE | yes |
| team_members.user_id | 112 | CASCADE | yes |
| team_invitations.invited_by | 126 | SET NULL | yes |
| team_events.user_id | 143 | SET NULL | yes |
| team_shares.shared_by | 158 | SET NULL | yes |
| share_groups.user_id | 185 | SET NULL | yes |
| share_revisions.user_id | 199 | SET NULL | yes |
| share_comments.user_id | 220 | SET NULL | yes |
| share_stars.user_id | 248 | CASCADE | NOT NULL |
| tags.user_id | 258 | CASCADE | yes |
| folders.user_id | 279 | CASCADE | yes |
| user_profiles.user_id | 300 | CASCADE | NOT NULL UNIQUE |
| file_requests.user_id | 344 | CASCADE | NOT NULL |

Auto-generated FK names follow `<table>_<col>_fkey`. Dependent views (must be dropped before retype, recreated after): `public_shares`, `trending_shares`, `team_invites`, `profiles`.

---

## Task 1: Retype user identity columns + functions to TEXT

**Files:**
- Modify: `infra/init/01_schema.sql` (lines 16-20, 41, 79, 101, 112, 126, 143, 158, 185, 199, 220, 248, 258, 279, 300, 344, ~469)
- Modify: `infra/init/02_rpc_functions.sql` (lines 22, 59, 71, 80, 115)
- Modify: `k8s/auth-stub.sql`
- Create: `migrations/007_firebase_uid_text.sql`

**Interfaces:** none (pure schema).

- [ ] **Step 1: Edit `infra/init/01_schema.sql` — `auth.users`**

Change lines 16-20 from:
```sql
CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
to:
```sql
CREATE TABLE IF NOT EXISTS auth.users (
    id TEXT PRIMARY KEY,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Edit `infra/init/01_schema.sql` — 15 user-ref columns**

For each column listed in the table above, change the type token `UUID` → `TEXT` on that column **only**. Preserve `REFERENCES auth.users(id)`, the `ON DELETE` clause, and any `NOT NULL` / `UNIQUE`. Example (line 41):
```sql
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
```
Apply the same `UUID` → `TEXT` edit to: `shares.user_id`, `api_keys.user_id`, `teams.owner_id`, `team_members.user_id`, `team_invitations.invited_by`, `team_events.user_id`, `team_shares.shared_by`, `share_groups.user_id`, `share_revisions.user_id`, `share_comments.user_id`, `share_stars.user_id`, `tags.user_id`, `folders.user_id`, `user_profiles.user_id`, `file_requests.user_id`. Do **not** touch non-user UUID columns (e.g. `teams.id`, `team_id`, `share_id`).

- [ ] **Step 3: Edit `infra/init/01_schema.sql` — `has_user_starred`**

Change (around line 469):
```sql
CREATE OR REPLACE FUNCTION has_user_starred(p_share_id UUID, p_user_id UUID)
```
to:
```sql
CREATE OR REPLACE FUNCTION has_user_starred(p_share_id UUID, p_user_id TEXT)
```

- [ ] **Step 4: Edit `infra/init/02_rpc_functions.sql` — 5 functions**

- Line 22 (`search_shares` RETURNS TABLE): `user_id UUID` → `user_id TEXT`
- Line 59 (`change_team_member_role`): `p_user_id UUID,` → `p_user_id TEXT,`
- Line 71 (`remove_team_member`): `p_user_id UUID` → `p_user_id TEXT`
- Line 80 (`accept_team_invite`): `p_user_id UUID` → `p_user_id TEXT`
- Line 115 (`create_team_invite`): `p_invited_by UUID,` → `p_invited_by TEXT,`

- [ ] **Step 5: Edit `k8s/auth-stub.sql`**

Change:
```sql
CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID
  LANGUAGE sql STABLE AS $$
    SELECT NULL::UUID;
  $$;
```
to:
```sql
CREATE OR REPLACE FUNCTION auth.uid() RETURNS TEXT
  LANGUAGE sql STABLE AS $$
    SELECT NULL::TEXT;
  $$;
```

- [ ] **Step 6: Create `migrations/007_firebase_uid_text.sql`**

Full contents (self-contained, non-destructive; for existing DBs):

```sql
-- 007_firebase_uid_text.sql
-- Switch all user-identity columns from UUID (Supabase) to TEXT (Firebase uid).
-- Non-destructive: UUID values are valid TEXT. Postgres refuses to ALTER a
-- column a view depends on, so views are dropped first and recreated after.

BEGIN;

DROP VIEW IF EXISTS public_shares;
DROP VIEW IF EXISTS trending_shares;
DROP VIEW IF EXISTS team_invites;
DROP VIEW IF EXISTS profiles;

ALTER TABLE shares           DROP CONSTRAINT IF EXISTS shares_user_id_fkey;
ALTER TABLE api_keys         DROP CONSTRAINT IF EXISTS api_keys_user_id_fkey;
ALTER TABLE teams            DROP CONSTRAINT IF EXISTS teams_owner_id_fkey;
ALTER TABLE team_members     DROP CONSTRAINT IF EXISTS team_members_user_id_fkey;
ALTER TABLE team_invitations DROP CONSTRAINT IF EXISTS team_invitations_invited_by_fkey;
ALTER TABLE team_events      DROP CONSTRAINT IF EXISTS team_events_user_id_fkey;
ALTER TABLE team_shares      DROP CONSTRAINT IF EXISTS team_shares_shared_by_fkey;
ALTER TABLE share_groups     DROP CONSTRAINT IF EXISTS share_groups_user_id_fkey;
ALTER TABLE share_revisions  DROP CONSTRAINT IF EXISTS share_revisions_user_id_fkey;
ALTER TABLE share_comments   DROP CONSTRAINT IF EXISTS share_comments_user_id_fkey;
ALTER TABLE share_stars      DROP CONSTRAINT IF EXISTS share_stars_user_id_fkey;
ALTER TABLE tags             DROP CONSTRAINT IF EXISTS tags_user_id_fkey;
ALTER TABLE folders          DROP CONSTRAINT IF EXISTS folders_user_id_fkey;
ALTER TABLE user_profiles    DROP CONSTRAINT IF EXISTS user_profiles_user_id_fkey;
ALTER TABLE file_requests    DROP CONSTRAINT IF EXISTS file_requests_user_id_fkey;

ALTER TABLE auth.users ALTER COLUMN id TYPE TEXT;
ALTER TABLE auth.users ALTER COLUMN id DROP DEFAULT;

ALTER TABLE shares           ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE api_keys         ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE teams            ALTER COLUMN owner_id  TYPE TEXT;
ALTER TABLE team_members     ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE team_invitations ALTER COLUMN invited_by TYPE TEXT;
ALTER TABLE team_events      ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE team_shares      ALTER COLUMN shared_by TYPE TEXT;
ALTER TABLE share_groups     ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_revisions  ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_comments   ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_stars      ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE tags             ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE folders          ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE user_profiles    ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE file_requests    ALTER COLUMN user_id   TYPE TEXT;

ALTER TABLE shares           ADD CONSTRAINT shares_user_id_fkey           FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE api_keys         ADD CONSTRAINT api_keys_user_id_fkey         FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE teams            ADD CONSTRAINT teams_owner_id_fkey           FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE team_members     ADD CONSTRAINT team_members_user_id_fkey     FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE team_invitations ADD CONSTRAINT team_invitations_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE team_events      ADD CONSTRAINT team_events_user_id_fkey      FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE team_shares      ADD CONSTRAINT team_shares_shared_by_fkey    FOREIGN KEY (shared_by) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_groups     ADD CONSTRAINT share_groups_user_id_fkey     FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_revisions  ADD CONSTRAINT share_revisions_user_id_fkey  FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_comments   ADD CONSTRAINT share_comments_user_id_fkey   FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_stars      ADD CONSTRAINT share_stars_user_id_fkey      FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE tags             ADD CONSTRAINT tags_user_id_fkey             FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE folders          ADD CONSTRAINT folders_user_id_fkey          FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE user_profiles    ADD CONSTRAINT user_profiles_user_id_fkey    FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE file_requests    ADD CONSTRAINT file_requests_user_id_fkey    FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE OR REPLACE VIEW team_invites AS SELECT * FROM team_invitations;
CREATE OR REPLACE VIEW profiles AS SELECT * FROM user_profiles;

CREATE OR REPLACE VIEW public_shares AS
SELECT
    s.id, s.slug, s.filename, s.title, s.tags, s.view_count,
    s.download_count, s.created_at, s.user_id, s.mime_type, s.source,
    COALESCE(star_counts.star_count, 0) AS star_count
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count FROM share_stars GROUP BY share_id
) star_counts ON star_counts.share_id = s.id
WHERE s.is_private = false AND s.burned = false
  AND (s.expires_at IS NULL OR s.expires_at > now());

CREATE OR REPLACE VIEW trending_shares AS
SELECT
    s.id, s.slug, s.filename, s.title, s.tags, s.view_count,
    s.download_count, s.created_at, s.user_id, s.mime_type, s.source,
    COALESCE(star_counts.star_count, 0) AS star_count,
    (ln(GREATEST(s.view_count, 0) + 1) *
     (1.0 / (1.0 + EXTRACT(EPOCH FROM (now() - s.created_at)) / 86400.0)))
    + (ln(GREATEST(COALESCE(star_counts.star_count, 0), 0) + 1) * 2.0)
    AS trending_score
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count FROM share_stars GROUP BY share_id
) star_counts ON star_counts.share_id = s.id;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS TEXT
  LANGUAGE sql STABLE AS $$ SELECT NULL::TEXT; $$;

CREATE OR REPLACE FUNCTION search_shares(query_term TEXT, result_limit INTEGER DEFAULT 20, result_offset INTEGER DEFAULT 0)
RETURNS TABLE (
    id UUID, slug TEXT, filename TEXT, title TEXT, mime_type TEXT, source TEXT,
    view_count INTEGER, download_count INTEGER, created_at TIMESTAMPTZ, user_id TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.slug, s.filename, s.title, s.mime_type, s.source,
           s.view_count, s.download_count, s.created_at, s.user_id
    FROM shares s
    WHERE s.is_private = false AND s.burned = false
      AND (s.expires_at IS NULL OR s.expires_at > now())
      AND (s.content_text ILIKE '%' || query_term || '%'
           OR s.filename ILIKE '%' || query_term || '%'
           OR s.title ILIKE '%' || query_term || '%')
    ORDER BY s.created_at DESC
    LIMIT result_limit OFFSET result_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION change_team_member_role(p_team_id UUID, p_user_id TEXT, p_new_role TEXT)
RETURNS void AS $$
BEGIN
    UPDATE team_members SET role = p_new_role WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION remove_team_member(p_team_id UUID, p_user_id TEXT)
RETURNS void AS $$
BEGIN
    DELETE FROM team_members WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accept_team_invite(p_token TEXT, p_user_id TEXT)
RETURNS TABLE(team_id UUID, team_name TEXT) AS $$
DECLARE
    v_invite RECORD;
    v_team_id UUID;
    v_team_name TEXT;
BEGIN
    SELECT * INTO v_invite FROM team_invitations
    WHERE token = p_token AND status = 'pending' AND expires_at > now();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid or expired invite';
    END IF;
    UPDATE team_invitations SET status = 'accepted' WHERE token = p_token;
    INSERT INTO team_members (team_id, user_id, role)
    VALUES (v_invite.team_id, p_user_id, v_invite.role)
    ON CONFLICT (team_id, user_id) DO NOTHING;
    SELECT id, name INTO v_team_id, v_team_name FROM teams WHERE id = v_invite.team_id;
    RETURN QUERY SELECT v_team_id, v_team_name;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_team_invite(p_team_id UUID, p_email TEXT, p_role TEXT, p_invited_by TEXT, p_token TEXT)
RETURNS TABLE(id UUID, team_id UUID, email TEXT, role TEXT, token TEXT) AS $$
DECLARE v_id UUID;
BEGIN
    INSERT INTO team_invitations (team_id, email, role, invited_by, token)
    VALUES (p_team_id, p_email, p_role, p_invited_by, p_token)
    RETURNING id INTO v_id;
    RETURN QUERY SELECT v_id, p_team_id, p_email, p_role, p_token;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION has_user_starred(p_share_id UUID, p_user_id TEXT)
RETURNS BOOLEAN AS $$
    SELECT EXISTS(SELECT 1 FROM share_stars WHERE share_id = p_share_id AND user_id = p_user_id);
$$ LANGUAGE sql;

COMMIT;
```

- [ ] **Step 7: Re-initialize the local DB from the edited init schema**

Run (data is disposable):
```bash
docker compose down -v
docker compose up -d
```
Wait for Postgres to be ready, then verify.

- [ ] **Step 8: Verify types via psql**

```bash
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='auth' AND table_name='users' AND column_name='id';"
```
Expect `data_type = text`.

```bash
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT count(*) FROM information_schema.columns WHERE column_name IN ('user_id','owner_id','invited_by','shared_by') AND data_type='text' AND table_schema='public';"
```
Expect `15`.

```bash
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT pg_typeof(user_id) FROM public_shares LIMIT 0;"
```
Expect `text` (view reflects the new type).

- [ ] **Step 9: Commit**

```bash
git add infra/init/01_schema.sql infra/init/02_rpc_functions.sql k8s/auth-stub.sql migrations/007_firebase_uid_text.sql
git commit -m "refactor(db): retype user identity columns to TEXT for Firebase uids"
```

---

## Task 2: Add the `provision_firebase_user` RPC

**Files:**
- Modify: `infra/init/02_rpc_functions.sql` (append)
- Create: `migrations/008_provision_firebase_user.sql`

**Interfaces:**
- Produces: SQL RPC `provision_firebase_user(p_uid TEXT, p_email TEXT) → TABLE(user_id, username, display_name, bio, avatar_url, is_public, created_at, updated_at)`. Called by Task 4's endpoint as `client.rpc("provision_firebase_user", {"p_uid": uid, "p_email": email}).execute()`; result `.data[0]` is the profile row.

- [ ] **Step 1: Append to `infra/init/02_rpc_functions.sql`**

```sql

-- =========================================================================
-- provision_firebase_user — idempotent upsert of auth.users + user_profiles
-- Called by GET /api/auth/session on every FE load. ON CONFLICT keeps it
-- race-free for concurrent first calls; profile fields are never clobbered.
-- =========================================================================
CREATE OR REPLACE FUNCTION provision_firebase_user(p_uid TEXT, p_email TEXT)
RETURNS TABLE (
    user_id TEXT,
    username TEXT,
    display_name TEXT,
    bio TEXT,
    avatar_url TEXT,
    is_public BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
) AS $$
BEGIN
    INSERT INTO auth.users (id, email)
    VALUES (p_uid, p_email)
    ON CONFLICT (id) DO UPDATE
      SET email = COALESCE(EXCLUDED.email, auth.users.email);

    INSERT INTO user_profiles (user_id)
    VALUES (p_uid)
    ON CONFLICT (user_id) DO NOTHING;

    RETURN QUERY
    SELECT user_id, username, display_name, bio, avatar_url, is_public, created_at, updated_at
    FROM user_profiles
    WHERE user_id = p_uid;
END;
$$ LANGUAGE plpgsql;
```

- [ ] **Step 2: Create `migrations/008_provision_firebase_user.sql`**

Paste the **same** `CREATE OR REPLACE FUNCTION provision_firebase_user(...) ... $$ LANGUAGE plpgsql;` block from Step 1 (standalone file for existing DBs).

- [ ] **Step 3: Re-init so the new RPC is present**

```bash
docker compose down -v && docker compose up -d
```

- [ ] **Step 4: Verify the RPC via psql**

```bash
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT provision_firebase_user('firebase-test-uid-1', 'first@example.com');"
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT provision_firebase_user('firebase-test-uid-1', 'changed@example.com');"
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT email FROM auth.users WHERE id='firebase-test-uid-1';"
docker compose exec -T postgres psql -U dropitx -d dropitx -c "SELECT count(*) FROM user_profiles WHERE user_id='firebase-test-uid-1';"
```
Expect: row returned both times with `user_id='firebase-test-uid-1'`; `email='changed@example.com'`; profile `count = 1` (not duplicated).

```bash
docker compose exec -T postgres psql -U dropitx -d dropitx -c "DELETE FROM auth.users WHERE id='firebase-test-uid-1';"
```

- [ ] **Step 5: Commit**

```bash
git add infra/init/02_rpc_functions.sql migrations/008_provision_firebase_user.sql
git commit -m "feat(db): add provision_firebase_user RPC"
```

---

## Task 3: `get_firebase_claims` + provision-aware `get_current_user`

**Files:**
- Modify: `app/dependencies.py`
- Test: `tests/test_dependencies.py` (create)

**Interfaces:**
- Produces: `async def get_firebase_claims(request: Request) -> dict` (used by Task 4's endpoint via `Depends`); `async def get_current_user(request: Request) -> User` (unchanged signature, new behavior: verify + lookup, 401 `{"code":"user_not_provisioned"}` if missing).

- [ ] **Step 1: Write the failing tests** — create `tests/test_dependencies.py`

```python
"""Unit tests for auth dependencies."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from fastapi.exceptions import HTTPException

from app.dependencies import get_firebase_claims, get_current_user


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        mock.firebase_project_id = "test-project"
        mock.cors_origins = ["*"]
        yield mock


def _req(token=None):
    headers = {}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return FakeRequest(headers)


# ----- get_firebase_claims -----

def test_claims_missing_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_firebase_claims(_req()))
    assert exc.value.status_code == 401


@patch("app.dependencies.verify_firebase_jwt")
def test_claims_valid_token(mock_verify):
    mock_verify.return_value = {"sub": "uid-1", "email": "a@b.com"}
    claims = asyncio.run(get_firebase_claims(_req("tok")))
    assert claims["sub"] == "uid-1"


@patch("app.dependencies.verify_firebase_jwt", side_effect=ValueError("bad sig"))
def test_claims_invalid_token(mock_verify):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_firebase_claims(_req("tok")))
    assert exc.value.status_code == 401


# ----- get_current_user -----

@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_provisioned(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-1", "email": "a@b.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "uid-1", "email": "a@b.com"}]
    )
    user = asyncio.run(get_current_user(_req("tok")))
    assert user.id == "uid-1"
    assert user.email == "a@b.com"


@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_not_provisioned(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-2", "email": "x@y.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(_req("tok")))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "user_not_provisioned"


@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_lookup_error_is_500(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-3", "email": "z@w.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.side_effect = RuntimeError("db down")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(_req("tok")))
    assert exc.value.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dependencies.py -v
```
Expected: FAIL — `get_firebase_claims` does not exist yet (the not-provisioned / lookup-error tests also fail against the old `get_current_user`).

- [ ] **Step 3: Implement — edit `app/dependencies.py`**

Replace the existing `get_current_user` (lines 41-55) with `get_firebase_claims` + a new `get_current_user`:

```python
async def get_firebase_claims(request: Request) -> dict:
    """Verify the Firebase Bearer token and return its claims.

    Raises HTTPException(401) on a missing or invalid token.
    """
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    try:
        return await asyncio.to_thread(verify_firebase_jwt, token)
    except (ValueError, KeyError) as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_current_user(request: Request) -> User:
    """Verify the Firebase JWT and confirm the user is provisioned locally.

    Raises HTTPException(401) on missing/invalid token or an un-provisioned user.
    Does not write — provisioning is the FE's job via /api/auth/session.
    """
    claims = await get_firebase_claims(request)
    uid = claims["sub"]

    try:
        client = get_admin_client()
        resp = await asyncio.to_thread(
            lambda: client.table("auth.users").select("id, email").eq("id", uid).execute()
        )
    except Exception as exc:
        logger.error("User lookup failed for %s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="User lookup failed") from exc

    if not resp.data:
        raise HTTPException(
            status_code=401,
            detail={"code": "user_not_provisioned", "message": "User not provisioned"},
        )

    row = resp.data[0]
    return User(id=row["id"], email=row.get("email"))
```

Also update the `User` dataclass docstring (line 23) from `"""Authenticated user extracted from a Supabase JWT."""` to `"""Authenticated user extracted from a Firebase ID token."""`.

Leave `get_optional_user` untouched — it already swallows HTTPException from `get_current_user`, so an un-provisioned user on an optional-auth route degrades to anonymous (intended).

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dependencies.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run the existing suite to confirm no regressions**

```bash
pytest -q
```
Expected: green. Existing route tests override `get_current_user` via `dependency_overrides`, so the refactor does not affect them.

- [ ] **Step 6: Commit**

```bash
git add app/dependencies.py tests/test_dependencies.py
git commit -m "feat(auth): add get_firebase_claims and provision-aware get_current_user"
```

---

## Task 4: `GET /api/auth/session` endpoint

**Files:**
- Create: `app/auth/__init__.py` (empty), `app/auth/session.py`, `app/auth/router.py`
- Modify: `app/main.py`
- Test: `tests/test_auth_session.py` (create)

**Interfaces:**
- Consumes: `get_firebase_claims` (Task 3), `provision_firebase_user` RPC (Task 2), `get_admin_client` from `core.supabase`.
- Produces: `GET /api/auth/session` → `200 {id, email, email_verified, profile{...}}`; `401` on bad/missing token; `500` on provisioning failure.

- [ ] **Step 1: Write the failing tests** — create `tests/test_auth_session.py`

```python
"""Tests for GET /api/auth/session."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_firebase_claims


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        mock.firebase_project_id = "test-project"
        mock.cors_origins = ["*"]
        yield mock


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def override_claims(claims):
    app.dependency_overrides[get_firebase_claims] = lambda: claims


PROFILE_ROW = {
    "user_id": "uid-1",
    "username": None,
    "display_name": None,
    "bio": None,
    "avatar_url": None,
    "is_public": False,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


class TestGetSession:
    def test_requires_auth(self, client):
        resp = client.get("/api/auth/session")
        assert resp.status_code == 401

    @patch("app.auth.session.get_admin_client")
    def test_provisions_and_returns_profile(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com", "email_verified": True})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[PROFILE_ROW])

        resp = client.get("/api/auth/session")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "uid-1"
        assert body["email"] == "a@b.com"
        assert body["email_verified"] is True
        assert body["profile"]["user_id"] == "uid-1"
        mock_client.rpc.assert_called_once_with(
            "provision_firebase_user", {"p_uid": "uid-1", "p_email": "a@b.com"}
        )

    @patch("app.auth.session.get_admin_client")
    def test_idempotent(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[PROFILE_ROW])

        r1 = client.get("/api/auth/session")
        r2 = client.get("/api/auth/session")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["profile"]["user_id"] == r2.json()["profile"]["user_id"]
        assert mock_client.rpc.call_count == 2

    @patch("app.auth.session.get_admin_client")
    def test_empty_profile_returns_500(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=[])
        resp = client.get("/api/auth/session")
        assert resp.status_code == 500

    @patch("app.auth.session.get_admin_client")
    def test_rpc_exception_returns_500(self, mock_get_client, client):
        override_claims({"sub": "uid-1", "email": "a@b.com"})
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.rpc.return_value.execute.side_effect = RuntimeError("db down")
        resp = client.get("/api/auth/session")
        assert resp.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_auth_session.py -v
```
Expected: FAIL — `app.auth.session` does not exist (import error / 404 on the route).

- [ ] **Step 3: Create `app/auth/__init__.py`** — empty file.

- [ ] **Step 4: Create `app/auth/session.py`**

```python
"""Firebase auth session endpoint — provisions the user and returns the profile."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_firebase_claims
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


class SessionProfile(BaseModel):
    id: str
    email: str | None = None
    email_verified: bool = False
    profile: dict


@router.get("/session", tags=["Auth"], summary="Provision user and return profile")
async def get_session(claims: dict = Depends(get_firebase_claims)) -> SessionProfile:
    uid = claims["sub"]
    email = claims.get("email")

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.rpc(
                "provision_firebase_user", {"p_uid": uid, "p_email": email}
            ).execute()
        )
    except Exception as exc:
        logger.error("Provisioning failed for %s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="Provisioning failed") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Provisioning returned no profile")

    return SessionProfile(
        id=uid,
        email=email,
        email_verified=bool(claims.get("email_verified")),
        profile=rows[0],
    )
```

- [ ] **Step 5: Create `app/auth/router.py`**

```python
from fastapi import APIRouter

from app.auth.session import router as session_router

router = APIRouter()
router.include_router(session_router)
```

- [ ] **Step 6: Wire into `app/main.py`**

Add to the imports block (after line 8):
```python
from app.auth.router import router as auth_router
```
Add to the router-registration block (after line 110):
```python
app.include_router(auth_router, prefix="/api/auth")
```
Refresh the stale auth copy in the `description=` string (around lines 81-83): change `"- **JWT (Supabase Auth):** ..."` to `"- **JWT (Firebase Auth):** \`Authorization: Bearer <firebase_id_token>\` — used for dashboard, upload, publish, image, and /api/auth/session endpoints"`.

- [ ] **Step 7: Run the new tests to verify they pass**

```bash
pytest tests/test_auth_session.py -v
```
Expected: all PASS.

- [ ] **Step 8: Run the full suite**

```bash
pytest -q
```
Expected: green (new + existing tests).

- [ ] **Step 9: Smoke-check the OpenAPI doc**

```bash
python -c "from app.main import app; print([r.path for r in app.routes if '/auth' in getattr(r,'path','')])"
```
Expected output includes `/api/auth/session`.

- [ ] **Step 10: Commit**

```bash
git add app/auth/ app/main.py tests/test_auth_session.py
git commit -m "feat(auth): add GET /api/auth/session provisioning endpoint"
```

---

## Self-Review (run after writing — already applied)

**Spec coverage:**
- Identity = Firebase uid TEXT → Task 1 (all 15 columns + functions + views).
- No provisioning → Task 2 (`provision_firebase_user` RPC).
- No auth surface → Task 4 (`/api/auth/session`).
- `get_current_user` verify+lookup, `user_not_provisioned` 401, no writes → Task 3.
- `FIREBASE_PROJECT_ID` requirement → Global Constraints (already set; no code change — it's an env/deploy concern noted in the spec).
- Schema mismatch resolution → Task 1.

**Placeholder scan:** none. All SQL and Python is complete and copy-pasteable. The earlier "12 tables" miscount in the spec is corrected here to **15 columns / 13 tables** (adds `teams.owner_id`, `team_invitations.invited_by`, `team_shares.shared_by`) plus 4 dependent views — the migration drops/recreates them so the retype doesn't fail.

**Type consistency:** RPC returns `(user_id TEXT, …)`; endpoint reads `rows[0]` into `SessionProfile.profile: dict`, returns `id=uid` (str from claims). `get_current_user` returns `User(id=row["id"], …)` (str). `client.rpc("provision_firebase_user", {"p_uid","p_email"})` matches the RPC signature `provision_firebase_user(p_uid TEXT, p_email TEXT)`.

**Carryover note for the FE spec (out of scope here):** after this lands, `/api/auth/session` is the FE's "who am I + ensure provisioned" call on every auth-state-ready; any 401 from a protected route (incl. `user_not_provisioned`) means re-call `/auth/session`.

---

## Execution Handoff

Plan complete and saved to `plans/260812-2252-firebase-auth-backend-api/plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
