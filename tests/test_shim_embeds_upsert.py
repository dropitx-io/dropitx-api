"""Live-DB tests: nested selects (embeds), upsert and scalar RPC results in the DB shim.

Runs against the real Postgres from CI. Expected shapes follow PostgREST: an embed
is keyed by the foreign table name and holds an object or null (to-one) or a list
(to-many) with only the named columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from core.db import _get_pool, _run_async
from core.supabase import get_admin_client

INSTANT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _ddl(sql: str) -> None:
    async def run():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql)

    _run_async(run())


@pytest.fixture
def db():
    return get_admin_client()


@pytest.fixture
def rel():
    """A parent table `ep_<tag>s` and a child `ec_<tag>` holding `ep_<tag>_id`."""
    tag = uuid.uuid4().hex[:8]
    parent, child, fk = f"ep_{tag}s", f"ec_{tag}", f"ep_{tag}_id"
    _ddl(
        f"CREATE TABLE {parent} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text, "
        f"created_at timestamptz NOT NULL DEFAULT '2030-01-02T03:04:05Z');"
        f"CREATE TABLE {child} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        f"{fk} uuid REFERENCES {parent}(id), owner_uid text, label text, "
        f"created_at timestamptz NOT NULL DEFAULT now())"
    )
    yield parent, child, fk
    _ddl(f"DROP TABLE {child}; DROP TABLE {parent}")


@pytest.fixture
def family(db, rel):
    """Parent P with children a and b, parent Q with none, orphan child c."""
    parent, child, fk = rel
    p, q = db.table(parent).insert([{"name": "P"}, {"name": "Q"}]).execute().data
    a, b, c = db.table(child).insert([
        {fk: p["id"], "label": "a"},
        {fk: p["id"], "label": "b"},
        {"label": "c"},
    ]).execute().data
    return {"p": p, "q": q, "a": a, "b": b, "c": c}


class TestToOne:
    def test_embed_is_an_object_with_the_named_columns_or_null(self, db, rel, family):
        parent, child, _ = rel

        rows = db.table(child).select(f"*, {parent}(id, name)").order("label").execute().data

        assert [(r["label"], r[parent]) for r in rows] == [
            ("a", {"id": family["p"]["id"], "name": "P"}),
            ("b", {"id": family["p"]["id"], "name": "P"}),
            ("c", None),
        ]

    def test_main_row_id_is_not_overwritten_by_the_joined_id(self, db, rel, family):
        parent, child, _ = rel

        rows = db.table(child).select(f"*, {parent}(*)").order("label").execute().data

        assert [r["id"] for r in rows] == [family["a"]["id"], family["b"]["id"], family["c"]["id"]]

    def test_star_embeds_every_foreign_column(self, db, rel, family):
        parent, child, _ = rel

        (row,) = db.table(child).select(f"label, {parent}(*)").eq("label", "a").execute().data

        embedded = row[parent]
        assert set(embedded) == {"id", "name", "created_at"}
        assert (embedded["id"], embedded["name"]) == (family["p"]["id"], "P")
        assert datetime.fromisoformat(embedded["created_at"]) == INSTANT

    def test_only_listed_main_columns_and_the_embed_are_returned(self, db, rel, family):
        parent, child, _ = rel

        (row,) = db.table(child).select(f"label, {parent}(name)").eq("label", "b").execute().data

        assert row == {"label": "b", parent: {"name": "P"}}

    def test_embed_only_select_returns_just_the_embed(self, db, rel, family):
        parent, child, _ = rel

        (row,) = db.table(child).select(f"{parent}(name)").eq("label", "a").execute().data

        assert row == {parent: {"name": "P"}}

    def test_filters_order_and_count_use_the_main_table_columns(self, db, rel, family):
        parent, child, _ = rel

        # `id` and `created_at` exist on both tables: they must mean the child's.
        resp = (
            db.table(child).select(f"id, {parent}(name)", count="exact")
            .eq("id", family["b"]["id"])
            .order("created_at", desc=True)
            .execute()
        )

        assert resp.data == [{"id": family["b"]["id"], parent: {"name": "P"}}]
        assert resp.count == 1


class TestToMany:
    def test_embed_is_a_list_of_the_children_or_empty(self, db, rel, family):
        parent, child, _ = rel

        rows = db.table(parent).select(f"name, {child}(label)").order("name").execute().data

        assert [(r["name"], sorted(c["label"] for c in r[child])) for r in rows] == [
            ("P", ["a", "b"]),
            ("Q", []),
        ]
        assert all(isinstance(r[child], list) for r in rows)

    def test_hint_names_the_foreign_column_that_references_the_parent(self, db, rel, family):
        parent, child, fk = rel

        (row,) = db.table(parent).select(f"*, {child}!{fk}(id)").eq("name", "P").execute().data

        assert row["id"] == family["p"]["id"]
        assert sorted(c["id"] for c in row[child]) == sorted([family["a"]["id"], family["b"]["id"]])


class TestHintedToOne:
    def test_user_profiles_hint_joins_the_uid_column_on_user_profiles_user_id(self, db, rel):
        _, child, _ = rel
        uid = f"u-{uuid.uuid4().hex[:10]}"
        db.table("auth.users").insert({"id": uid}).execute()
        try:
            profile = db.table("user_profiles").insert({"user_id": uid, "display_name": "Ann"}).execute().data[0]
            mine = db.table(child).insert({"owner_uid": uid, "label": "mine"}).execute().data[0]
            db.table(child).insert({"owner_uid": "someone-else", "label": "theirs"}).execute()

            rows = (
                db.table(child).select("*, user_profiles!owner_uid(id, display_name)")
                .order("label").execute().data
            )

            assert [(r["id"], r["label"], r["user_profiles"]) for r in rows][0] == (
                mine["id"], "mine", {"id": profile["id"], "display_name": "Ann"},
            )
            assert rows[1]["user_profiles"] is None
        finally:
            db.table("auth.users").delete().eq("id", uid).execute()


class TestSpecValidation:
    def test_a_non_identifier_embed_column_is_rejected(self, db, rel):
        parent, child, _ = rel

        with pytest.raises(ValueError, match="identifier"):
            db.table(child).select(f"*, {parent}(name; DROP TABLE x)").execute()

    def test_an_embed_with_no_relating_column_is_rejected(self, db, rel):
        parent, _, _ = rel

        with pytest.raises(ValueError, match="teams"):
            db.table(parent).select("*, teams(*)").execute()


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------

@pytest.fixture
def pairs():
    name = f"up_{uuid.uuid4().hex[:8]}"
    _ddl(
        f"CREATE TABLE {name} (id serial PRIMARY KEY, a text NOT NULL, b text NOT NULL, "
        f"n integer, tz timestamptz, UNIQUE (a, b))"
    )
    yield name
    _ddl(f"DROP TABLE {name}")


def _stored(db, table) -> list[tuple]:
    rows = db.table(table).select("a, b, n").order("id").execute().data
    return [(r["a"], r["b"], r["n"]) for r in rows]


class TestUpsert:
    def test_new_key_inserts_and_returns_the_row(self, db, pairs):
        rows = db.table(pairs).upsert({"a": "x", "b": "y", "n": 1}, on_conflict="a,b").execute().data

        assert [(r["a"], r["b"], r["n"]) for r in rows] == [("x", "y", 1)]
        assert _stored(db, pairs) == [("x", "y", 1)]

    def test_existing_key_updates_the_other_columns(self, db, pairs):
        first = db.table(pairs).upsert({"a": "x", "b": "y", "n": 1}, on_conflict="a,b").execute().data[0]

        rows = db.table(pairs).upsert({"a": "x", "b": "y", "n": 2}, on_conflict="a,b").execute().data

        assert [(r["id"], r["n"]) for r in rows] == [(first["id"], 2)]
        assert _stored(db, pairs) == [("x", "y", 2)]

    def test_ignore_duplicates_keeps_the_existing_row_and_returns_nothing_for_it(self, db, pairs):
        db.table(pairs).upsert({"a": "x", "b": "y", "n": 1}, on_conflict="a,b").execute()

        rows = (
            db.table(pairs)
            .upsert({"a": "x", "b": "y", "n": 2}, on_conflict="a,b", ignore_duplicates=True)
            .execute().data
        )

        assert rows == []
        assert _stored(db, pairs) == [("x", "y", 1)]

    def test_payload_of_only_conflict_columns_is_idempotent_and_returns_the_row(self, db, pairs):
        first = db.table(pairs).upsert({"a": "x", "b": "y"}, on_conflict="a,b").execute().data
        second = db.table(pairs).upsert({"a": "x", "b": "y"}, on_conflict="a,b").execute().data

        assert [r["id"] for r in second] == [r["id"] for r in first]
        assert _stored(db, pairs) == [("x", "y", None)]

    def test_list_payload_inserts_new_keys_and_updates_existing_ones(self, db, pairs):
        db.table(pairs).upsert({"a": "x", "b": "y", "n": 1}, on_conflict="a,b").execute()

        rows = db.table(pairs).upsert(
            [{"a": "x", "b": "y", "n": 10}, {"a": "x", "b": "z", "n": 20}],
            on_conflict="a,b",
        ).execute().data

        assert sorted((r["b"], r["n"]) for r in rows) == [("y", 10), ("z", 20)]
        assert _stored(db, pairs) == [("x", "y", 10), ("x", "z", 20)]

    def test_iso_timestamp_strings_are_converted(self, db, pairs):
        (row,) = db.table(pairs).upsert(
            {"a": "x", "b": "y", "tz": "2030-01-02T10:04:05+07:00"}, on_conflict="a,b",
        ).execute().data

        assert datetime.fromisoformat(row["tz"]) == INSTANT


# ---------------------------------------------------------------------------
# Scalar RPC results
# ---------------------------------------------------------------------------

class TestScalarRpc:
    """PostgREST returns a scalar function's value itself, not a one-row table."""

    def test_integer_function_returns_the_number(self, db):
        assert db.rpc("get_star_count", {"p_share_id": str(uuid.uuid4())}).execute().data == 0

    def test_boolean_function_returns_the_boolean(self, db):
        resp = db.rpc("has_user_starred", {"p_share_id": str(uuid.uuid4()), "p_user_id": "nobody"}).execute()

        assert resp.data is False

    def test_table_function_still_returns_rows(self, db):
        resp = db.rpc("check_rate_limit", {
            "p_key": f"shim-scalar-{uuid.uuid4().hex}", "p_max_attempts": 5, "p_window_secs": 60,
        }).execute()

        assert isinstance(resp.data, list) and resp.data[0]["success"] is True
