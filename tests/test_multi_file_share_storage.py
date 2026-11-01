"""Live-DB tests: a multi-file share's files leave storage with the share.

`POST /api/upload/multi` stores each file under `shares/<slug>/` and records it in
`share_files`; the share row points at the first file only.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from tests.conftest import act_as, unique_ip


def _object_exists(seed, path: str) -> bool:
    try:
        seed.db.storage.from_("html-files").download(path)
    except Exception:
        return False
    return True


def _multi_share(client, seed, owner) -> tuple[dict, list[str]]:
    act_as(owner)
    resp = client.post(
        "/api/upload/multi",
        files=[
            ("files", ("one.md", b"# one", "text/markdown")),
            ("files", ("two.md", b"# two", "text/markdown")),
            ("files", ("three.html", b"<p>three</p>", "text/html")),
        ],
        headers=unique_ip(),
    )
    assert resp.status_code == 200, resp.text
    paths = [f["storage_path"] for f in resp.json()["files"]]
    row = seed.adopt(resp.json()["slug"])
    seed.objects.extend(paths)
    assert all(_object_exists(seed, p) for p in paths)
    return row, paths


def test_deleting_a_multi_file_share_removes_every_file(client, seed):
    owner = seed.user()
    share, paths = _multi_share(client, seed, owner)

    assert client.delete(f"/api/shares/{share['slug']}").status_code == 200

    assert [p for p in paths if _object_exists(seed, p)] == []


def test_burning_a_multi_file_share_removes_every_file(client, seed):
    owner = seed.user()
    share, paths = _multi_share(client, seed, owner)

    assert client.post(f"/api/shares/{share['slug']}/burn", json={}).status_code == 200

    assert [p for p in paths if _object_exists(seed, p)] == []
    files = seed.db.table("share_files").select("id").eq("share_id", share["id"]).execute().data
    assert files == []


def test_expired_multi_file_share_cleanup_removes_every_file(client, seed):
    from app.services.cleanup import cleanup_expired_shares

    owner = seed.user()
    share, paths = _multi_share(client, seed, owner)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    seed.db.table("shares").update({"expires_at": past}).eq("id", share["id"]).execute()

    assert asyncio.run(cleanup_expired_shares()) >= 1

    assert [p for p in paths if _object_exists(seed, p)] == []
