"""Live-DB tests: list inserts and the `.not_` filter operator of the DB shim.

Runs against the real Postgres + MinIO from CI.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import User, get_current_user, get_optional_user
from app.main import app
from app.services.cleanup import cleanup_expired_file_requests
from core.db import _get_pool, _run_async
from core.supabase import get_admin_client

UTC = timezone.utc
INSTANT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def scratch():
    name = f"shim_multi_{uuid.uuid4().hex[:10]}"

    async def ddl(sql: str):
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)

    _run_async(ddl(
        f"CREATE TABLE {name} (id serial PRIMARY KEY, a text, b integer, "
        f"c text DEFAULT 'dflt', tz timestamptz)"
    ))
    yield name
    _run_async(ddl(f"DROP TABLE {name}"))


class TestListInsert:
    def test_three_rows_with_differing_keys_return_three_rows(self, scratch):
        rows = get_admin_client().table(scratch).insert([
            {"a": "one", "b": 1},
            {"b": 2, "c": "custom"},
            {"a": "three", "c": None},
        ]).execute().data

        assert [(r["a"], r["b"], r["c"]) for r in rows] == [
            ("one", 1, "dflt"),
            (None, 2, "custom"),
            ("three", None, None),
        ]

    def test_rows_come_back_in_input_order_and_are_stored(self, scratch):
        db = get_admin_client()

        returned = db.table(scratch).insert([{"a": "x"}, {"a": "y"}, {"a": "z"}]).execute().data
        stored = db.table(scratch).select("*").order("id").execute().data

        assert [r["a"] for r in returned] == ["x", "y", "z"]
        assert [r["a"] for r in stored] == ["x", "y", "z"]

    def test_missing_key_takes_column_default_but_explicit_none_is_null(self, scratch):
        rows = get_admin_client().table(scratch).insert([
            {"a": "has-default"},
            {"a": "explicit-null", "c": None},
        ]).execute().data

        assert rows[0]["c"] == "dflt"
        assert rows[1]["c"] is None

    def test_columns_are_first_seen_order_then_new_keys_in_row_order(self, scratch, monkeypatch):
        import asyncpg

        statements: list[str] = []
        real_fetch = asyncpg.Connection.fetch

        async def spy(conn, query, *args, **kwargs):
            statements.append(query)
            return await real_fetch(conn, query, *args, **kwargs)

        monkeypatch.setattr(asyncpg.Connection, "fetch", spy)

        get_admin_client().table(scratch).insert([
            {"b": 1, "a": "x"},
            {"c": "y", "a": "z"},
            {"tz": INSTANT},
        ]).execute()

        assert statements[-1].startswith(f"INSERT INTO {scratch} (b, a, c, tz) VALUES ")

    def test_iso_timestamp_strings_are_stored_for_every_row(self, scratch):
        rows = get_admin_client().table(scratch).insert([
            {"tz": "2030-01-02T03:04:05Z"},
            {"tz": "2030-01-02T10:04:05+07:00"},
            {"tz": "2030-01-02T03:04:05"},
            {"a": "no-timestamp"},
        ]).execute().data

        assert [datetime.fromisoformat(r["tz"]) for r in rows[:3]] == [INSTANT] * 3
        assert rows[3]["tz"] is None

    def test_empty_list_runs_no_query_and_returns_no_rows(self, scratch, monkeypatch):
        import asyncpg

        calls: list[str] = []
        real_fetch = asyncpg.Connection.fetch

        async def spy(conn, query, *args, **kwargs):
            calls.append(query)
            return await real_fetch(conn, query, *args, **kwargs)

        monkeypatch.setattr(asyncpg.Connection, "fetch", spy)

        resp = get_admin_client().table(scratch).insert([]).execute()

        assert resp.data == []
        assert calls == []

    def test_single_row_dict_insert_is_unchanged(self, scratch):
        row = get_admin_client().table(scratch).insert({"a": "solo"}).execute().data[0]

        assert (row["a"], row["b"], row["c"]) == ("solo", None, "dflt")


class TestNotOperator:
    @pytest.fixture
    def seeded(self, scratch):
        db = get_admin_client()
        db.table(scratch).insert([
            {"a": "x", "b": 1},
            {"a": "y", "b": 2},
            {"a": None, "b": 3},
        ]).execute()
        return db, scratch

    @staticmethod
    def _bs(resp) -> list[int]:
        return sorted(r["b"] for r in resp.data)

    def test_not_is_null_returns_rows_with_a_value(self, seeded):
        db, table = seeded

        assert self._bs(db.table(table).select("*").not_.is_("a", None).execute()) == [1, 2]

    def test_not_is_accepts_the_null_string_spelling(self, seeded):
        db, table = seeded

        assert self._bs(db.table(table).select("*").not_.is_("a", "null").execute()) == [1, 2]

    def test_not_eq_excludes_the_match_and_null_rows(self, seeded):
        db, table = seeded

        # NOT (a = 'x'): a NULL comparison is unknown, so the NULL row is not returned.
        assert self._bs(db.table(table).select("*").not_.eq("a", "x").execute()) == [2]

    def test_not_in_and_not_like(self, seeded):
        db, table = seeded

        assert self._bs(db.table(table).select("*").not_.in_("b", [1, 2]).execute()) == [3]
        assert self._bs(db.table(table).select("*").not_.like("a", "x%").execute()) == [2]

    def test_not_combines_with_other_filters_and_param_numbering_holds(self, seeded):
        db, table = seeded

        resp = (
            db.table(table).select("*")
            .gt("b", 0)
            .not_.eq("a", "x")
            .lt("b", 3)
            .execute()
        )

        assert self._bs(resp) == [2]

    def test_not_applies_to_only_the_next_filter(self, seeded):
        db, table = seeded

        resp = db.table(table).select("*").not_.eq("a", "x").eq("b", 2).execute()
        assert self._bs(resp) == [2]
        resp = db.table(table).select("*").not_.eq("b", 2).eq("a", "x").execute()
        assert self._bs(resp) == [1]

    def test_not_works_on_update_and_delete(self, seeded):
        db, table = seeded

        updated = db.table(table).update({"c": "changed"}).not_.is_("a", None).execute().data
        deleted = db.table(table).delete().not_.eq("b", 3).execute().data

        assert sorted(r["b"] for r in updated) == [1, 2]
        assert sorted(r["b"] for r in deleted) == [1, 2]

    def test_not_rejects_non_filter_methods(self, seeded):
        db, table = seeded

        with pytest.raises(AttributeError, match="can only negate filters"):
            db.table(table).select("*").not_.order("b")

    def test_not_with_a_timestamp_string_parameter(self, scratch):
        db = get_admin_client()
        db.table(scratch).insert([{"b": 1, "tz": INSTANT}, {"b": 2, "tz": INSTANT + timedelta(days=1)}]).execute()

        resp = db.table(scratch).select("*").not_.lt("tz", "2030-01-02T12:00:00Z").execute()

        assert self._bs(resp) == [2]


# ---------------------------------------------------------------------------
# cleanup_expired_file_requests (uses .not_.is_)
# ---------------------------------------------------------------------------

class TestExpiredFileRequestCleanup:
    @pytest.fixture
    def seeded(self):
        db = get_admin_client()
        bag = {"users": [], "requests": [], "objects": []}
        uid = f"fr-{uuid.uuid4().hex}"
        db.table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
        bag["users"].append(uid)
        bag["uid"] = uid
        yield bag
        for rid in bag["requests"]:
            db.table("file_requests").delete().eq("id", rid).execute()
        if bag["objects"]:
            db.storage.from_("html-files").remove(bag["objects"])
        for u in bag["users"]:
            db.table("auth.users").delete().eq("id", u).execute()

    def _request_with_upload(self, bag, *, expires_at: str) -> tuple[dict, dict]:
        db = get_admin_client()
        request = db.table("file_requests").insert({
            "slug": f"fr-{uuid.uuid4().hex[:12]}",
            "user_id": bag["uid"],
            "expires_at": expires_at,
        }).execute().data[0]
        bag["requests"].append(request["id"])
        path = f"requests/{request['id']}/file.html"
        db.storage.from_("html-files").upload(path, b"<p>x</p>", file_options={"content-type": "text/html"})
        bag["objects"].append(path)
        upload = db.table("file_request_uploads").insert({
            "file_request_id": request["id"],
            "storage_path": path,
            "filename": "file.html",
            "mime_type": "text/html",
            "file_size": 8,
        }).execute().data[0]
        return request, upload

    def test_expired_upload_is_deleted_and_live_one_is_kept(self, seeded):
        db = get_admin_client()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expired_req, expired_upload = self._request_with_upload(seeded, expires_at=past)
        live_req, live_upload = self._request_with_upload(seeded, expires_at=future)

        done = asyncio.run(cleanup_expired_file_requests())

        assert done >= 1
        assert db.table("file_request_uploads").select("id").eq("id", expired_upload["id"]).execute().data == []
        assert len(db.table("file_request_uploads").select("id").eq("id", live_upload["id"]).execute().data) == 1
        with pytest.raises(Exception):
            db.storage.from_("html-files").download(expired_upload["storage_path"])
        assert db.storage.from_("html-files").download(live_upload["storage_path"]) == b"<p>x</p>"

    def test_expired_request_is_deactivated_and_kept_for_history(self, seeded):
        db = get_admin_client()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        expired_req, _ = self._request_with_upload(seeded, expires_at=past)
        live_req, _ = self._request_with_upload(
            seeded, expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat()
        )

        asyncio.run(cleanup_expired_file_requests())

        expired = db.table("file_requests").select("is_active").eq("id", expired_req["id"]).execute().data
        live = db.table("file_requests").select("is_active").eq("id", live_req["id"]).execute().data
        assert expired == [{"is_active": False}]
        assert live == [{"is_active": True}]

    def test_request_stays_active_when_storage_removal_fails(self, seeded, monkeypatch):
        from core.db import StorageBucket

        db = get_admin_client()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        request, upload = self._request_with_upload(seeded, expires_at=past)

        def boom(self, paths):
            raise RuntimeError("storage down")

        monkeypatch.setattr(StorageBucket, "remove", boom)
        asyncio.run(cleanup_expired_file_requests())
        monkeypatch.undo()

        assert db.table("file_requests").select("is_active").eq("id", request["id"]).execute().data == [{"is_active": True}]
        assert len(db.table("file_request_uploads").select("id").eq("id", upload["id"]).execute().data) == 1


# ---------------------------------------------------------------------------
# POST /api/upload/multi with several files
# ---------------------------------------------------------------------------

def _unique_ip() -> dict:
    return {"cf-connecting-ip": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMultiUpload:
    @pytest.fixture
    def owner(self):
        db = get_admin_client()
        uid = f"mu-{uuid.uuid4().hex}"
        db.table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
        user = User(id=uid, email=f"{uid}@example.com")
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_optional_user] = lambda: user
        created = {"slugs": []}
        yield user, created
        for slug in created["slugs"]:
            for row in db.table("shares").select("id").eq("slug", slug).execute().data:
                files = db.table("share_files").select("storage_path").eq("share_id", row["id"]).execute().data
                paths = [f["storage_path"] for f in files]
                if paths:
                    db.storage.from_("html-files").remove(paths)
                db.table("shares").delete().eq("id", row["id"]).execute()
        db.table("auth.users").delete().eq("id", uid).execute()

    def test_two_files_upload_and_owner_lists_and_reads_them(self, client, owner):
        user, created = owner

        resp = client.post(
            "/api/upload/multi",
            files=[
                ("files", ("first.html", b"<p>first</p>", "text/html")),
                ("files", ("second.md", b"# second", "text/markdown")),
            ],
            data={"is_private": "true"},
            headers=_unique_ip(),
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        created["slugs"].append(body["slug"])
        assert body["file_count"] == 2

        listing = client.get(f"/api/shares/{body['slug']}/files")
        assert listing.status_code == 200, listing.text
        files = listing.json()["files"]
        assert [(f["filename"], f["mime_type"], f["sort_order"]) for f in files] == [
            ("first.html", "text/html", 0),
            ("second.md", "text/markdown", 1),
        ]
        assert [f["file_size"] for f in files] == [len(b"<p>first</p>"), len(b"# second")]

        content = client.get(f"/api/shares/{body['slug']}/content")
        assert content.status_code == 200, content.text
        assert content.json()["content"] == "<p>first</p>"

        app.dependency_overrides[get_optional_user] = lambda: None
        assert client.get(f"/api/shares/{body['slug']}/files").status_code == 404

    def test_three_files_keep_sort_order(self, client, owner):
        _, created = owner

        resp = client.post(
            "/api/upload/multi",
            files=[
                ("files", ("a.html", b"<p>a</p>", "text/html")),
                ("files", ("b.html", b"<p>b</p>", "text/html")),
                ("files", ("c.html", b"<p>c</p>", "text/html")),
            ],
            headers=_unique_ip(),
        )

        assert resp.status_code == 200, resp.text
        created["slugs"].append(resp.json()["slug"])
        files = client.get(f"/api/shares/{resp.json()['slug']}/files").json()["files"]
        assert [f["filename"] for f in files] == ["a.html", "b.html", "c.html"]
