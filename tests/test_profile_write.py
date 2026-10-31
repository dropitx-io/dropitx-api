"""Live-DB tests: PUT /api/v1/profile sets the signed-in user's display name."""

from __future__ import annotations

import pytest

from tests.conftest import act_as

URL = "/api/v1/profile"


def _profile(seed, user) -> dict | None:
    rows = seed.db.table("user_profiles").select("*").eq("user_id", user.id).execute().data
    return rows[0] if rows else None


class TestUpdateProfile:
    def test_updates_the_callers_row_and_returns_it(self, client, seed):
        user = seed.user()
        seed.db.table("user_profiles").insert(
            {"user_id": user.id, "display_name": "Old Name", "avatar_url": "https://img.test/a.png"}
        ).execute()
        act_as(user)

        resp = client.put(URL, json={"display_name": "New Name"})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"display_name": "New Name", "avatar_url": "https://img.test/a.png"}
        assert _profile(seed, user)["display_name"] == "New Name"

    def test_response_exposes_only_display_name_and_avatar_url(self, client, seed):
        user = seed.user()
        username = f"u{user.id[-8:]}"
        seed.db.table("user_profiles").insert(
            {"user_id": user.id, "username": username, "bio": "private bio"}
        ).execute()
        act_as(user)

        body = client.put(URL, json={"display_name": "Someone"}).json()

        assert set(body) == {"display_name", "avatar_url"}
        assert body["avatar_url"] is None
        row = _profile(seed, user)
        assert row["username"] == username
        assert row["bio"] == "private bio"

    def test_creates_the_profile_row_when_the_caller_has_none(self, client, seed):
        user = seed.user()
        assert _profile(seed, user) is None
        act_as(user)

        resp = client.put(URL, json={"display_name": "First Name"})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"display_name": "First Name", "avatar_url": None}
        assert _profile(seed, user)["display_name"] == "First Name"

    def test_trims_surrounding_whitespace(self, client, seed):
        user = seed.user()
        act_as(user)

        resp = client.put(URL, json={"display_name": "  Padded Name \n"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["display_name"] == "Padded Name"
        assert _profile(seed, user)["display_name"] == "Padded Name"

    def test_does_not_touch_another_users_profile(self, client, seed):
        caller, other = seed.user(), seed.user()
        seed.db.table("user_profiles").insert(
            {"user_id": other.id, "display_name": "Other Person"}
        ).execute()
        act_as(caller)

        resp = client.put(URL, json={"display_name": "Caller Name"})

        assert resp.status_code == 200, resp.text
        assert _profile(seed, other)["display_name"] == "Other Person"

    def test_anonymous_caller_is_401(self, client):
        act_as(None)

        resp = client.put(URL, json={"display_name": "Nobody"})

        assert resp.status_code == 401

    @pytest.mark.parametrize(
        "display_name",
        ["", "   ", "x" * 101, "  " + "x" * 101 + "  "],
        ids=["empty", "whitespace-only", "101-chars", "101-chars-padded"],
    )
    def test_invalid_display_name_is_422_and_changes_nothing(self, client, seed, display_name):
        user = seed.user()
        seed.db.table("user_profiles").insert(
            {"user_id": user.id, "display_name": "Keep Me"}
        ).execute()
        act_as(user)

        resp = client.put(URL, json={"display_name": display_name})

        assert resp.status_code == 422
        assert _profile(seed, user)["display_name"] == "Keep Me"

    def test_a_name_of_exactly_100_characters_is_accepted(self, client, seed):
        user = seed.user()
        act_as(user)

        resp = client.put(URL, json={"display_name": "x" * 100})

        assert resp.status_code == 200, resp.text
        assert resp.json()["display_name"] == "x" * 100

    def test_missing_display_name_is_422(self, client, seed):
        act_as(seed.user())

        assert client.put(URL, json={}).status_code == 422
