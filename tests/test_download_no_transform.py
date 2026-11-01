"""Live-DB tests: downloads ask intermediaries not to modify the bytes.

A CDN may rewrite `text/html` responses (Cloudflare injects its analytics beacon),
so a downloaded HTML file would differ from the uploaded one. `Cache-Control:
no-transform` (RFC 9111 §5.2.2.6) forbids that.
"""

from __future__ import annotations

from tests.conftest import PUBLIC_BODY, act_as, unique_ip

BROWSER = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


def _directives(resp) -> set[str]:
    return {d.strip().lower() for d in resp.headers.get("cache-control", "").split(",") if d.strip()}


def test_share_download_is_marked_no_transform(client, seed):
    share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
    act_as(None)

    resp = client.get(f"/api/shares/{share['slug']}/download", headers={**unique_ip(), **BROWSER})

    assert resp.status_code == 200, resp.text
    assert resp.content == PUBLIC_BODY.encode()
    assert "no-transform" in _directives(resp)
    assert resp.headers["content-disposition"].startswith("attachment;")


def test_group_zip_download_is_marked_no_transform(client, seed):
    owner = seed.user()
    act_as(owner)
    batch = client.post(
        "/api/upload/batch",
        files=[("files", ("a.html", PUBLIC_BODY.encode(), "text/html"))],
        headers=unique_ip(),
    ).json()
    seed.groups.append(batch["group_slug"])
    for f in batch["files"]:
        seed.adopt(f["slug"])

    resp = client.get(f"/api/download/group/{batch['group_slug']}", headers={**unique_ip(), **BROWSER})

    assert resp.status_code == 200, resp.text
    assert "no-transform" in _directives(resp)
    assert resp.headers["content-disposition"].startswith("attachment;")
