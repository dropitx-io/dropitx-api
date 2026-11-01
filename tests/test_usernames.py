"""Usernames: derived on first session, editable through PUT /api/v1/profile.

A username is 3-30 characters of lowercase letters, digits and hyphens, starts and
ends with a letter or digit, is unique, and is not a reserved route word.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.dependencies import get_firebase_claims
from app.main import app
from core.usernames import RESERVED_USERNAMES, derive_username_base, username_candidates, validate_username
from tests.conftest import act_as

AUTH = {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Derivation and validation
# ---------------------------------------------------------------------------

class TestDerivation:
    @pytest.mark.parametrize(
        "email, display_name, expected",
        [
            ("John.Doe+news@example.com", None, "john-doe-news"),
            ("ab@example.com", "Ann Lee", "ann-lee"),
            ("ab@example.com", None, "user"),
            (None, "  Ünïcode Näme!! ", "n-code-n-me"),
            (None, None, "user"),
            ("x" * 50 + "@example.com", None, "x" * 30),
            ("a--b__c@example.com", None, "a-b-c"),
        ],
    )
    def test_base_is_a_valid_username_shape(self, email, display_name, expected):
        assert derive_username_base(email, display_name) == expected

    def test_candidates_add_a_numeric_suffix_within_30_characters(self):
        candidates = username_candidates("x" * 30)
        assert next(candidates) == "x" * 30
        assert next(candidates) == "x" * 29 + "2"

    def test_reserved_words_are_never_candidates(self):
        assert next(username_candidates("admin")) == "admin2"

    @pytest.mark.parametrize("name", ["abc", "a-b", "user-123", "x" * 30])
    def test_valid_usernames(self, name):
        assert validate_username(name) is None

    @pytest.mark.parametrize(
        "name", ["ab", "x" * 31, "has space", "-lead", "trail-", "under_score", "Upper", *sorted(RESERVED_USERNAMES)],
    )
    def test_invalid_usernames(self, name):
        assert validate_username(name) is not None


# ---------------------------------------------------------------------------
# GET /api/auth/session assigns a username
# ---------------------------------------------------------------------------

_claims: dict = {}


@pytest.fixture
def session(client, seed):
    """Call /api/auth/session as a fresh Firebase uid; its rows are removed afterwards."""
    def call(email: str | None, name: str | None = None, uid: str | None = None) -> dict:
        uid = uid or f"un-{uuid.uuid4().hex}"
        if uid not in seed.users:
            seed.users.append(uid)
        _claims.clear()
        _claims.update({"sub": uid, "email": email, "email_verified": True, **({"name": name} if name else {})})
        app.dependency_overrides[get_firebase_claims] = lambda: dict(_claims)
        resp = client.get("/api/auth/session", headers=AUTH)
        assert resp.status_code == 200, resp.text
        return resp.json()
    with patch("app.dependencies.verify_firebase_jwt", side_effect=lambda _t: dict(_claims)):
        yield call


def _stored_username(seed, uid: str) -> str | None:
    return seed.db.table("user_profiles").select("username").eq("user_id", uid).execute().data[0]["username"]


def _unique_local() -> str:
    return f"user{uuid.uuid4().hex[:10]}"


class TestSessionAssignsUsername:
    def test_first_session_derives_it_from_the_email(self, session, seed):
        local = _unique_local()

        body = session(f"{local}@example.com")

        assert body["profile"]["username"] == local
        assert _stored_username(seed, body["id"]) == local

    def test_a_taken_name_gets_a_numeric_suffix(self, session):
        local = _unique_local()
        first = session(f"{local}@example.com")
        second = session(f"{local}@other.example")

        assert first["profile"]["username"] == local
        assert second["profile"]["username"] == f"{local}2"

    def test_falls_back_to_the_display_name(self, session):
        name = f"Display {uuid.uuid4().hex[:8]}"

        body = session("ab@example.com", name=name)

        assert body["profile"]["username"] == name.lower().replace(" ", "-")

    def test_an_existing_user_without_one_gets_it_on_the_next_session(self, session, seed):
        user = seed.user()
        seed.db.table("user_profiles").insert({"user_id": user.id}).execute()
        local = _unique_local()

        body = session(f"{local}@example.com", uid=user.id)

        assert body["profile"]["username"] == local

    def test_an_existing_username_is_never_replaced(self, session, seed):
        user = seed.user()
        kept = f"kept-{uuid.uuid4().hex[:8]}"
        seed.db.table("user_profiles").insert({"user_id": user.id, "username": kept}).execute()

        body = session(f"{_unique_local()}@example.com", uid=user.id)

        assert body["profile"]["username"] == kept
        assert _stored_username(seed, user.id) == kept


# ---------------------------------------------------------------------------
# PUT /api/v1/profile sets a username
# ---------------------------------------------------------------------------

URL = "/api/v1/profile"


class TestProfileUsername:
    def test_sets_the_username_and_returns_it(self, client, seed):
        user = seed.user()
        act_as(user)
        name = f"me-{uuid.uuid4().hex[:8]}"

        resp = client.put(URL, json={"display_name": "Me", "username": name})

        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == name
        assert _stored_username(seed, user.id) == name

    def test_input_is_trimmed_and_lowercased(self, client, seed):
        user = seed.user()
        act_as(user)
        name = f"Me-{uuid.uuid4().hex[:8]}"

        resp = client.put(URL, json={"display_name": "Me", "username": f"  {name} "})

        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == name.lower()

    def test_a_name_taken_by_someone_else_is_409(self, client, seed):
        owner, caller = seed.user(), seed.user()
        taken = f"taken-{uuid.uuid4().hex[:8]}"
        seed.db.table("user_profiles").insert({"user_id": owner.id, "username": taken}).execute()
        seed.db.table("user_profiles").insert({"user_id": caller.id, "username": f"c-{uuid.uuid4().hex[:8]}"}).execute()
        act_as(caller)

        resp = client.put(URL, json={"display_name": "Me", "username": taken})

        assert resp.status_code == 409
        assert _stored_username(seed, owner.id) == taken

    def test_keeping_ones_own_name_is_fine(self, client, seed):
        user = seed.user()
        mine = f"mine-{uuid.uuid4().hex[:8]}"
        seed.db.table("user_profiles").insert({"user_id": user.id, "username": mine}).execute()
        act_as(user)

        resp = client.put(URL, json={"display_name": "Me", "username": mine})

        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("name", ["ab", "x" * 31, "has space", "-lead", "under_score", "admin", "embed", "u"])
    def test_an_invalid_or_reserved_name_is_422_and_changes_nothing(self, client, seed, name):
        user = seed.user()
        mine = f"mine-{uuid.uuid4().hex[:8]}"
        seed.db.table("user_profiles").insert({"user_id": user.id, "username": mine}).execute()
        act_as(user)

        resp = client.put(URL, json={"display_name": "Me", "username": name})

        assert resp.status_code == 422
        assert _stored_username(seed, user.id) == mine

    def test_omitting_username_leaves_it_unchanged(self, client, seed):
        user = seed.user()
        mine = f"mine-{uuid.uuid4().hex[:8]}"
        seed.db.table("user_profiles").insert({"user_id": user.id, "username": mine}).execute()
        act_as(user)

        resp = client.put(URL, json={"display_name": "Renamed"})

        assert resp.status_code == 200
        assert resp.json()["username"] == mine

    def test_is_public_can_be_switched_on_and_off(self, client, seed):
        user = seed.user()
        act_as(user)

        on = client.put(URL, json={"display_name": "Me", "is_public": True})
        off = client.put(URL, json={"display_name": "Me", "is_public": False})

        assert on.json()["is_public"] is True
        assert off.json()["is_public"] is False
