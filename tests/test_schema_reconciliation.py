"""Live-DB tests: code paths that broke because infra/init lacked what they use.

Runs against the real Postgres from CI. Only authentication is overridden.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import User, get_current_user, get_optional_user
from app.internal.publish import _resolve_custom_slug
from app.main import app
from app.v1.revisions import save_revision
from core.supabase import get_admin_client


def _tag() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture
def db():
    return get_admin_client()


@pytest.fixture
def seed(db):
    """Create rows; remove them (and their cascades) on teardown."""
    made: list[tuple[str, str, str]] = []  # (table, key column, value)

    def add(table: str, row: dict, key: str = "id") -> dict:
        created = db.table(table).insert(row).execute().data[0]
        made.append((table, key, created[key]))
        return created

    yield add
    for table, key, value in reversed(made):
        db.table(table).delete().eq(key, value).execute()


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _act_as(uid: str) -> None:
    user = User(id=uid, email=f"{uid}@example.com")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def test_new_team_is_on_the_free_plan_which_allows_one_domain(client, seed):
    uid = f"u-{_tag()}"
    seed("auth.users", {"id": uid})
    team = seed("teams", {"name": "T", "slug": f"t-{_tag()}", "owner_id": uid})
    seed("team_members", {"team_id": team["id"], "user_id": uid, "role": "owner"})
    _act_as(uid)
    url = f"/api/dashboard/teams/{team['slug']}/domains"

    first = client.post(url, json={"domain": f"{_tag()}.example.com"})
    second = client.post(url, json={"domain": f"{_tag()}.example.com"})

    assert team["plan"] == "free"
    assert first.status_code == 201
    assert second.status_code == 403
    assert "Pro plan" in second.json()["detail"]


def test_create_team_invite_stores_token_inviter_and_expiry_as_named(db, seed):
    uid = f"u-{_tag()}"
    seed("auth.users", {"id": uid})
    team = seed("teams", {"name": "T", "slug": f"t-{_tag()}", "owner_id": uid})
    token = f"tok-{_tag()}"
    expiry = datetime(2031, 5, 6, 7, 8, 9, tzinfo=timezone.utc)

    # Same parameter order as app/dashboard/team_invites.py.
    db.rpc("create_team_invite", {
        "p_team_id": team["id"],
        "p_email": "invitee@example.com",
        "p_role": "editor",
        "p_token": token,
        "p_invited_by": uid,
        "p_expires_at": expiry.isoformat(),
    }).execute()

    (row,) = db.table("team_invitations").select("*").eq("team_id", team["id"]).execute().data
    assert (row["token"], row["invited_by"], row["role"]) == (token, uid, "editor")
    assert datetime.fromisoformat(row["expires_at"]) == expiry


def test_create_team_invite_defaults_expiry_to_seven_days(db, seed):
    uid = f"u-{_tag()}"
    seed("auth.users", {"id": uid})
    team = seed("teams", {"name": "T", "slug": f"t-{_tag()}", "owner_id": uid})

    db.rpc("create_team_invite", {
        "p_team_id": team["id"], "p_email": "x@example.com", "p_role": "viewer",
        "p_invited_by": uid, "p_token": f"tok-{_tag()}",
    }).execute()

    (row,) = db.table("team_invitations").select("expires_at").eq("team_id", team["id"]).execute().data
    left = datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)


def test_share_revisions_are_numbered_per_share(db, seed):
    share = seed("shares", {"slug": f"rev-{_tag()}"})

    first = asyncio.run(save_revision(share["id"], "v1 body", filename="a.md", title="A"))
    second = asyncio.run(save_revision(share["id"], "v2 body"))

    rows = db.table("share_revisions").select("*").eq("share_id", share["id"]).order("revision").execute().data
    assert (first, second) == (1, 2)
    assert [(r["revision"], r["content"], r["filename"], r["title"]) for r in rows] == [
        (1, "v1 body", "a.md", "A"),
        (2, "v2 body", None, None),
    ]


def test_comment_reply_keeps_its_parent(client, seed):
    share = seed("shares", {"slug": f"cmt-{_tag()}"})
    app.dependency_overrides[get_optional_user] = lambda: None
    n = uuid.uuid4().int
    ip = {"cf-connecting-ip": f"10.{n % 256}.{(n >> 8) % 256}.{(n >> 16) % 256}"}  # own rate-limit bucket

    parent = client.post(f"/api/shares/{share['slug']}/comments", json={"content": "first"}, headers=ip)
    reply = client.post(
        f"/api/shares/{share['slug']}/comments",
        json={"content": "reply", "parent_id": parent.json()["id"]},
        headers=ip,
    )
    listed = client.get(f"/api/shares/{share['slug']}/comments").json()["comments"]

    assert parent.status_code == reply.status_code == 200
    assert {c["content"]: c["parent_id"] for c in listed} == {"first": None, "reply": parent.json()["id"]}


def test_custom_slug_is_prefixed_with_the_owners_username(seed):
    uid = f"u-{_tag()}"
    username = f"alice{_tag()}"
    seed("auth.users", {"id": uid})
    seed("user_profiles", {"user_id": uid, "username": username})

    assert asyncio.run(_resolve_custom_slug(uid, "my-doc")) == f"{username}/my-doc"


def test_accept_team_invite_adds_the_member_and_names_the_team(db, seed):
    owner, invitee = f"u-{_tag()}", f"u-{_tag()}"
    seed("auth.users", {"id": owner})
    seed("auth.users", {"id": invitee})
    team = seed("teams", {"name": "Team Accept", "slug": f"t-{_tag()}", "owner_id": owner})
    token = f"tok-{_tag()}"
    db.rpc("create_team_invite", {
        "p_team_id": team["id"], "p_email": "i@example.com", "p_role": "editor",
        "p_invited_by": owner, "p_token": token,
    }).execute()

    resp = db.rpc("accept_team_invite", {"p_token": token, "p_user_id": invitee}).execute()

    assert resp.data == [{"team_id": team["id"], "team_name": "Team Accept"}]
    (member,) = db.table("team_members").select("role").eq("team_id", team["id"]).eq("user_id", invitee).execute().data
    assert member["role"] == "editor"
