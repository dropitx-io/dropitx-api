"""Live-DB tests: ISO-8601 strings bound to timestamp/date columns reach Postgres.

The shim must convert string parameters by the prepared statement's declared
parameter types, so callers can keep sending `datetime.isoformat()` strings.
Runs against the real Postgres + MinIO from CI.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import ApiKeyAuth, User, get_api_key, get_current_user, get_optional_user
from app.main import app
from core.db import _get_pool, _run_async
from core.supabase import get_admin_client

UTC = timezone.utc
INSTANT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)

# Every spelling below denotes the same instant.
SAME_INSTANT = {
    "z-suffix": "2030-01-02T03:04:05Z",
    "offset": "2030-01-02T10:04:05+07:00",
    "naive-is-utc": "2030-01-02T03:04:05",
    "aware-datetime": INSTANT,
    "offset-datetime": datetime(2030, 1, 2, 10, 4, 5, tzinfo=timezone(timedelta(hours=7))),
}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.fixture
def scratch():
    name = f"shim_ts_{uuid.uuid4().hex[:10]}"

    async def ddl(sql: str):
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)

    _run_async(ddl(
        f"CREATE TABLE {name} (id serial PRIMARY KEY, tz timestamptz, ts timestamp, "
        f"d date, note text)"
    ))
    yield name
    _run_async(ddl(f"DROP TABLE {name}"))


class TestShimTimestampParams:
    @pytest.mark.parametrize("value", SAME_INSTANT.values(), ids=SAME_INSTANT.keys())
    def test_insert_into_timestamptz(self, scratch, value):
        row = get_admin_client().table(scratch).insert({"tz": value}).execute().data[0]

        assert _parse(row["tz"]) == INSTANT

    @pytest.mark.parametrize("value", SAME_INSTANT.values(), ids=SAME_INSTANT.keys())
    def test_update_timestamptz(self, scratch, value):
        db = get_admin_client()
        created = db.table(scratch).insert({"tz": None}).execute().data[0]

        updated = db.table(scratch).update({"tz": value}).eq("id", created["id"]).execute().data[0]

        assert _parse(updated["tz"]) == INSTANT

    @pytest.mark.parametrize("value", SAME_INSTANT.values(), ids=SAME_INSTANT.keys())
    def test_lt_and_gt_filters_on_timestamptz(self, scratch, value):
        db = get_admin_client()
        row = db.table(scratch).insert({"tz": INSTANT}).execute().data[0]
        one_hour = timedelta(hours=1)

        def as_bound(delta):
            if isinstance(value, datetime):
                return value + delta
            return (_parse(value.replace("Z", "+00:00")) + delta).isoformat()

        later = db.table(scratch).select("id").eq("id", row["id"]).lt("tz", as_bound(one_hour)).execute().data
        earlier = db.table(scratch).select("id").eq("id", row["id"]).gt("tz", as_bound(-one_hour)).execute().data
        not_later = db.table(scratch).select("id").eq("id", row["id"]).gt("tz", as_bound(one_hour)).execute().data

        assert [r["id"] for r in later] == [row["id"]]
        assert [r["id"] for r in earlier] == [row["id"]]
        assert not_later == []

    def test_filter_accepts_z_and_offset_strings(self, scratch):
        db = get_admin_client()
        row = db.table(scratch).insert({"tz": INSTANT}).execute().data[0]

        z = db.table(scratch).select("id").eq("id", row["id"]).lt("tz", "2030-01-02T04:04:05Z").execute().data
        off = db.table(scratch).select("id").eq("id", row["id"]).gt("tz", "2030-01-02T09:04:05+07:00").execute().data

        assert len(z) == 1
        assert len(off) == 1

    def test_exact_count_with_timestamp_filter(self, scratch):
        db = get_admin_client()
        db.table(scratch).insert({"tz": INSTANT}).execute()

        resp = db.table(scratch).select("id", count="exact").lt("tz", "2030-01-02T04:04:05Z").execute()

        assert resp.count == 1

    def test_naive_string_is_read_as_utc_regardless_of_process_timezone(self, scratch, monkeypatch):
        import time

        monkeypatch.setenv("TZ", "Asia/Saigon")
        time.tzset()
        try:
            row = get_admin_client().table(scratch).insert({"tz": "2030-01-02T03:04:05"}).execute().data[0]
        finally:
            monkeypatch.undo()
            time.tzset()

        assert _parse(row["tz"]) == INSTANT

    def test_timestamp_without_time_zone_stores_utc_wall_clock(self, scratch):
        db = get_admin_client()

        from_offset = db.table(scratch).insert({"ts": "2030-01-02T10:04:05+07:00"}).execute().data[0]
        from_z = db.table(scratch).insert({"ts": "2030-01-02T03:04:05Z"}).execute().data[0]

        assert _parse(from_offset["ts"]) == datetime(2030, 1, 2, 3, 4, 5)
        assert _parse(from_z["ts"]) == datetime(2030, 1, 2, 3, 4, 5)

    def test_date_column_accepts_iso_string(self, scratch):
        row = get_admin_client().table(scratch).insert({"d": "2030-01-02"}).execute().data[0]

        assert date.fromisoformat(row["d"]) == date(2030, 1, 2)

    def test_text_column_keeps_iso_looking_strings_verbatim(self, scratch):
        iso = "2030-01-02T03:04:05Z"

        row = get_admin_client().table(scratch).insert({"note": iso}).execute().data[0]

        assert row["note"] == iso

    def test_null_timestamp_passes_through(self, scratch):
        row = get_admin_client().table(scratch).insert({"tz": None}).execute().data[0]

        assert row["tz"] is None


class TestStatementCache:
    """Declared param types are memoized per SQL so asyncpg's statement cache applies."""

    @pytest.fixture
    def prepares(self, monkeypatch):
        import asyncpg

        calls: list[str] = []
        real_prepare = asyncpg.Connection.prepare

        async def spy(conn, query, *args, **kwargs):
            calls.append(query)
            return await real_prepare(conn, query, *args, **kwargs)

        monkeypatch.setattr(asyncpg.Connection, "prepare", spy)
        return calls

    def test_repeating_a_query_with_a_str_timestamp_prepares_at_most_once(self, scratch, prepares):
        db = get_admin_client()
        db.table(scratch).insert({"tz": INSTANT}).execute()

        db.table(scratch).select("id").lt("tz", "2030-01-02T04:04:05Z").execute()
        after_first = len(prepares)
        rows = db.table(scratch).select("id").lt("tz", "2031-01-02T04:04:05Z").execute().data

        assert len(rows) == 1
        assert len(prepares) == after_first

    def test_query_without_str_params_never_prepares(self, scratch, prepares):
        db = get_admin_client()

        db.table(scratch).insert({"tz": INSTANT}).execute()
        db.table(scratch).select("id").eq("id", 1).execute()
        db.table(scratch).update({"tz": INSTANT}).eq("id", 1).execute()
        db.table(scratch).delete().eq("id", 1).execute()

        assert prepares == []


