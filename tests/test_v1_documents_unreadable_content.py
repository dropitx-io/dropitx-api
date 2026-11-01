"""Live-DB tests: a document whose stored bytes are not text never fails the v1 API.

Runs against the real Postgres + MinIO from CI. Only the API-key dependency is
overridden; share rows and storage objects are real.
"""

from __future__ import annotations

from app.dependencies import ApiKeyAuth, get_api_key
from app.main import app
from tests.conftest import PUBLIC_BODY

CIPHERTEXT = b"\xb6\xff\x00\x13\x9c binary ciphertext \xfe"


def _use_personal_key(user) -> None:
    app.dependency_overrides[get_api_key] = lambda: ApiKeyAuth(user_id=user.id, key_id="k")


def _encrypted_share(seed, owner) -> dict:
    share = seed.share(owner, is_private=False, encrypted=True,
                       encryption_iv="iv", encryption_salt="salt", password_hash="x")
    seed.db.storage.from_("html-files").upload(share["storage_path"], CIPHERTEXT)
    return share


def _missing_object_share(seed, owner) -> dict:
    share = seed.share(owner, is_private=False, burned=True)
    seed.db.storage.from_("html-files").remove([share["storage_path"]])
    return share


class TestListingWithUnreadableContent:
    def test_an_encrypted_binary_document_is_listed_without_content(self, client, seed):
        owner = seed.user()
        readable = seed.share(owner, is_private=False, body=PUBLIC_BODY)
        encrypted = _encrypted_share(seed, owner)
        _use_personal_key(owner)

        resp = client.get("/api/v1/documents")

        assert resp.status_code == 200, resp.text
        by_slug = {d["slug"]: d for d in resp.json()}
        assert by_slug[readable["slug"]]["content"] == PUBLIC_BODY
        assert by_slug[encrypted["slug"]]["content"] == ""
        assert by_slug[encrypted["slug"]]["encrypted"] is True

    def test_a_document_whose_object_is_gone_is_listed_without_content(self, client, seed):
        owner = seed.user()
        readable = seed.share(owner, is_private=False, body=PUBLIC_BODY)
        gone = _missing_object_share(seed, owner)
        _use_personal_key(owner)

        resp = client.get("/api/v1/documents")

        assert resp.status_code == 200, resp.text
        by_slug = {d["slug"]: d for d in resp.json()}
        assert by_slug[readable["slug"]]["content"] == PUBLIC_BODY
        assert by_slug[gone["slug"]]["content"] == ""


class TestGettingUnreadableContent:
    def test_an_encrypted_binary_document_is_returned_without_content(self, client, seed):
        owner = seed.user()
        encrypted = _encrypted_share(seed, owner)
        _use_personal_key(owner)

        resp = client.get(f"/api/v1/documents/{encrypted['slug']}")

        assert resp.status_code == 200, resp.text
        assert resp.json()["content"] == ""
        assert resp.json()["encrypted"] is True

    def test_a_burned_document_is_gone(self, client, seed):
        owner = seed.user()
        gone = _missing_object_share(seed, owner)
        _use_personal_key(owner)

        resp = client.get(f"/api/v1/documents/{gone['slug']}")

        assert resp.status_code == 410, resp.text
