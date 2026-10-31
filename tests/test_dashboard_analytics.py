"""Live-DB tests: the dashboard analytics endpoints.

Runs against the real Postgres + MinIO from CI. Only authentication is overridden;
shares and share_views rows are real.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from core.db import _get_pool, _run_async
from tests.conftest import Seed, act_as, walk_keys

SECRET_KEYS = {"password_hash", "delete_token", "content", "content_text", "storage_path", "user_id"}


async def _execute(sql: str, *args):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql, *args)


def _insert_share(seed: Seed, owner, **fields) -> dict:
    """A share row with no storage object: analytics never reads content."""
    row = {
        "slug": f"an-{uuid.uuid4().hex[:12]}",
        "filename": f"{uuid.uuid4().hex[:6]}.md",
        "user_id": owner.id,
        "delete_token": f"tok-{uuid.uuid4().hex}",
    }
    row.update(fields)
    created = seed.db.table("shares").insert(row).execute().data[0]
    seed.shares.append(created["id"])
    return created


def _add_view(share: dict, *, days_ago: float = 0, source: str = "direct",
              country: str | None = None, unique: bool = True) -> None:
    viewed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    _run_async(_execute(
        "INSERT INTO share_views (share_id, viewed_at, referrer_source, country_code, is_unique) "
        "VALUES ($1, $2, $3, $4, $5)",
        uuid.UUID(share["id"]), viewed_at, source, country, unique,
    ))


def _past(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# GET /api/dashboard/analytics/top-shares
# ---------------------------------------------------------------------------

class TestTopShares:
    def test_requires_authentication(self, client):
        app.dependency_overrides.clear()

        assert client.get("/api/dashboard/analytics/top-shares").status_code == 401

    def test_ranks_the_callers_shares_by_recent_views(self, client, seed):
        me, other = seed.user(), seed.user()
        busy = _insert_share(seed, me, title="Busy")
        quiet = _insert_share(seed, me, title=None, filename="quiet.md")
        middling = _insert_share(seed, me, title="Middling")
        theirs = _insert_share(seed, other, title="Theirs")
        for _ in range(3):
            _add_view(busy)
        _add_view(busy, unique=False)
        _add_view(middling)
        _add_view(middling, days_ago=45)  # outside the 30-day ranking window
        for _ in range(9):
            _add_view(theirs)
        act_as(me)

        resp = client.get("/api/dashboard/analytics/top-shares")

        assert resp.status_code == 200
        top = resp.json()["top"]
        assert [t["slug"] for t in top] == [busy["slug"], middling["slug"], quiet["slug"]]
        assert top[0] == {
            "share_id": busy["id"],
            "slug": busy["slug"],
            "title": "Busy",
            "total_views": 4,
            "unique_views": 3,
        }
        assert (top[1]["total_views"], top[1]["unique_views"]) == (1, 1)
        assert (top[2]["title"], top[2]["total_views"], top[2]["unique_views"]) == ("quiet.md", 0, 0)
        assert not SECRET_KEYS & set(walk_keys(resp.json()))

    def test_limit_defaults_to_ten_and_caps_the_list(self, client, seed):
        me = seed.user()
        for _ in range(12):
            _insert_share(seed, me)
        act_as(me)

        assert len(client.get("/api/dashboard/analytics/top-shares").json()["top"]) == 10
        assert len(client.get("/api/dashboard/analytics/top-shares?limit=3").json()["top"]) == 3
        assert len(client.get("/api/dashboard/analytics/top-shares?limit=50").json()["top"]) == 12

    @pytest.mark.parametrize("limit", ["0", "-1", "51", "abc", ""])
    def test_limit_outside_bounds_is_rejected(self, client, seed, limit):
        act_as(seed.user())

        assert client.get(f"/api/dashboard/analytics/top-shares?limit={limit}").status_code == 422

    def test_totals_cover_every_share_not_just_the_top_n(self, client, seed):
        me, other = seed.user(), seed.user()
        _insert_share(seed, me, view_count=10, file_size=100)
        _insert_share(seed, me, view_count=5, file_size=None)
        _insert_share(seed, me, view_count=1, file_size=50, is_private=True)
        _insert_share(seed, me, view_count=2, file_size=25, expires_at=_past(3))
        _insert_share(seed, me, view_count=4, file_size=10, burned=True)
        _insert_share(seed, other, view_count=1000, file_size=1_000_000)
        act_as(me)

        body = client.get("/api/dashboard/analytics/top-shares?limit=2").json()

        assert len(body["top"]) == 2
        assert body["totals"] == {
            "share_count": 5, "total_views": 22, "total_size": 185,
            "unique_views": 0, "shares_with_views": 0,
        }

    def test_totals_count_recent_views_across_every_share(self, client, seed):
        me, other = seed.user(), seed.user()
        ranked = _insert_share(seed, me)
        expired = _insert_share(seed, me, expires_at=_past(3))
        hidden = _insert_share(seed, me, is_private=True, burned=True)
        _insert_share(seed, me)  # never viewed
        stale = _insert_share(seed, me)
        theirs = _insert_share(seed, other)
        _add_view(ranked)
        _add_view(ranked)
        _add_view(ranked, unique=False)
        _add_view(expired)
        _add_view(hidden, days_ago=3, unique=False)
        _add_view(stale, days_ago=45)  # outside the 30-day window
        for _ in range(5):
            _add_view(theirs)
        act_as(me)

        body = client.get("/api/dashboard/analytics/top-shares?limit=1").json()

        assert [t["slug"] for t in body["top"]] == [ranked["slug"]]
        assert body["totals"]["unique_views"] == 3
        assert body["totals"]["shares_with_views"] == 3

    def test_user_without_shares_gets_zero_totals_and_no_rows(self, client, seed):
        act_as(seed.user())

        resp = client.get("/api/dashboard/analytics/top-shares")

        assert resp.status_code == 200
        assert resp.json() == {
            "totals": {
                "share_count": 0, "total_views": 0, "total_size": 0,
                "unique_views": 0, "shares_with_views": 0,
            },
            "top": [],
        }


# ---------------------------------------------------------------------------
# GET /api/dashboard/shares/{slug}/analytics
# ---------------------------------------------------------------------------

class TestShareAnalytics:
    def _seeded_share(self, seed, me) -> dict:
        share = _insert_share(seed, me, title="Report", filename="report.md", is_private=True)
        _add_view(share, source="google", country="VN")
        _add_view(share, source="google", country="VN", unique=False)
        _add_view(share, source="twitter", country="US")
        _add_view(share, days_ago=3, source="direct", country=None, unique=False)
        _add_view(share, days_ago=40, source="slack", country="DE")  # outside 30 days
        return share

    def test_requires_authentication(self, client):
        app.dependency_overrides.clear()

        assert client.get("/api/dashboard/shares/anything/analytics").status_code == 401

    def test_owner_gets_summary_timeseries_referrers_and_geo(self, client, seed):
        me = seed.user()
        share = self._seeded_share(seed, me)
        act_as(me)

        resp = client.get(f"/api/dashboard/shares/{share['slug']}/analytics")

        assert resp.status_code == 200
        body = resp.json()
        assert body["share"] == {"slug": share["slug"], "title": "Report", "filename": "report.md"}
        assert body["days"] == 30
        assert body["summary"] == {
            "total_views": 4,
            "unique_views": 2,
            "views_today": 3,
            "views_7d": 4,
            "avg_daily_views": 0.1,
        }
        series = body["timeseries"]
        assert len(series) == 30
        today = datetime.now(timezone.utc).date()
        assert [p["date"] for p in series] == [
            (today - timedelta(days=back)).isoformat() for back in range(29, -1, -1)
        ]
        assert series[-1] == {"date": today.isoformat(), "views": 3, "unique_views": 2}
        assert sum(p["views"] for p in series) == 4
        assert body["referrers"] == [
            {"referrer_source": "google", "views": 2},
            {"referrer_source": "direct", "views": 1},
            {"referrer_source": "twitter", "views": 1},
        ]
        assert body["geo"] == [
            {"country_code": "VN", "views": 2},
            {"country_code": "US", "views": 1},
        ]
        assert not SECRET_KEYS & set(walk_keys(body))

    def test_days_narrows_every_section(self, client, seed):
        me = seed.user()
        share = self._seeded_share(seed, me)
        act_as(me)

        body = client.get(f"/api/dashboard/shares/{share['slug']}/analytics?days=1").json()

        assert body["days"] == 1
        assert body["summary"]["total_views"] == 3
        assert len(body["timeseries"]) == 1
        assert [r["referrer_source"] for r in body["referrers"]] == ["google", "twitter"]
        assert [g["country_code"] for g in body["geo"]] == ["VN", "US"]

    @pytest.mark.parametrize("days", ["1", "365"])
    def test_days_bounds_are_inclusive(self, client, seed, days):
        me = seed.user()
        share = _insert_share(seed, me)
        act_as(me)

        resp = client.get(f"/api/dashboard/shares/{share['slug']}/analytics?days={days}")

        assert resp.status_code == 200
        assert len(resp.json()["timeseries"]) == int(days)

    @pytest.mark.parametrize("days", ["0", "-5", "366", "abc", "1.5", ""])
    def test_days_outside_bounds_is_rejected(self, client, seed, days):
        me = seed.user()
        share = _insert_share(seed, me)
        act_as(me)

        resp = client.get(f"/api/dashboard/shares/{share['slug']}/analytics?days={days}")

        assert resp.status_code == 422

    def test_share_without_views_returns_zeros_and_empty_lists(self, client, seed):
        me = seed.user()
        share = _insert_share(seed, me, title=None, filename="empty.md")
        act_as(me)

        resp = client.get(f"/api/dashboard/shares/{share['slug']}/analytics?days=7")

        assert resp.status_code == 200
        body = resp.json()
        assert body["share"] == {"slug": share["slug"], "title": None, "filename": "empty.md"}
        assert body["summary"] == {
            "total_views": 0, "unique_views": 0, "views_today": 0, "views_7d": 0, "avg_daily_views": 0.0,
        }
        assert len(body["timeseries"]) == 7
        assert all(p["views"] == 0 and p["unique_views"] == 0 for p in body["timeseries"])
        assert body["referrers"] == []
        assert body["geo"] == []

    def test_expired_and_burned_shares_stay_visible_to_their_owner(self, client, seed):
        me = seed.user()
        expired = _insert_share(seed, me, expires_at=_past(2))
        burned = _insert_share(seed, me, burned=True)
        act_as(me)

        for share in (expired, burned):
            assert client.get(f"/api/dashboard/shares/{share['slug']}/analytics").status_code == 200

    def test_non_owner_gets_the_same_404_as_a_missing_slug(self, client, seed):
        me, stranger, teammate = seed.user(), seed.user(), seed.user()
        private = self._seeded_share(seed, me)
        public = _insert_share(seed, me, is_private=False)
        seed.team_with_share(teammate, private)

        for viewer, share in ((stranger, private), (stranger, public), (teammate, private)):
            act_as(viewer)
            missing = client.get("/api/dashboard/shares/no-such-slug-here/analytics")
            resp = client.get(f"/api/dashboard/shares/{share['slug']}/analytics")
            assert missing.status_code == 404
            assert resp.status_code == 404
            assert resp.content == missing.content

    def test_share_without_an_owner_is_not_found_for_everyone(self, client, seed):
        me = seed.user()
        share = _insert_share(seed, me)
        seed.db.table("shares").update({"user_id": None}).eq("id", share["id"]).execute()
        act_as(me)

        assert client.get(f"/api/dashboard/shares/{share['slug']}/analytics").status_code == 404

    def test_share_list_route_is_unaffected(self, client, seed):
        me = seed.user()
        share = _insert_share(seed, me)
        act_as(me)

        listing = client.get("/api/dashboard/shares")

        assert listing.status_code == 200
        assert [i["slug"] for i in listing.json()["items"]] == [share["slug"]]
