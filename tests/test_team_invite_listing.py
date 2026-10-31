"""Live-DB tests: GET /api/dashboard/teams/{slug}/invites only shows tokens to owners and admins."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import act_as


@pytest.fixture
def team(seed):
    """A team owned by one user with one pending invite; `join` adds members."""

    class _Team:
        def __init__(self):
            self.owner = seed.user()
            row = seed.db.table("teams").insert(
                {"name": "Listing Team", "slug": f"lst-{uuid.uuid4().hex[:10]}", "owner_id": self.owner.id}
            ).execute().data[0]
            seed.teams.append(row["id"])
            self.id, self.slug = row["id"], row["slug"]
            self.join(self.owner, "owner")
            self.invite = seed.db.table("team_invitations").insert({
                "team_id": self.id, "email": f"guest-{uuid.uuid4().hex[:8]}@example.com",
                "role": "viewer", "invited_by": self.owner.id, "token": f"tok-{uuid.uuid4().hex}",
            }).execute().data[0]

        def join(self, user, role):
            seed.db.table("team_members").insert(
                {"team_id": self.id, "user_id": user.id, "role": role}
            ).execute()
            return user

    return _Team()


def _list(client, team):
    return client.get(f"/api/dashboard/teams/{team.slug}/invites")


class TestInviteListingToken:
    def test_owner_sees_the_token(self, client, team):
        act_as(team.owner)

        resp = _list(client, team)

        assert resp.status_code == 200, resp.text
        [row] = resp.json()
        assert row["token"] == team.invite["token"]
        assert row["email"] == team.invite["email"]

    @pytest.mark.parametrize("role", ["viewer", "editor"])
    def test_other_members_get_rows_without_a_token_key(self, client, seed, team, role):
        member = team.join(seed.user(), role)
        act_as(member)

        resp = _list(client, team)

        assert resp.status_code == 200, resp.text
        [row] = resp.json()
        assert "token" not in row
        assert team.invite["token"] not in resp.text
        assert row["id"] == team.invite["id"]
        assert row["email"] == team.invite["email"]
        assert row["status"] == "pending"

    def test_non_member_is_still_403(self, client, seed, team):
        act_as(seed.user())

        assert _list(client, team).status_code == 403
