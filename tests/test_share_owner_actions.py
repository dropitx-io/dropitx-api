"""Live-DB tests: who may delete, burn, protect or re-encrypt a share.

Runs against the real Postgres + MinIO from CI. Only authentication is
overridden; the share rows, storage objects and encryption are real.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import act_as, unique_ip

# method, route suffix, request body for each owner-only share mutation
ROUTES = {
    "delete": ("DELETE", "", {}),
    "burn": ("POST", "/burn", {}),
    "set-password": ("POST", "/set-password", {"password": "hunter22"}),
    "encrypt": ("POST", "/encrypt", {"password": "hunter22"}),
}
route_params = pytest.mark.parametrize("route", ROUTES, ids=list(ROUTES))


def _call(client, route: str, slug: str, delete_token: str | None):
    method, suffix, body = ROUTES[route]
    payload = {**body, **({"delete_token": delete_token} if delete_token is not None else {})}
    return client.request(method, f"/api/shares/{slug}{suffix}", json=payload, headers=unique_ip())


@pytest.fixture
def missing_slug_body(client):
    """Response body of a delete/burn/... against a slug that does not exist."""

    def body_for(route: str) -> dict:
        act_as(None)
        resp = _call(client, route, f"does-not-exist-{uuid.uuid4().hex}", "any-token")
        assert resp.status_code == 404
        return resp.json()

    return body_for


def _row(seed, share: dict) -> dict | None:
    rows = seed.db.table("shares").select("*").eq("id", share["id"]).execute().data
    return rows[0] if rows else None


class TestPrivateShareWrongToken:
    @route_params
    def test_wrong_delete_token_is_indistinguishable_from_a_missing_slug(
        self, client, seed, missing_slug_body, route
    ):
        share = seed.share(seed.user())
        act_as(None)

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 404
        assert resp.json() == missing_slug_body(route)
        assert _row(seed, share) == share

    @route_params
    def test_non_owner_with_a_wrong_token_gets_404(self, client, seed, missing_slug_body, route):
        share = seed.share(seed.user())
        act_as(seed.user())

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 404
        assert resp.json() == missing_slug_body(route)

    @route_params
    def test_correct_delete_token_succeeds(self, client, seed, route):
        share = seed.share(seed.user())
        act_as(None)

        resp = _call(client, route, share["slug"], share["delete_token"])

        assert resp.status_code == 200, resp.text
        assert _row(seed, share) != share

    @route_params
    def test_signed_in_owner_succeeds_without_a_token(self, client, seed, route):
        owner = seed.user()
        share = seed.share(owner)
        act_as(owner)

        resp = _call(client, route, share["slug"], None)

        assert resp.status_code == 200, resp.text

    @route_params
    def test_burned_private_share_with_a_wrong_token_is_404_not_410(
        self, client, seed, missing_slug_body, route
    ):
        share = seed.share(seed.user(), burned=True)
        act_as(None)

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 404
        assert resp.json() == missing_slug_body(route)

    @route_params
    def test_expired_private_share_with_a_wrong_token_is_404_and_is_not_deleted(
        self, client, seed, missing_slug_body, route
    ):
        share = seed.share(seed.user(), expires_at="2020-01-01T00:00:00+00:00")
        act_as(None)

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 404
        assert resp.json() == missing_slug_body(route)
        assert _row(seed, share) is not None

    def test_burning_an_already_burned_private_share_as_its_owner_is_410(self, client, seed):
        share = seed.share(seed.user(), burned=True)
        act_as(None)

        resp = _call(client, "burn", share["slug"], share["delete_token"])

        assert resp.status_code == 410


class TestPublicShareWrongToken:
    @route_params
    def test_wrong_delete_token_stays_403(self, client, seed, route):
        share = seed.share(seed.user(), is_private=False)
        act_as(None)

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 403
        assert _row(seed, share) == share

    @route_params
    def test_burned_public_share_with_a_wrong_token_is_403_not_410(self, client, seed, route):
        share = seed.share(seed.user(), is_private=False, burned=True)
        act_as(None)

        resp = _call(client, route, share["slug"], "wrong-token")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /shares/{slug}/reencrypt
# ---------------------------------------------------------------------------

OLD, NEW = "old-pass-1", "new-pass-2"


def _encrypted_share(client, seed, owner, **overrides) -> dict:
    share = seed.share(owner, **overrides)
    act_as(owner)
    resp = client.post(f"/api/shares/{share['slug']}/encrypt", json={"password": OLD}, headers=unique_ip())
    assert resp.status_code == 200, resp.text
    return share


def _reencrypt(client, slug: str, **extra):
    return client.post(
        f"/api/shares/{slug}/reencrypt",
        json={"old_password": OLD, "new_password": NEW, **extra},
        headers=unique_ip(),
    )


class TestReencryptOwnerAuth:
    def test_anonymous_with_only_the_old_password_gets_401(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=False)
        before = _row(seed, share)
        act_as(None)

        resp = _reencrypt(client, share["slug"])

        assert resp.status_code == 401
        assert _row(seed, share)["encryption_salt"] == before["encryption_salt"]

    def test_wrong_delete_token_gets_403_on_a_public_share(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=False)
        act_as(None)

        assert _reencrypt(client, share["slug"], delete_token="wrong").status_code == 403

    def test_anonymous_without_a_token_gets_401_for_a_missing_slug(self, client):
        act_as(None)

        resp = _reencrypt(client, f"does-not-exist-{uuid.uuid4().hex}")

        assert resp.status_code == 401

    def test_non_owner_gets_403_on_a_public_share(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=False)
        before = _row(seed, share)
        act_as(seed.user())

        resp = _reencrypt(client, share["slug"])

        assert resp.status_code == 403
        assert _row(seed, share)["encryption_salt"] == before["encryption_salt"]

    def test_non_owner_gets_404_on_a_private_share(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=True)
        act_as(seed.user())
        missing = _reencrypt(client, f"does-not-exist-{uuid.uuid4().hex}")

        resp = _reencrypt(client, share["slug"])

        assert resp.status_code == 404
        assert resp.json() == missing.json()

    def test_wrong_delete_token_gets_404_on_a_private_share(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=True)
        act_as(None)

        resp = _reencrypt(client, share["slug"], delete_token="wrong-token")

        assert resp.status_code == 404

    def test_signed_in_owner_rotates_the_password(self, client, seed):
        owner = seed.user()
        share = _encrypted_share(client, seed, owner, is_private=True)
        before = _row(seed, share)

        resp = _reencrypt(client, share["slug"])

        assert resp.status_code == 200, resp.text
        assert _row(seed, share)["encryption_salt"] != before["encryption_salt"]
        assert _reencrypt(client, share["slug"]).status_code == 401  # old password no longer decrypts

    def test_delete_token_holder_rotates_the_password(self, client, seed):
        share = _encrypted_share(client, seed, seed.user(), is_private=True)
        act_as(None)

        resp = _reencrypt(client, share["slug"], delete_token=share["delete_token"])

        assert resp.status_code == 200, resp.text
        again = _reencrypt(client, share["slug"], delete_token=share["delete_token"])
        assert again.status_code == 401
        assert again.json()["detail"] == "Incorrect old password"
