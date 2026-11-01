"""Live-DB tests: team actions are written to team_events and read back by the events feed.

Event types and payloads (the frontend renders these):

    member_joined   actor = new member        {"role"}
    member_left     actor = leaving member    {"user_id"}
    member_removed  actor = owner             {"user_id"}
    role_changed    actor = owner             {"user_id", "role", "previous_role"}
    invite_sent     actor = inviter           {"invite_id", "email", "role"}
    invite_revoked  actor = revoker           {"invite_id", "email"}
    share_added     actor = sharer            {"share_id", "slug"}
    share_removed   actor = remover or null   {"share_id", "slug"}
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.dependencies import ApiKeyAuth, get_api_key
from app.main import app
from core.supabase import get_admin_client
from tests.conftest import act_as


@pytest.fixture
def team(client, seed):
    """A team created through the API by its owner (who is its first member)."""
    owner = seed.user()
    act_as(owner)
    slug = f"ev-{uuid.uuid4().hex[:10]}"
    resp = client.post("/api/dashboard/teams", json={"name": "Events team", "slug": slug})
    assert resp.status_code == 201, resp.text
    seed.teams.append(resp.json()["id"])
    return {"id": resp.json()["id"], "slug": slug, "owner": owner}


def _events(seed, team) -> list[dict]:
    return (
        seed.db.table("team_events").select("*").eq("team_id", team["id"])
        .order("created_at", desc=False).execute().data
    )


def _only(seed, team, event_type: str) -> dict:
    matching = [e for e in _events(seed, team) if e["event_type"] == event_type]
    assert len(matching) == 1, _events(seed, team)
    event = matching[0]
    if isinstance(event["payload"], str):
        event["payload"] = json.loads(event["payload"])
    return event


def _member(seed, team, role="viewer"):
    user = seed.user()
    seed.db.table("team_members").insert({"team_id": team["id"], "user_id": user.id, "role": role}).execute()
    return user


def _invite(client, team, email="invitee@example.com", role="editor") -> dict:
    act_as(team["owner"])
    resp = client.post(f"/api/dashboard/teams/{team['slug']}/invites", json={"email": email, "role": role})
    assert resp.status_code == 201, resp.text
    return {**resp.json(), "id": _invite_id(resp.json()["token"])}


def _invite_id(token: str) -> str:
    """The create response carries the token, not the invite id."""
    return get_admin_client().table("team_invitations").select("id").eq("token", token).execute().data[0]["id"]


class TestMembershipEvents:
    def test_accepting_an_invite_records_member_joined(self, client, seed, team):
        invite = _invite(client, team, role="editor")
        joiner = seed.user()
        act_as(joiner)

        assert client.post("/api/invite/accept", json={"token": invite["token"]}).status_code == 200

        event = _only(seed, team, "member_joined")
        assert event["user_id"] == joiner.id
        assert event["payload"] == {"role": "editor"}

    def test_owner_removing_a_member_records_member_removed(self, client, seed, team):
        member = _member(seed, team)
        act_as(team["owner"])

        resp = client.request("DELETE", f"/api/dashboard/teams/{team['slug']}/members", json={"user_id": member.id})

        assert resp.status_code == 200
        event = _only(seed, team, "member_removed")
        assert event["user_id"] == team["owner"].id
        assert event["payload"] == {"user_id": member.id}

    def test_leaving_records_member_left(self, client, seed, team):
        member = _member(seed, team)
        act_as(member)

        resp = client.request("DELETE", f"/api/dashboard/teams/{team['slug']}/members", json={"user_id": member.id})

        assert resp.status_code == 200
        event = _only(seed, team, "member_left")
        assert event["user_id"] == member.id
        assert event["payload"] == {"user_id": member.id}

    def test_removing_someone_who_is_not_a_member_records_nothing(self, client, seed, team):
        stranger = seed.user()
        act_as(team["owner"])

        client.request("DELETE", f"/api/dashboard/teams/{team['slug']}/members", json={"user_id": stranger.id})

        assert _events(seed, team) == []

    def test_changing_a_role_records_role_changed(self, client, seed, team):
        member = _member(seed, team, role="viewer")
        act_as(team["owner"])

        resp = client.patch(
            f"/api/dashboard/teams/{team['slug']}/members", json={"user_id": member.id, "role": "editor"},
        )

        assert resp.status_code == 200
        event = _only(seed, team, "role_changed")
        assert event["user_id"] == team["owner"].id
        assert event["payload"] == {"user_id": member.id, "role": "editor", "previous_role": "viewer"}


class TestInviteEvents:
    def test_sending_an_invite_records_invite_sent(self, client, seed, team):
        invite = _invite(client, team, email="new@example.com", role="viewer")

        event = _only(seed, team, "invite_sent")
        assert event["user_id"] == team["owner"].id
        assert event["payload"] == {"invite_id": invite["id"], "email": "new@example.com", "role": "viewer"}
        assert "token" not in event["payload"]

    def test_bulk_invites_record_one_event_per_sent_invite(self, client, seed, team):
        act_as(team["owner"])

        resp = client.post(
            f"/api/dashboard/teams/{team['slug']}/invites/bulk",
            json={"emails": ["a@example.com", "b@example.com"], "role": "viewer"},
        )

        assert resp.json()["success"] == 2
        sent = [e for e in _events(seed, team) if e["event_type"] == "invite_sent"]
        assert len(sent) == 2

    def test_revoking_an_invite_records_invite_revoked(self, client, seed, team):
        invite = _invite(client, team, email="gone@example.com")

        resp = client.request(
            "DELETE", f"/api/dashboard/teams/{team['slug']}/invites", json={"invite_id": invite["id"]},
        )

        assert resp.status_code == 200
        event = _only(seed, team, "invite_revoked")
        assert event["payload"] == {"invite_id": invite["id"], "email": "gone@example.com"}

    def test_revoking_an_unknown_invite_records_nothing(self, client, seed, team):
        act_as(team["owner"])

        client.request(
            "DELETE", f"/api/dashboard/teams/{team['slug']}/invites", json={"invite_id": str(uuid.uuid4())},
        )

        assert _events(seed, team) == []


class TestShareEvents:
    def _team_key(self, team) -> None:
        key = ApiKeyAuth(user_id=team["owner"].id, key_id="k", team_id=team["id"])
        app.dependency_overrides[get_api_key] = lambda: key

    def test_team_key_document_records_share_added_and_its_delete_share_removed(self, client, seed, team):
        self._team_key(team)

        created = client.post("/api/v1/documents", json={"content": "# team doc", "filename": "t.md"})
        assert created.status_code in (200, 201), created.text
        slug = created.json()["slug"]
        added = _only(seed, team, "share_added")

        assert client.delete(f"/api/v1/documents/{slug}").status_code == 204

        removed = _only(seed, team, "share_removed")
        assert added["user_id"] == removed["user_id"] == team["owner"].id
        assert added["payload"]["slug"] == removed["payload"]["slug"] == slug
        assert added["payload"]["share_id"] == removed["payload"]["share_id"]

    def test_owner_deleting_a_team_share_records_share_removed(self, client, seed, team):
        share = seed.share(team["owner"], is_private=False)
        seed.db.table("team_shares").insert(
            {"team_id": team["id"], "share_id": share["id"], "shared_by": team["owner"].id}
        ).execute()
        act_as(team["owner"])

        assert client.delete(f"/api/shares/{share['slug']}").status_code == 200

        event = _only(seed, team, "share_removed")
        assert event["user_id"] == team["owner"].id
        assert event["payload"] == {"share_id": share["id"], "slug": share["slug"]}


def test_events_feed_returns_recorded_events_newest_first_with_object_payloads(client, seed, team):
    _invite(client, team, email="first@example.com")
    _invite(client, team, email="second@example.com")
    act_as(team["owner"])

    resp = client.get(f"/api/dashboard/teams/{team['slug']}/events")

    assert resp.status_code == 200
    body = resp.json()
    assert [e["payload"]["email"] for e in body] == ["second@example.com", "first@example.com"]
    assert set(body[0]) == {"id", "team_id", "user_id", "event_type", "payload", "created_at"}
