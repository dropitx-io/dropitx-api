"""Live-DB tests: the dashboard share list, favorites, and the team role/column shapes.

Runs against the real Postgres + MinIO from CI. Only authentication is overridden.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from core.security import hash_password
from tests.conftest import Seed, act_as, walk_keys

SECRET_KEYS = {"password_hash", "delete_token", "content", "content_text", "storage_path"}


def _ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# GET /api/dashboard/shares
# ---------------------------------------------------------------------------

class TestMyShares:
    def test_requires_authentication(self, client):
        app.dependency_overrides.clear()

        assert client.get("/api/dashboard/shares").status_code == 401

    def test_lists_only_the_callers_shares_newest_first(self, client, seed):
        me, other = seed.user(), seed.user()
        oldest = seed.share(me, is_private=False, created_at=_ago(3))
        newest = seed.share(me, is_private=False, created_at=_ago(1))
        middle = seed.share(me, is_private=False, created_at=_ago(2))
        seed.share(other, is_private=False, created_at=_ago(0))
        act_as(me)

        resp = client.get("/api/dashboard/shares")

        assert resp.status_code == 200
        body = resp.json()
        assert [i["id"] for i in body["items"]] == [newest["id"], middle["id"], oldest["id"]]
        assert (body["total"], body["page"], body["limit"]) == (3, 1, 20)
        assert all(i["is_owner"] is True for i in body["items"])

    def test_owner_view_includes_private_and_expired_shares(self, client, seed):
        me = seed.user()
        private = seed.share(me, is_private=True, created_at=_ago(1))
        expired = seed.share(me, is_private=False, expires_at=_ago(5), created_at=_ago(2))
        act_as(me)

        body = client.get("/api/dashboard/shares").json()

        by_id = {i["id"]: i for i in body["items"]}
        assert set(by_id) == {private["id"], expired["id"]}
        assert by_id[private["id"]]["is_private"] is True
        assert by_id[expired["id"]]["expires_at"] is not None

    def test_reports_has_password_and_never_returns_secrets(self, client, seed):
        me = seed.user()
        protected = seed.share(
            me, is_private=False, password_hash=hash_password("hunter2"), created_at=_ago(1),
        )
        open_share = seed.share(me, is_private=False, created_at=_ago(2))
        act_as(me)

        resp = client.get("/api/dashboard/shares")

        by_id = {i["id"]: i for i in resp.json()["items"]}
        assert by_id[protected["id"]]["has_password"] is True
        assert by_id[open_share["id"]]["has_password"] is False
        assert not SECRET_KEYS & set(walk_keys(resp.json()))
        assert protected["delete_token"] not in resp.text
        assert protected["storage_path"] not in resp.text

    def test_paginates_with_totals(self, client, seed):
        me = seed.user()
        shares = [seed.share(me, is_private=False, created_at=_ago(h)) for h in (5, 4, 3, 2, 1)]
        newest_first = [s["id"] for s in reversed(shares)]
        act_as(me)

        first = client.get("/api/dashboard/shares?page=1&limit=2").json()
        second = client.get("/api/dashboard/shares?page=2&limit=2").json()
        last = client.get("/api/dashboard/shares?page=3&limit=2").json()
        beyond = client.get("/api/dashboard/shares?page=4&limit=2").json()

        assert [i["id"] for i in first["items"]] == newest_first[0:2]
        assert [i["id"] for i in second["items"]] == newest_first[2:4]
        assert [i["id"] for i in last["items"]] == newest_first[4:5]
        assert beyond["items"] == []
        for body, page in ((first, 1), (second, 2), (last, 3), (beyond, 4)):
            assert (body["total"], body["page"], body["limit"]) == (5, page, 2)

    def test_another_users_pages_never_show_my_shares(self, client, seed):
        me, other = seed.user(), seed.user()
        mine = seed.share(me, is_private=False)
        act_as(other)

        body = client.get("/api/dashboard/shares").json()

        assert body["items"] == [] and body["total"] == 0
        assert mine["id"] not in str(body)

    @pytest.mark.parametrize(
        "query",
        ["page=0", "page=-1", "limit=0", "limit=101", "limit=-5", "page=abc"],
    )
    def test_rejects_out_of_range_paging(self, client, seed, query):
        act_as(seed.user())

        assert client.get(f"/api/dashboard/shares?{query}").status_code == 422

    def test_accepts_the_maximum_limit(self, client, seed):
        act_as(seed.user())

        resp = client.get("/api/dashboard/shares?limit=100")

        assert resp.status_code == 200 and resp.json()["limit"] == 100


# ---------------------------------------------------------------------------
# /api/v1/favorites
# ---------------------------------------------------------------------------

class TestFavorites:
    def test_requires_firebase_authentication(self, client, seed):
        share = seed.share(seed.user(), is_private=False)
        app.dependency_overrides.clear()

        assert client.get("/api/v1/favorites").status_code == 401
        assert client.get(f"/api/v1/favorites/{share['id']}").status_code == 401
        assert client.post(f"/api/v1/favorites/{share['id']}").status_code == 401
        assert client.delete(f"/api/v1/favorites/{share['id']}").status_code == 401

    def test_add_list_and_remove(self, client, seed):
        owner, me = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, title="Bookmarked")
        act_as(me)

        assert client.get("/api/v1/favorites").json() == []
        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": False}

        added = client.post(f"/api/v1/favorites/{share['id']}")
        assert added.status_code == 200 and added.json() == {"favorited": True}
        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": True}

        listed = client.get("/api/v1/favorites")
        assert listed.status_code == 200
        [item] = listed.json()
        assert item["id"] == share["id"] and item["slug"] == share["slug"]
        assert item["title"] == "Bookmarked"
        assert item["has_password"] is False
        assert item["favorited_at"]

        removed = client.delete(f"/api/v1/favorites/{share['id']}")
        assert removed.status_code == 200 and removed.json() == {"favorited": False}
        assert client.get("/api/v1/favorites").json() == []
        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": False}

    def test_add_and_remove_are_idempotent(self, client, seed):
        me = seed.user()
        share = seed.share(seed.user(), is_private=False)
        act_as(me)

        assert client.delete(f"/api/v1/favorites/{share['id']}").status_code == 200
        assert client.post(f"/api/v1/favorites/{share['id']}").status_code == 200
        assert client.post(f"/api/v1/favorites/{share['id']}").status_code == 200
        assert len(client.get("/api/v1/favorites").json()) == 1
        assert client.delete(f"/api/v1/favorites/{share['id']}").status_code == 200
        assert client.delete(f"/api/v1/favorites/{share['id']}").status_code == 200
        assert client.get("/api/v1/favorites").json() == []

    def test_lists_newest_favorite_first(self, client, seed):
        me = seed.user()
        first = seed.share(seed.user(), is_private=False)
        second = seed.share(seed.user(), is_private=False)
        act_as(me)

        client.post(f"/api/v1/favorites/{first['id']}")
        client.post(f"/api/v1/favorites/{second['id']}")

        assert [i["id"] for i in client.get("/api/v1/favorites").json()] == [
            second["id"], first["id"],
        ]

    def test_share_made_private_after_favoriting_disappears(self, client, seed):
        owner, me = seed.user(), seed.user()
        share = seed.share(owner, is_private=False)
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")
        seed.db.table("shares").update({"is_private": True}).eq("id", share["id"]).execute()

        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": False}
        assert client.get("/api/v1/favorites").json() == []

    @pytest.mark.parametrize("ended", [
        {"expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
        {"burned": True},
    ], ids=["expired", "burned"])
    def test_ended_share_is_hidden_from_non_owner_favorites(self, client, seed, ended):
        owner, me = seed.user(), seed.user()
        share = seed.share(owner, is_private=False)
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")
        seed.db.table("shares").update(ended).eq("id", share["id"]).execute()

        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": False}
        assert client.get("/api/v1/favorites").json() == []

    def test_owner_keeps_own_expired_share_as_favorite(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=False)
        act_as(owner)
        client.post(f"/api/v1/favorites/{share['id']}")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        seed.db.table("shares").update({"expires_at": past}).eq("id", share["id"]).execute()

        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": True}
        assert [i["id"] for i in client.get("/api/v1/favorites").json()] == [share["id"]]

    def test_favorites_are_per_user(self, client, seed):
        me, other = seed.user(), seed.user()
        share = seed.share(seed.user(), is_private=False)
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")

        act_as(other)

        assert client.get("/api/v1/favorites").json() == []
        assert client.get(f"/api/v1/favorites/{share['id']}").json() == {"favorited": False}
        client.delete(f"/api/v1/favorites/{share['id']}")

        act_as(me)
        assert len(client.get("/api/v1/favorites").json()) == 1

    def test_list_never_returns_secrets(self, client, seed):
        me = seed.user()
        share = seed.share(
            seed.user(), is_private=False, password_hash=hash_password("hunter2"),
        )
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")

        resp = client.get("/api/v1/favorites")

        assert resp.json()[0]["has_password"] is True
        assert not SECRET_KEYS & set(walk_keys(resp.json()))
        assert share["delete_token"] not in resp.text
        assert share["storage_path"] not in resp.text

    def test_missing_and_invisible_shares_are_the_same_404(self, client, seed):
        owner, me = seed.user(), seed.user()
        private = seed.share(owner, is_private=True)
        act_as(me)

        missing = client.post(f"/api/v1/favorites/{uuid.uuid4()}")
        not_a_uuid = client.post("/api/v1/favorites/not-a-uuid")
        hidden = client.post(f"/api/v1/favorites/{private['id']}")

        assert missing.status_code == 404
        assert not_a_uuid.status_code == 404 and not_a_uuid.json() == missing.json()
        assert hidden.status_code == 404 and hidden.json() == missing.json()
        assert client.get("/api/v1/favorites").json() == []

    def test_owner_can_favorite_their_own_private_share(self, client, seed):
        me = seed.user()
        private = seed.share(me, is_private=True)
        act_as(me)

        assert client.post(f"/api/v1/favorites/{private['id']}").status_code == 200
        [item] = client.get("/api/v1/favorites").json()
        assert item["id"] == private["id"] and item["is_private"] is True

    def test_share_that_turned_private_drops_out_of_the_list(self, client, seed):
        owner, me = seed.user(), seed.user()
        share = seed.share(owner, is_private=False)
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")

        seed.db.table("shares").update({"is_private": True}).eq("id", share["id"]).execute()

        assert client.get("/api/v1/favorites").json() == []

    def test_deleting_the_share_removes_the_favorite(self, client, seed):
        me = seed.user()
        share = seed.share(seed.user(), is_private=False)
        act_as(me)
        client.post(f"/api/v1/favorites/{share['id']}")

        seed.db.table("shares").delete().eq("id", share["id"]).execute()

        assert client.get("/api/v1/favorites").json() == []
        assert seed.db.table("favorites").select("share_id").eq("user_id", me.id).execute().data == []


# ---------------------------------------------------------------------------
# Team responses: caller role and schema column names
# ---------------------------------------------------------------------------

def _team_with_members(seed: Seed, **roles) -> str:
    """A team owned by roles['owner'] with one member per named role; returns the slug."""
    slug = f"dash-team-{uuid.uuid4().hex[:10]}"
    owner = roles["owner"]
    team = seed.db.table("teams").insert(
        {"name": "Dash team", "slug": slug, "owner_id": owner.id}
    ).execute().data[0]
    seed.teams.append(team["id"])
    for role, user in roles.items():
        seed.db.table("team_members").insert(
            {"team_id": team["id"], "user_id": user.id, "role": role}
        ).execute()
    return slug


class TestTeamResponses:
    @pytest.mark.parametrize("role", ["owner", "editor", "viewer"])
    def test_get_team_reports_the_callers_role(self, client, seed, role):
        users = {r: seed.user() for r in ("owner", "editor", "viewer")}
        slug = _team_with_members(seed, **users)
        act_as(users[role])

        resp = client.get(f"/api/dashboard/teams/{slug}")

        assert resp.status_code == 200
        assert resp.json()["role"] == role
        assert resp.json()["slug"] == slug

    def test_get_team_still_refuses_non_members(self, client, seed):
        slug = _team_with_members(seed, owner=seed.user())
        act_as(seed.user())

        assert client.get(f"/api/dashboard/teams/{slug}").status_code == 403

    def test_team_rows_carry_the_schema_column_names(self, client, seed):
        owner = seed.user()
        slug = _team_with_members(seed, owner=owner)
        act_as(owner)

        team = client.get(f"/api/dashboard/teams/{slug}").json()
        listed = client.get("/api/dashboard/teams").json()

        assert team["owner_id"] == owner.id and team["plan"] == "free"
        assert "created_by" not in team
        [membership] = [m for m in listed if m["teams"]["slug"] == slug]
        assert membership["role"] == "owner" and membership["joined_at"]
        assert membership["teams"]["owner_id"] == owner.id
        assert membership["teams"]["plan"] == "free"
        assert "created_by" not in membership["teams"]

    def test_team_events_carry_the_schema_column_names(self, client, seed):
        owner = seed.user()
        slug = _team_with_members(seed, owner=owner)
        team_id = seed.db.table("teams").select("id").eq("slug", slug).execute().data[0]["id"]
        seed.db.table("team_events").insert({
            "team_id": team_id,
            "user_id": owner.id,
            "event_type": "member_joined",
            "payload": json.dumps({"target_user_id": "someone"}),
        }).execute()
        act_as(owner)

        resp = client.get(f"/api/dashboard/teams/{slug}/events?limit=10")

        assert resp.status_code == 200
        [event] = resp.json()
        assert event["event_type"] == "member_joined"
        assert event["user_id"] == owner.id
        assert event["payload"] == {"target_user_id": "someone"}
        assert not {"actor_id", "target_user_id", "metadata"} & set(event)
