"""Live-DB tests: restoring a published share's version brings back that version's content.

Runs against the real Postgres + MinIO from CI. Only authentication is
overridden; share rows, version rows and storage objects are real.
"""

from __future__ import annotations

from tests.conftest import act_as, unique_ip


def _publish(client, seed, content: str) -> str:
    resp = client.post("/api/publish", json={"content": content}, headers=unique_ip())
    assert resp.status_code == 200, resp.text
    slug = resp.json()["slug"]
    seed.adopt(slug)
    return slug


def _track_version_objects(seed, slug: str) -> list[dict]:
    rows = seed.db.table("share_versions").select("*").eq("share_slug", slug).execute().data
    seed.objects.extend(r["storage_path"] for r in rows if r.get("storage_path"))
    return rows


def _content(client, slug: str) -> str:
    resp = client.get(f"/api/shares/{slug}/content", headers=unique_ip())
    assert resp.status_code == 200, resp.text
    return resp.json()["content"]


class TestRestoreVersion:
    def test_restoring_version_one_serves_its_content_again(self, client, seed):
        act_as(seed.user())
        slug = _publish(client, seed, "<p>VERSION-ONE</p>")
        update = client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-TWO</p>"}, headers=unique_ip())
        assert update.status_code == 200, update.text

        resp = client.post(f"/api/shares/{slug}/versions/1/restore")

        versions = _track_version_objects(seed, slug)
        assert resp.status_code == 200, resp.text
        assert _content(client, slug) == "<p>VERSION-ONE</p>"
        assert len(versions) == 2

    def test_restore_first_saves_the_current_content_as_a_version(self, client, seed):
        act_as(seed.user())
        slug = _publish(client, seed, "<p>VERSION-ONE</p>")
        client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-TWO</p>"}, headers=unique_ip())
        assert client.post(f"/api/shares/{slug}/versions/1/restore").status_code == 200

        resp = client.post(f"/api/shares/{slug}/versions/2/restore")

        _track_version_objects(seed, slug)
        assert resp.status_code == 200, resp.text
        assert _content(client, slug) == "<p>VERSION-TWO</p>"

    def test_a_version_keeps_its_content_after_later_updates(self, client, seed):
        act_as(seed.user())
        slug = _publish(client, seed, "<p>VERSION-ONE</p>")
        client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-TWO</p>"}, headers=unique_ip())
        client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-THREE</p>"}, headers=unique_ip())

        versions = {v["version_num"]: v for v in _track_version_objects(seed, slug)}
        live_path = seed.db.table("shares").select("storage_path").eq("slug", slug).execute().data[0]["storage_path"]

        assert versions[1]["storage_path"] != live_path
        assert seed.db.storage.from_("html-files").download(versions[1]["storage_path"]) == b"<p>VERSION-ONE</p>"
        assert seed.db.storage.from_("html-files").download(versions[2]["storage_path"]) == b"<p>VERSION-TWO</p>"

    def test_a_version_without_its_own_snapshot_is_refused_and_changes_nothing(self, client, seed):
        owner = seed.user()
        share = seed.share(owner, body="<p>CURRENT</p>", is_private=False, source="editor")
        seed.db.table("share_versions").insert({
            "share_slug": share["slug"],
            "content_text": "OLD",
            "storage_path": share["storage_path"],
            "version_num": 1,
        }).execute()
        act_as(owner)

        resp = client.post(f"/api/shares/{share['slug']}/versions/1/restore")

        assert resp.status_code == 409, resp.text
        assert _content(client, share["slug"]) == "<p>CURRENT</p>"
        assert len(_track_version_objects(seed, share["slug"])) == 1


class TestVersionSnapshotsFollowTheShare:
    def _published_with_two_versions(self, client, seed) -> tuple[str, list[str]]:
        act_as(seed.user())
        slug = _publish(client, seed, "<p>VERSION-ONE</p>")
        client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-TWO</p>"}, headers=unique_ip())
        client.put(f"/api/publish/{slug}", json={"content": "<p>VERSION-THREE</p>"}, headers=unique_ip())
        paths = [v["storage_path"] for v in _track_version_objects(seed, slug)]
        assert len(paths) == 2
        return slug, paths

    def _exists(self, seed, path: str) -> bool:
        try:
            seed.db.storage.from_("html-files").download(path)
        except Exception:
            return False
        return True

    def test_burning_removes_the_version_snapshots(self, client, seed):
        slug, paths = self._published_with_two_versions(client, seed)

        assert client.post(f"/api/shares/{slug}/burn", json={}).status_code == 200

        assert not any(self._exists(seed, p) for p in paths)
        assert seed.db.table("share_versions").select("id").eq("share_slug", slug).execute().data == []

    def test_deleting_removes_the_version_snapshots(self, client, seed):
        slug, paths = self._published_with_two_versions(client, seed)

        assert client.delete(f"/api/shares/{slug}").status_code == 200

        assert not any(self._exists(seed, p) for p in paths)
