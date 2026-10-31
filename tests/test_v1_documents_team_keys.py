"""Live-DB tests: what v1 API keys read and write on upload-source and private team shares.

Runs against the real Postgres + MinIO from CI. Only the API-key dependency is
overridden; share rows, storage objects and team links are real.
"""

from __future__ import annotations

import pytest

from app.dependencies import ApiKeyAuth, get_api_key
from app.main import app
from core.security import hash_password
from tests.conftest import PRIVATE_BODY, PUBLIC_BODY


def _key_for_team(seed, member, *shares):
    """A team key whose team holds `shares`."""
    seed.team_with_share(member, shares[0])
    team_id = seed.teams[-1]
    for share in shares[1:]:
        seed.db.table("team_shares").insert(
            {"team_id": team_id, "share_id": share["id"], "shared_by": share["user_id"]}
        ).execute()
    return ApiKeyAuth(user_id=member.id, key_id="k", team_id=team_id)


def _use(key: ApiKeyAuth) -> None:
    app.dependency_overrides[get_api_key] = lambda: key


@pytest.fixture
def missing_document_body(client, seed):
    _use(ApiKeyAuth(user_id=seed.user().id, key_id="k"))
    resp = client.get("/api/v1/documents/does-not-exist")
    assert resp.status_code == 404
    return resp.json()


class TestTeamKeyContent:
    def test_team_listing_returns_content_of_upload_source_shares(self, client, seed):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, body=PUBLIC_BODY, source="upload")
        _use(_key_for_team(seed, member, share))

        resp = client.get("/api/v1/documents")

        assert resp.status_code == 200
        assert [(d["slug"], d["content"]) for d in resp.json()] == [(share["slug"], PUBLIC_BODY)]

    def test_team_key_reads_an_open_upload_source_share(self, client, seed):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, body=PUBLIC_BODY, source="upload")
        _use(_key_for_team(seed, member, share))

        resp = client.get(f"/api/v1/documents/{share['slug']}")

        assert resp.status_code == 200
        assert resp.json()["content"] == PUBLIC_BODY

    def test_team_key_gets_404_for_a_private_team_share(self, client, seed, missing_document_body):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=True)
        _use(_key_for_team(seed, member, share))

        resp = client.get(f"/api/v1/documents/{share['slug']}")

        assert resp.status_code == 404
        assert resp.json() == missing_document_body
        assert PRIVATE_BODY not in resp.text

    def test_team_key_gets_404_for_a_password_team_share(self, client, seed, missing_document_body):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, password_hash=hash_password("pw"))
        _use(_key_for_team(seed, member, share))

        resp = client.get(f"/api/v1/documents/{share['slug']}")

        assert resp.status_code == 404
        assert resp.json() == missing_document_body

    def test_team_listing_skips_private_and_password_shares(self, client, seed):
        owner, member = seed.user(), seed.user()
        open_share = seed.share(owner, is_private=False, body=PUBLIC_BODY)
        private = seed.share(owner, is_private=True)
        locked = seed.share(owner, is_private=False, password_hash=hash_password("pw"))
        _use(_key_for_team(seed, member, open_share, private, locked))

        resp = client.get("/api/v1/documents")

        assert resp.status_code == 200
        assert [d["slug"] for d in resp.json()] == [open_share["slug"]]
        assert PRIVATE_BODY not in resp.text

    @pytest.mark.parametrize("path", ["/revisions", "/revisions/1"])
    def test_team_key_gets_404_for_revisions_of_a_private_team_share(
        self, client, seed, missing_document_body, path
    ):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=True)
        seed.db.table("share_revisions").insert(
            {"share_id": share["id"], "revision": 1, "content": PRIVATE_BODY}
        ).execute()
        _use(_key_for_team(seed, member, share))

        resp = client.get(f"/api/v1/documents/{share['slug']}{path}")

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Document not found"}
        assert PRIVATE_BODY not in resp.text

    def test_personal_key_owner_still_reads_own_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=True)
        _use(ApiKeyAuth(user_id=owner.id, key_id="k"))

        resp = client.get(f"/api/v1/documents/{share['slug']}")

        assert resp.status_code == 200
        assert resp.json()["content"] == PRIVATE_BODY