# ---------------------------------------------------------------------------
# Endpoints that write ISO strings into shares.expires_at
# ---------------------------------------------------------------------------

def _unique_ip() -> dict:
    return {"cf-connecting-ip": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def created():
    """Shares and users created through the API by one test, removed on teardown."""
    db = get_admin_client()
    bag = {"slugs": [], "users": []}
    yield bag
    for slug in bag["slugs"]:
        rows = db.table("shares").select("id, storage_path").eq("slug", slug).execute().data
        for row in rows:
            db.table("shares").delete().eq("id", row["id"]).execute()
            if row.get("storage_path"):
                db.storage.from_("html-files").remove([row["storage_path"]])
    for uid in bag["users"]:
        db.table("auth.users").delete().eq("id", uid).execute()


def _expires_at_of(slug: str) -> datetime:
    row = get_admin_client().table("shares").select("expires_at").eq("slug", slug).execute().data[0]
    assert row["expires_at"] is not None
    return _parse(row["expires_at"])


def _assert_about_an_hour_from_now(expires_at: datetime) -> None:
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(minutes=58) < remaining < timedelta(minutes=62)


class TestEndpointsStoreExpiry:
    def test_cli_file_upload_with_expires_stores_expires_at(self, client, created):
        app.dependency_overrides[get_optional_user] = lambda: None

        resp = client.post(
            "/api/cli/upload",
            files={"file": ("note.md", b"# cli", "text/markdown")},
            data={"expires": "1h"},
            headers=_unique_ip(),
        )

        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        created["slugs"].append(slug)
        _assert_about_an_hour_from_now(_expires_at_of(slug))

    def test_cli_text_upload_succeeds(self, client, created):
        app.dependency_overrides[get_optional_user] = lambda: None

        resp = client.post(
            "/api/cli/upload/text",
            data={"content": "plain cli text"},
            headers=_unique_ip(),
        )

        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        created["slugs"].append(slug)
        assert _expires_at_of(slug) > datetime.now(UTC)

    def test_web_upload_with_expiry_succeeds(self, client, created):
        app.dependency_overrides[get_optional_user] = lambda: None

        resp = client.post(
            "/api/upload",
            files={"file": ("note.md", b"# web", "text/markdown")},
            data={"expires_in": "1h"},
            headers=_unique_ip(),
        )

        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        created["slugs"].append(slug)
        _assert_about_an_hour_from_now(_expires_at_of(slug))

    def test_v1_document_create_with_expires_in_succeeds(self, client, created):
        uid = f"ts-{uuid.uuid4().hex}"
        get_admin_client().table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
        created["users"].append(uid)
        app.dependency_overrides[get_api_key] = lambda: ApiKeyAuth(user_id=uid, key_id="k")

        resp = client.post(
            "/api/v1/documents",
            json={"content": "# doc", "filename": "doc.md", "expires_in": 3600},
        )

        assert resp.status_code == 201, resp.text
        slug = resp.json()["slug"]
        created["slugs"].append(slug)
        _assert_about_an_hour_from_now(_expires_at_of(slug))
