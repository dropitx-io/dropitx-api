"""Live-DB tests: the five share analytics read functions in infra/init.

One share with two views: one today (unique, from Google, in VN) and one three
days ago (a repeat, direct, no country). Expected values are worked out by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.db import _get_pool, _run_async
from core.supabase import get_admin_client


async def _execute(sql: str, *args):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql, *args)


@pytest.fixture
def seeded():
    db = get_admin_client()
    uid = f"u-{uuid.uuid4().hex[:10]}"
    db.table("auth.users").insert({"id": uid}).execute()
    share = db.table("shares").insert(
        {"slug": f"an-{uuid.uuid4().hex[:10]}", "title": "Report", "user_id": uid, "view_count": 2}
    ).execute().data[0]
    quiet = db.table("shares").insert(
        {"slug": f"an-{uuid.uuid4().hex[:10]}", "filename": "quiet.md", "user_id": uid}
    ).execute().data[0]
    _run_async(_execute(
        "INSERT INTO share_views (share_id, viewed_at, referrer, referrer_source, country_code, is_unique) "
        "VALUES ($1, now(), 'https://www.google.com/', 'google', 'VN', true), "
        "       ($1, now() - interval '3 days', NULL, 'direct', NULL, false)",
        uuid.UUID(share["id"]),
    ))
    yield uid, share, quiet
    db.table("shares").delete().in_("id", [share["id"], quiet["id"]]).execute()  # views cascade
    db.table("auth.users").delete().eq("id", uid).execute()


def _rpc(name: str, params: dict) -> list[dict]:
    return get_admin_client().rpc(name, params).execute().data


def test_share_analytics_summary(seeded):
    _, share, _ = seeded

    assert _rpc("get_share_analytics", {"p_share_id": share["id"], "p_days": 30}) == [{
        "total_views": 2,
        "unique_views": 1,
        "views_today": 1,
        "views_7d": 2,
        "avg_daily_views": 0.1,
    }]


def test_share_analytics_window_excludes_older_views(seeded):
    _, share, _ = seeded

    (row,) = _rpc("get_share_analytics", {"p_share_id": share["id"], "p_days": 1})

    assert (row["total_views"], row["unique_views"], row["avg_daily_views"]) == (1, 1, 1.0)


def test_share_view_timeseries_has_one_row_per_day_including_empty_days(seeded):
    _, share, _ = seeded
    today = datetime.now(timezone.utc).date()

    rows = _rpc("get_share_view_timeseries", {"p_share_id": share["id"], "p_days": 7})

    expected = []
    for back in range(6, -1, -1):
        day = (today - timedelta(days=back)).isoformat()
        views, unique = {0: (1, 1), 3: (1, 0)}.get(back, (0, 0))
        expected.append({"date": day, "views": views, "unique_views": unique})
    assert rows == expected


def test_share_referrers(seeded):
    _, share, _ = seeded

    assert _rpc("get_share_referrers", {"p_share_id": share["id"], "p_days": 30, "p_limit": 10}) == [
        {"referrer_source": "direct", "views": 1},
        {"referrer_source": "google", "views": 1},
    ]


def test_share_geo_counts_only_known_countries(seeded):
    _, share, _ = seeded

    assert _rpc("get_share_geo", {"p_share_id": share["id"], "p_days": 30, "p_limit": 10}) == [
        {"country_code": "VN", "views": 1},
    ]


def test_user_top_shares_ranks_by_views_and_includes_unviewed(seeded):
    uid, share, quiet = seeded

    assert _rpc("get_user_top_shares", {"p_user_id": uid, "p_limit": 10}) == [
        {"share_id": share["id"], "slug": share["slug"], "title": "Report", "total_views": 2, "unique_views": 1},
        {"share_id": quiet["id"], "slug": quiet["slug"], "title": "quiet.md", "total_views": 0, "unique_views": 0},
    ]
    assert len(_rpc("get_user_top_shares", {"p_user_id": uid, "p_limit": 1})) == 1


def test_functions_return_nothing_or_zeros_for_a_share_without_views(seeded):
    _, _, quiet = seeded
    sid = quiet["id"]

    assert _rpc("get_share_analytics", {"p_share_id": sid, "p_days": 30}) == [{
        "total_views": 0, "unique_views": 0, "views_today": 0, "views_7d": 0, "avg_daily_views": 0.0,
    }]
    assert _rpc("get_share_referrers", {"p_share_id": sid, "p_days": 30, "p_limit": 10}) == []
    assert _rpc("get_share_geo", {"p_share_id": sid, "p_days": 30, "p_limit": 10}) == []
    assert all(r["views"] == 0 for r in _rpc("get_share_view_timeseries", {"p_share_id": sid, "p_days": 3}))


# ---------------------------------------------------------------------------
# One window for every read function, in UTC, whatever the session timezone
# ---------------------------------------------------------------------------

def _utc_midnight() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _view_at(share: dict, viewed_at: datetime, *, unique: bool = True) -> None:
    _run_async(_execute(
        "INSERT INTO share_views (share_id, viewed_at, referrer_source, country_code, is_unique) "
        "VALUES ($1, $2, 'direct', 'VN', $3)",
        uuid.UUID(share["id"]), viewed_at, unique,
    ))


def test_summary_total_matches_timeseries_sum_for_the_same_window(seeded):
    _, share, _ = seeded
    # Just before the first calendar day of a 7-day window: inside "now() - 7 days"
    # but outside the seven days the timeseries lists.
    _view_at(share, _utc_midnight() - timedelta(days=6, minutes=1))
    params = {"p_share_id": share["id"], "p_days": 7}

    (summary,) = _rpc("get_share_analytics", params)
    series = _rpc("get_share_view_timeseries", params)

    assert summary["total_views"] == sum(day["views"] for day in series) == 2
    assert summary["unique_views"] == sum(day["unique_views"] for day in series) == 1
    assert sum(r["views"] for r in _rpc("get_share_referrers", {**params, "p_limit": 10})) == 2
    assert sum(r["views"] for r in _rpc("get_share_geo", {**params, "p_limit": 10})) == 1


def test_views_in_the_last_seven_days_ignore_a_shorter_window(seeded):
    _, share, _ = seeded

    (row,) = _rpc("get_share_analytics", {"p_share_id": share["id"], "p_days": 1})

    assert row["total_views"] == 1
    assert row["views_7d"] == 2


async def _in_timezone(timezone_name: str, sql: str, *args) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL timezone = '{timezone_name}'")
            return [dict(r) for r in await conn.fetch(sql, *args)]


@pytest.mark.parametrize("session_timezone", ["Pacific/Kiritimati", "Etc/GMT+12"])
def test_read_functions_give_the_same_answer_in_any_session_timezone(seeded, session_timezone):
    _, share, _ = seeded
    _view_at(share, _utc_midnight() - timedelta(minutes=1))
    sid = uuid.UUID(share["id"])
    calls = {
        "get_share_analytics": ("SELECT * FROM get_share_analytics($1, 7)", (sid,)),
        "get_share_view_timeseries": ("SELECT * FROM get_share_view_timeseries($1, 7)", (sid,)),
        "get_share_referrers": ("SELECT * FROM get_share_referrers($1, 7, 10)", (sid,)),
        "get_share_geo": ("SELECT * FROM get_share_geo($1, 7, 10)", (sid,)),
    }

    for name, (sql, args) in calls.items():
        in_utc = _run_async(_in_timezone("UTC", sql, *args))
        elsewhere = _run_async(_in_timezone(session_timezone, sql, *args))
        assert elsewhere == in_utc, name