class TestUploadSourceStorageBucket:
    def test_patched_content_is_what_the_next_read_returns(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=False, source="upload")
        _use(ApiKeyAuth(user_id=owner.id, key_id="k"))

        patched = client.patch(f"/api/v1/documents/{share['slug']}", json={"content": "<p>new</p>"})
        read = client.get(f"/api/v1/documents/{share['slug']}")

        assert patched.status_code == 200
        assert read.json()["content"] == "<p>new</p>"

    def test_restored_revision_is_what_the_next_read_returns(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=False, source="upload", body=PUBLIC_BODY)
        _use(ApiKeyAuth(user_id=owner.id, key_id="k"))
        client.patch(f"/api/v1/documents/{share['slug']}", json={"content": "<p>new</p>"})

        restored = client.post(f"/api/v1/documents/{share['slug']}/revisions/1/restore")
        read = client.get(f"/api/v1/documents/{share['slug']}")

        assert restored.status_code == 200
        assert read.json()["content"] == PUBLIC_BODY


class TestTeamKeyWrites:
    def test_team_key_patch_of_a_private_team_share_is_404_and_changes_nothing(
        self, client, seed, missing_document_body
    ):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=True, title="before")
        _use(_key_for_team(seed, member, share))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json={"title": "x"})

        assert resp.status_code == 404
        assert resp.json() == missing_document_body
        assert PRIVATE_BODY not in resp.text
        assert seed.db.table("shares").select("title").eq("id", share["id"]).execute().data[0]["title"] == "before"

    def test_team_key_patch_of_a_password_team_share_is_404(self, client, seed, missing_document_body):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, password_hash=hash_password("pw"))
        _use(_key_for_team(seed, member, share))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json={"title": "x"})

        assert resp.status_code == 404
        assert resp.json() == missing_document_body

    @pytest.mark.parametrize("body", [{"is_private": True}, {"title": "x", "is_private": False}])
    def test_team_key_cannot_change_privacy(self, client, seed, body):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, body=PUBLIC_BODY, title="before")
        _use(_key_for_team(seed, member, share))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json=body)

        assert resp.status_code == 403
        row = seed.db.table("shares").select("*").eq("id", share["id"]).execute().data[0]
        assert (row["is_private"], row["title"], row["password_hash"]) == (False, "before", None)

    def test_team_key_cannot_set_a_password_through_patch(self, client, seed):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, body=PUBLIC_BODY)
        _use(_key_for_team(seed, member, share))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json={"password": "hunter22"})

        assert resp.status_code == 400
        row = seed.db.table("shares").select("password_hash").eq("id", share["id"]).execute().data[0]
        assert row["password_hash"] is None

    def test_team_key_still_patches_an_open_team_share(self, client, seed):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, body=PUBLIC_BODY)
        _use(_key_for_team(seed, member, share))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json={"title": "x"})

        assert resp.status_code == 200
        assert resp.json()["title"] == "x"

    def test_personal_key_owner_still_changes_privacy(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=False)
        _use(ApiKeyAuth(user_id=owner.id, key_id="k"))

        resp = client.patch(f"/api/v1/documents/{share['slug']}", json={"is_private": True})

        assert resp.status_code == 200
        assert resp.json()["is_private"] is True

    def test_team_key_restore_on_a_private_team_share_is_404_and_changes_nothing(
        self, client, seed, missing_document_body
    ):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=True)
        seed.db.table("share_revisions").insert(
            {"share_id": share["id"], "revision": 1, "content": "<p>restored</p>"}
        ).execute()
        _use(_key_for_team(seed, member, share))

        resp = client.post(f"/api/v1/documents/{share['slug']}/revisions/1/restore")

        assert resp.status_code == 404
        assert resp.json() == missing_document_body
        assert PRIVATE_BODY not in resp.text
        _use(ApiKeyAuth(user_id=owner.id, key_id="k"))
        assert client.get(f"/api/v1/documents/{share['slug']}").json()["content"] == PRIVATE_BODY

    def test_team_key_restore_on_a_password_team_share_is_404(self, client, seed, missing_document_body):
        owner, member = seed.user(), seed.user()
        share = seed.share(owner, is_private=False, password_hash=hash_password("pw"))
        seed.db.table("share_revisions").insert(
            {"share_id": share["id"], "revision": 1, "content": "<p>restored</p>"}
        ).execute()
        _use(_key_for_team(seed, member, share))

        resp = client.post(f"/api/v1/documents/{share['slug']}/revisions/1/restore")

        assert resp.status_code == 404
        assert resp.json() == missing_document_body
