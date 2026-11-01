"""Live-DB tests: burning a share removes its stored bytes, and its owner can still delete it.

Runs against the real Postgres + MinIO from CI. Only authentication is
overridden; share rows and storage objects are real.
"""

from __future__ import annotations

import pytest

from tests.conftest import PUBLIC_BODY, act_as, unique_ip


def _object_exists(seed, path: str) -> bool:
    try:
        seed.db.storage.from_("html-files").download(path)
    except Exception:
        return False
    return True


def _row(seed, share: dict) -> dict | None:
    rows = seed.db.table("shares").select("*").eq("id", share["id"]).execute().data
    return rows[0] if rows else None


class TestBurningRemovesContent:
    def test_first_read_of_a_burn_after_reading_share_removes_its_object(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False, burn_after_reading=True)
        act_as(None)

        first = client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip())
        second = client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip())

        assert first.status_code == 200 and first.json()["content"] == PUBLIC_BODY
        assert not _object_exists(seed, share["storage_path"])
        assert second.status_code == 410

    def test_consuming_a_one_time_download_removes_its_object(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False, one_time_download=True)
        act_as(None)

        first = client.get(f"/api/shares/{share['slug']}/download", headers=unique_ip())
        second = client.get(f"/api/shares/{share['slug']}/download", headers=unique_ip())

        assert first.status_code == 200 and first.text == PUBLIC_BODY
        assert not _object_exists(seed, share["storage_path"])
        assert second.status_code == 410

    def test_owner_burn_removes_the_object_and_leaves_a_tombstone(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, body=PUBLIC_BODY, is_private=False, content_text="public body")
        act_as(owner)

        resp = client.post(f"/api/shares/{share['slug']}/burn", json={})

        assert resp.status_code == 200, resp.text
        assert not _object_exists(seed, share["storage_path"])
        tombstone = _row(seed, share)
        assert tombstone["burned"] is True
        assert tombstone["content_text"] is None
        act_as(None)
        assert client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip()).status_code == 410


class TestDeletingABurnedShare:
    @pytest.mark.parametrize("state", [{"burned": True}, {"one_time_download": True, "download_count": 1}],
                             ids=["burned", "consumed"])
    def test_signed_in_owner_deletes_it(self, client, seed, state):
        owner = seed.user()
        share = seed.share(owner, is_private=False, **state)
        act_as(owner)

        resp = client.delete(f"/api/shares/{share['slug']}")

        assert resp.status_code == 200, resp.text
        assert _row(seed, share) is None
        assert not _object_exists(seed, share["storage_path"])

    def test_delete_token_holder_deletes_it(self, client, seed):
        share = seed.share(seed.user(), is_private=False, burned=True)
        act_as(None)

        resp = client.request("DELETE", f"/api/shares/{share['slug']}",
                              json={"delete_token": share["delete_token"]})

        assert resp.status_code == 200, resp.text
        assert _row(seed, share) is None

    def test_non_owner_still_cannot_delete_it(self, client, seed):
        share = seed.share(seed.user(), is_private=False, burned=True)
        act_as(seed.user())

        resp = client.delete(f"/api/shares/{share['slug']}")

        assert resp.status_code == 403
        assert _row(seed, share) is not None


def _revisions(seed, share: dict) -> list[dict]:
    return seed.db.table("share_revisions").select("id").eq("share_id", share["id"]).execute().data


class TestBurningRemovesDocumentRevisions:
    """A v1 document's revisions hold earlier copies of its content: they go when it burns."""

    def _with_revision(self, seed, share: dict) -> None:
        seed.db.table("share_revisions").insert(
            {"share_id": share["id"], "revision": 1, "content": "earlier secret"}
        ).execute()
        assert len(_revisions(seed, share)) == 1

    def test_owner_burn_deletes_the_revisions(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, is_private=False)
        self._with_revision(seed, share)
        act_as(owner)

        assert client.post(f"/api/shares/{share['slug']}/burn", json={}).status_code == 200

        assert _revisions(seed, share) == []

    def test_burn_after_reading_deletes_the_revisions(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False, burn_after_reading=True)
        self._with_revision(seed, share)
        act_as(None)

        assert client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip()).status_code == 200

        assert _revisions(seed, share) == []
