"""Live-DB tests: endpoints that read embedded rows, profile lookups by Firebase uid, and starring.

Runs against the real Postgres + MinIO from CI. Only authentication is overridden.
Embeds follow PostgREST: keyed by the foreign table name, an object or null for a
to-one relation, and the main row keeps its own `id`.
"""

from __future__ import annotations

import uuid

import pytest

from app.dependencies import ApiKeyAuth, User, get_api_key, get_current_user, get_optional_user
from app.main import app
from core.supabase import get_admin_client


def _tag() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture
def db():
    return get_admin_client()


@pytest.fixture
def seed(db):
    """Create rows; remove them (and their cascades) on teardown."""
    made: list[tuple[str, str, str]] = []

    def add(table: str, row: dict, key: str = "id") -> dict:
        created = db.table(table).insert(row).execute().data[0]
        made.append((table, key, created[key]))
        return created

    yield add
    for table, key, value in reversed(made):
        db.table(table).delete().eq(key, value).execute()


def _act_as(uid: str) -> None:
    user = User(id=uid, email=f"{uid}@example.com")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


@pytest.fixture
def member(seed):
    """A user with a profile who owns a team."""
    uid = f"u-{_tag()}"
    seed("auth.users", {"id": uid})
    profile = seed("user_profiles", {"user_id": uid, "display_name": "Ann Owner", "avatar_url": "https://a.example/ann.png"})
    team = seed("teams", {"name": "Team T", "slug": f"t-{_tag()}", "owner_id": uid})
    membership = seed("team_members", {"team_id": team["id"], "user_id": uid, "role": "owner"})
    return {"uid": uid, "profile": profile, "team": team, "membership": membership}


def test_list_teams_embeds_the_whole_team(client, member):
    _act_as(member["uid"])

    resp = client.get("/api/dashboard/teams")

    assert resp.status_code == 200
    (row,) = resp.json()
    team = member["team"]
    assert (row["team_id"], row["role"]) == (team["id"], "owner")
    assert row["joined_at"]
    assert row["teams"]["id"] == team["id"]
    assert (row["teams"]["name"], row["teams"]["slug"], row["teams"]["plan"]) == ("Team T", team["slug"], "free")


def test_team_members_include_profile_display_names(client, seed, member):
    other = f"u-{_tag()}"
    seed("auth.users", {"id": other})
    membership = seed("team_members", {"team_id": member["team"]["id"], "user_id": other, "role": "viewer"})
    _act_as(member["uid"])

    resp = client.get(f"/api/dashboard/teams/{member['team']['slug']}/members")

    assert resp.status_code == 200
    rows = {r["user_id"]: r for r in resp.json()}
    assert rows[member["uid"]]["id"] == member["membership"]["id"]
    assert rows[member["uid"]]["user_profiles"] == {
        "display_name": "Ann Owner", "avatar_url": "https://a.example/ann.png",
    }
    # A member without a profile row embeds null, not an object of nulls.
    assert rows[other]["id"] == membership["id"]
    assert rows[other]["user_profiles"] is None


def test_invitations_embed_team_and_inviter_and_keep_the_invite_id(client, seed, member):
    invitee = f"u-{_tag()}"
    invite = seed("team_invitations", {
        "team_id": member["team"]["id"], "email": f"{invitee}@example.com", "role": "editor",
        "invited_by": member["uid"], "token": f"tok-{_tag()}",
    })
    _act_as(invitee)

    resp = client.get("/api/dashboard/invitations")

    assert resp.status_code == 200
    (row,) = resp.json()
    team = member["team"]
    assert row["id"] == invite["id"]
    assert row["teams"] == {"id": team["id"], "name": "Team T", "slug": team["slug"]}
    assert row["user_profiles"] == {
        "id": member["profile"]["id"], "display_name": "Ann Owner", "avatar_url": "https://a.example/ann.png",
    }


def test_domain_resolve_reads_the_embedded_team(client, seed, member):
    domain = f"{_tag()}.example.com"
    seed("custom_domains", {"team_id": member["team"]["id"], "domain": domain, "status": "active"})

    resp = client.get(f"/api/dashboard/domains/resolve/{domain}")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["team_id"], body["team_slug"], body["team_name"]) == (
        member["team"]["id"], member["team"]["slug"], "Team T",
    )


def test_team_document_list_returns_the_embedded_shares(client, db, seed, member):
    path = f"test/{_tag()}.md"
    db.storage.from_("shares").upload(path, b"# hello", file_options={"content-type": "text/markdown"})
    try:
        share = seed("shares", {"slug": f"doc-{_tag()}", "storage_path": path, "user_id": member["uid"], "title": "Doc", "source": "api"})
        link = seed("team_shares", {"team_id": member["team"]["id"], "share_id": share["id"], "shared_by": member["uid"]})
        auth = ApiKeyAuth(user_id=member["uid"], key_id="k", team_id=member["team"]["id"])
        app.dependency_overrides[get_api_key] = lambda: auth

        resp = client.get("/api/v1/documents")

        assert resp.status_code == 200
        (doc,) = resp.json()
        assert doc["id"] == share["id"] != link["id"]
        assert (doc["slug"], doc["title"], doc["content"]) == (share["slug"], "Doc", "# hello")
    finally:
        db.storage.from_("shares").remove([path])


# ---------------------------------------------------------------------------
# Author profiles are looked up by Firebase uid (user_profiles.user_id)
# ---------------------------------------------------------------------------

def test_explore_shows_author_profiles(client, seed, member):
    share = seed("shares", {
        "slug": f"exp-{_tag()}", "filename": "a.md", "user_id": member["uid"],
        "view_count": 2_000_000_000,
    })

    resp = client.get("/api/explore", params={"sort": "views", "limit": 1})

    assert resp.status_code == 200
    (card,) = resp.json()["shares"]
    assert card["id"] == share["id"]
    assert (card["author_name"], card["author_avatar"]) == ("Ann Owner", "https://a.example/ann.png")


def test_oembed_shows_the_author_name(client, seed, member):
    share = seed("shares", {"slug": f"emb-{_tag()}", "filename": "a.md", "user_id": member["uid"]})

    resp = client.get("/api/oembed", params={"url": f"https://dropitx.com/s/{share['slug']}"})

    assert resp.status_code == 200
    assert resp.json()["author_name"] == "Ann Owner"


# ---------------------------------------------------------------------------
# Stars
# ---------------------------------------------------------------------------

def test_starring_a_share_twice_is_idempotent(client, db, seed, member):
    share = seed("shares", {"slug": f"star-{_tag()}", "user_id": member["uid"]})
    _act_as(member["uid"])
    url = f"/api/shares/{share['slug']}/star"

    first = client.post(url)
    second = client.post(url)
    status = client.get(url)

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json() == {"starred": True, "count": 1}
    assert status.json() == {"starred": True, "count": 1}
    stars = db.table("share_stars").select("user_id").eq("share_id", share["id"]).execute().data
    assert stars == [{"user_id": member["uid"]}]
