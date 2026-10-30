"""Live-DB tests: POST /api/analytics/track records one share_views row per view.

Runs against the real Postgres from CI; no dependency is overridden.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.supabase import get_admin_client

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_share():
    db = get_admin_client()
    ids: list[str] = []

    def make(**fields) -> dict:
        row = {"slug": f"trk-{uuid.uuid4().hex[:10]}", "view_count": 5, **fields}
        created = db.table("shares").insert(row).execute().data[0]
        ids.append(created["id"])
        return created

    yield make
    for share_id in ids:
        db.table("shares").delete().eq("id", share_id).execute()


def _ip() -> str:
    """A fresh client IP per test, so rate-limit buckets never collide."""
    n = uuid.uuid4().int
    return f"10.{n % 256}.{(n >> 8) % 256}.{(n >> 16) % 256}"


def _views(share_id: str) -> list[dict]:
    return get_admin_client().table("share_views").select("*").eq("share_id", share_id).order("id").execute().data


def _view_count(share_id: str) -> int:
    return get_admin_client().table("shares").select("view_count").eq("id", share_id).execute().data[0]["view_count"]


def _track(client, slug, ip, ua=MAC, country=None, **body):
    headers = {"cf-connecting-ip": ip, "user-agent": ua}
    if country:
        headers["cf-ipcountry"] = country
    return client.post("/api/analytics/track", json={"slug": slug, **body}, headers=headers)


def test_track_inserts_one_row_and_leaves_view_count_alone(client, make_share):
    share = make_share()

    resp = _track(client, share["slug"], _ip(), ua=IPHONE, country="VN",
                  referrer="https://www.google.com/search?q=dropitx")

    assert resp.status_code == 204
    views = _views(share["id"])
    assert len(views) == 1
    view = views[0]
    assert view["referrer"] == "https://www.google.com/search?q=dropitx"
    assert view["referrer_source"] == "google"
    assert view["country_code"] == "VN"
    assert view["user_agent_class"] == "mobile"
    assert view["is_unique"] is True
    assert view["viewed_at"]
    assert _view_count(share["id"]) == 5


def test_repeat_view_by_same_visitor_within_the_hour_is_not_unique(client, make_share):
    share = make_share()
    ip = _ip()

    _track(client, share["slug"], ip)
    _track(client, share["slug"], ip)
    _track(client, share["slug"], ip, ua=IPHONE)

    assert [v["is_unique"] for v in _views(share["id"])] == [True, False, True]


def test_referrer_classification(client, make_share):
    share = make_share()
    ip = _ip()

    _track(client, share["slug"], ip)
    _track(client, share["slug"], ip, referrer="https://x.com/someone/status/1")
    _track(client, share["slug"], ip, referrer="https://example.org/blog", is_embed=True)
    _track(client, share["slug"], ip, referrer="https://example.org/blog")
    _track(client, share["slug"], ip, referrer="not a url")

    sources = [v["referrer_source"] for v in _views(share["id"])]
    assert sources == ["direct", "twitter", "embed", "other", "direct"]


def test_bot_user_agent_and_unknown_country_code(client, make_share):
    share = make_share()

    _track(client, share["slug"], _ip(), ua="Mozilla/5.0 (compatible; Googlebot/2.1)", country="XX")

    (view,) = _views(share["id"])
    assert view["user_agent_class"] == "bot"
    assert view["country_code"] is None


def test_private_and_unknown_shares_record_nothing_and_answer_alike(client, make_share):
    private = make_share(is_private=True)

    private_resp = _track(client, private["slug"], _ip())
    missing_resp = _track(client, f"nope-{uuid.uuid4().hex[:8]}", _ip())

    assert private_resp.status_code == missing_resp.status_code == 204
    assert private_resp.content == missing_resp.content == b""
    assert _views(private["id"]) == []


@pytest.fixture
def stored_share(make_share):
    """A public share whose content object exists, so /content can answer 200."""
    slug = f"trk-{uuid.uuid4().hex[:10]}"
    path = f"test-analytics/{slug}.html"
    bucket = get_admin_client().storage.from_("html-files")
    bucket.upload(path, b"<p>hello</p>", file_options={"content-type": "text/html"})
    yield make_share(slug=slug, storage_path=path, source="upload")
    bucket.remove([path])


def _content(client, slug, ip):
    return client.get(f"/api/shares/{slug}/content", headers={"cf-connecting-ip": ip})


def test_track_answers_429_once_its_own_bucket_is_spent(client, make_share):
    share = make_share()
    ip = _ip()

    statuses = [_track(client, share["slug"], ip).status_code for _ in range(61)]

    assert statuses == [204] * 60 + [429]
    assert len(_views(share["id"])) == 60


def test_spent_track_bucket_leaves_content_reads_open(client, stored_share):
    ip = _ip()
    for _ in range(61):
        _track(client, stored_share["slug"], ip)

    resp = _content(client, stored_share["slug"], ip)

    assert resp.status_code == 200
    assert resp.json()["content"] == "<p>hello</p>"


def test_spent_read_bucket_leaves_track_open(client, stored_share):
    ip = _ip()
    reads = [_content(client, stored_share["slug"], ip).status_code for _ in range(61)]

    resp = _track(client, stored_share["slug"], ip)

    assert reads[-1] == 429
    assert resp.status_code == 204
    assert len(_views(stored_share["id"])) == 1


def test_slug_is_required(client):
    resp = client.post("/api/analytics/track", json={"referrer": "https://example.org"})

    assert resp.status_code == 422
    assert any(err["loc"][-1] == "slug" for err in resp.json()["detail"])
