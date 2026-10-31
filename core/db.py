"""
PostgREST compatibility shim — local PostgreSQL + MinIO backend.

Replaces supabase-py by mimicking the fluent table/storage API:
    client.table("shares").select("*").eq("id", rid).execute()
    client.table("shares").insert({...}).execute()
    client.table("shares").update({...}).eq("id", rid).execute()
    client.table("shares").delete().eq("id", rid).execute()
    client.storage.from_("bucket").upload(path, bytes, file_options={...})
    client.storage.from_("bucket").download(path)
    client.storage.from_("bucket").remove([path])
    client.rpc("func_name", {...}).execute()

All execute() calls are SYNCHRONOUS — callers wrap them in
asyncio.to_thread(). This module runs a background event loop
to serve asyncpg queries from sync context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

import asyncpg

from core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Background event loop — asyncpg is async-only, but callsites are sync
# ---------------------------------------------------------------------------

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()
_pool: asyncpg.Pool | None = None
# Created lazily on the background loop, which runs every coroutine that uses it.
_pool_lock: asyncio.Lock | None = None


def _start_background_loop():
    """Start a dedicated event loop in a background thread for asyncpg."""
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop

    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop

        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()

        thread = threading.Thread(target=_run_loop, name="db-event-loop", daemon=True)
        thread.start()
        if not ready.wait(timeout=1):
            raise RuntimeError("Failed to start background event loop")

        _loop, _loop_thread = loop, thread
        return loop


def _run_async(coro):
    """Submit a coroutine to the background loop and block until done."""
    loop = _start_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


async def _get_pool() -> asyncpg.Pool:
    global _pool, _pool_lock
    if _pool is not None and not _pool._closed:
        return _pool
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _pool is None or _pool._closed:
            _pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
    return _pool


# ---------------------------------------------------------------------------
# Response types — mimic supabase-py
# ---------------------------------------------------------------------------

class PostgRESTResponse:
    __slots__ = ("data", "count")

    def __init__(self, data=None, count: int | None = None):
        # A scalar RPC result (0, False) is data, not "no rows".
        self.data = [] if data is None else data
        self.count = count

    def __repr__(self):
        return f"PostgRESTResponse(data={self.data!r}, count={self.count})"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_row(row) -> dict:
    """Convert an asyncpg Record to a JSON-serializable dict."""
    out = {}
    for key, val in dict(row).items():
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, list):
            out[key] = list(val)
        else:
            out[key] = val
    return out


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_SPLIT_TOP_LEVEL = re.compile(r",\s*(?![^()]*\))")
_EMBED = re.compile(r"^(\w+)(?:!(\w+))?\((.+)\)$")

# Column of the foreign table a to-one embed matches the base column against.
# Firebase uids are user_profiles.user_id (TEXT); user_profiles.id is a UUID.
_EMBED_KEY = {"user_profiles": "user_id"}


def _identifier(name: str) -> str:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"select spec: {name!r} is not a valid identifier")
    return name


def _parse_select_columns(columns: str) -> tuple[list[str], list[tuple[str, str | None, list[str]]]]:
    """Split a PostgREST select string into main columns and embeds.

    "team_id, role, teams(*)"            -> (["team_id", "role"], [("teams", None, ["*"])])
    "*, user_profiles!user_id(a, b)"     -> (["*"], [("user_profiles", "user_id", ["a", "b"])])
    """
    main_cols: list[str] = []
    embeds: list[tuple[str, str | None, list[str]]] = []
    for part in (p.strip() for p in _SPLIT_TOP_LEVEL.split(columns)):
        if not part:
            continue
        match = _EMBED.match(part)
        if match:
            table, hint, inner = match.groups()
            embeds.append((table, hint, [c.strip() for c in inner.split(",") if c.strip()]))
        else:
            main_cols.append(part)
    return main_cols, embeds


def _fk_guess(table: str) -> str:
    """Key column named after a table: teams -> team_id, team_shares -> team_share_id."""
    return (table[:-1] if table.endswith("s") else table) + "_id"


def embed_join(
    base: str, foreign: str, hint: str | None, base_cols, foreign_cols,
) -> tuple[bool, str, str]:
    """How an embed relates to its base table: (to_one, base column, foreign column).

    To-one when the base table holds the key: the hint, or `<foreign singular>_id`,
    is a base column; it matches the foreign table's `_EMBED_KEY` column (default `id`).
    Otherwise to-many when the foreign table holds the key: the hint, or
    `<base singular>_id`, is a foreign column referencing base `id`.
    """
    col = hint or _fk_guess(foreign)
    if col in base_cols:
        return True, col, _EMBED_KEY.get(foreign, "id")
    col = hint or _fk_guess(base.rsplit(".", 1)[-1])
    if col in foreign_cols:
        return False, "id", col
    raise ValueError(
        f"select spec: no column relates {base} to {foreign}"
        + (f" through {hint!r}" if hint else "")
    )


# ---------------------------------------------------------------------------
# Parameter coercion — asyncpg rejects ISO-8601 strings for temporal columns
# ---------------------------------------------------------------------------

def _to_timestamptz(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    # asyncpg reads a naive datetime as local time; callers mean UTC.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _to_timestamp(value: str) -> datetime:
    # `timestamp` has no zone: store the UTC wall clock, and asyncpg wants it naive.
    return _to_timestamptz(value).astimezone(timezone.utc).replace(tzinfo=None)


def _to_date(value: str) -> date:
    return date.fromisoformat(value)


# Postgres type name (PreparedStatement.get_parameters()) -> str converter.
_PARAM_CONVERTERS = {
    "timestamptz": _to_timestamptz,
    "timestamp": _to_timestamp,
    "date": _to_date,
}


# SQL string -> declared parameter type names. Bounded: IN lists and batch inserts
# produce many distinct SQL strings.
_PARAM_TYPES_MAX = 512
_param_types: dict[str, tuple[str, ...]] = {}


async def _declared_types(conn, sql: str) -> tuple[str, ...]:
    """Parameter type names Postgres reports for `sql`, prepared at most once per SQL.

    Connection.prepare bypasses asyncpg's statement cache, so the actual execution
    goes through conn.fetch / conn.fetchval, which use it.
    """
    types = _param_types.get(sql)
    if types is None:
        stmt = await conn.prepare(sql)
        types = tuple(p.name for p in stmt.get_parameters())
        if len(_param_types) >= _PARAM_TYPES_MAX:
            _param_types.pop(next(iter(_param_types)))
        _param_types[sql] = types
    return types


async def _coerce(conn, sql: str, params: list | tuple) -> list:
    """Convert str params bound to temporal columns; other values pass through."""
    args = list(params)
    if not any(isinstance(a, str) for a in args):
        return args
    for i, name in enumerate(await _declared_types(conn, sql)):
        convert = _PARAM_CONVERTERS.get(name)
        if convert is not None and i < len(args) and isinstance(args[i], str):
            args[i] = convert(args[i])
    return args


# Table name -> its column names, read once from the catalog (the schema is fixed at runtime).
_table_columns: dict[str, frozenset[str]] = {}


async def _columns_of(conn, table: str) -> frozenset[str]:
    cols = _table_columns.get(table)
    if cols is None:
        schema, name = table.split(".", 1) if "." in table else ("public", table)
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2",
            schema, name,
        )
        cols = frozenset(r["column_name"] for r in rows)
        if not cols:
            raise ValueError(f"select spec: unknown table {table!r}")
        _table_columns[table] = cols
    return cols


# Function name -> whether it returns a single scalar (PostgREST then returns the value itself).
_scalar_functions: dict[str, bool] = {}


async def _returns_scalar(conn, func: str) -> bool:
    scalar = _scalar_functions.get(func)
    if scalar is None:
        scalar = bool(await conn.fetchval(
            "SELECT bool_and(NOT p.proretset AND t.typtype IN ('b', 'd', 'e', 'r', 'm')) "
            "FROM pg_proc p JOIN pg_type t ON t.oid = p.prorettype WHERE p.proname = $1",
            func,
        ))
        _scalar_functions[func] = scalar
    return scalar


async def _fetch(conn, sql: str, params: list | tuple = ()):
    return await conn.fetch(sql, *await _coerce(conn, sql, params))


async def _fetchval(conn, sql: str, params: list | tuple = ()):
    return await conn.fetchval(sql, *await _coerce(conn, sql, params))


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

class QueryBuilder:
    """Fluent builder mimicking PostgREST / supabase-py table API."""

    def __init__(self, table: str):
        self._table = table
        self._op: str = "select"
        self._columns: str = "*"
        self._filters: list[tuple[str, str, Any, bool]] = []  # (col, op, val, negated)
        self._negate_next = False
        self._order_by: tuple[str, str] | None = None
        self._limit_val: int | None = None
        self._offset_val: int | None = None
        self._payload: dict | list[dict] | None = None
        self._count: str | None = None

    # --- Query type setters ---
    def select(self, columns: str = "*", count: str | None = None) -> "QueryBuilder":
        self._op = "select"
        self._columns = columns
        self._count = count  # 'exact' | 'planned' | None — ignored, we always RETURN *
        return self

    def insert(self, row_data) -> "QueryBuilder":
        self._op = "insert"
        self._payload = row_data
        return self

    def upsert(self, row_data, on_conflict: str, ignore_duplicates: bool = False) -> "QueryBuilder":
        """INSERT … ON CONFLICT (on_conflict): update the other columns, or skip the row."""
        self._op = "upsert"
        self._payload = row_data
        target = [_identifier(c.strip()) for c in on_conflict.split(",") if c.strip()]
        if not target:
            raise ValueError("upsert needs on_conflict columns")
        self._on_conflict = (target, ignore_duplicates)
        return self

    def update(self, update_data: dict) -> "QueryBuilder":
        self._op = "update"
        self._payload = update_data
        return self

    def delete(self) -> "QueryBuilder":
        self._op = "delete"
        return self

    # --- Filters (PostgREST operators) ---
    def _add_filter(self, col: str, op: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, op, val, self._negate_next))
        self._negate_next = False
        return self

    @property
    def not_(self) -> "_NegatedFilters":
        """Negate the next filter: `.not_.is_("col", None)` -> `col IS NOT NULL`."""
        return _NegatedFilters(self)

    def eq(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "=", val)

    def neq(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "!=", val)

    def gt(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, ">", val)

    def gte(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, ">=", val)

    def lt(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "<", val)

    def lte(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "<=", val)

    def like(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "LIKE", val)

    def ilike(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "ILIKE", val)

    def in_(self, col: str, val: list) -> "QueryBuilder":
        return self._add_filter(col, "IN", val)

    def is_(self, col: str, val: Any) -> "QueryBuilder":
        if val is None or (isinstance(val, str) and val.lower() == "null"):
            return self._add_filter(col, "IS NULL", None)
        if isinstance(val, str) and val.lower() == "not.null":
            return self._add_filter(col, "IS NOT NULL", None)
        return self._add_filter(col, "IS", val)

    def contains(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "@>", val)

    def overlaps(self, col: str, val: Any) -> "QueryBuilder":
        return self._add_filter(col, "&&", val)

    # --- Pagination / ordering ---
    def order(self, col: str, desc: bool = False, foreign_table: str | None = None) -> "QueryBuilder":
        self._order_by = (col, "DESC" if desc else "ASC"); return self

    def limit(self, n: int) -> "QueryBuilder":
        self._limit_val = n; return self

    def range(self, start: int, end: int) -> "QueryBuilder":
        self._offset_val = start
        self._limit_val = end - start + 1
        return self

    def single(self) -> "QueryBuilder":
        self._limit_val = 1; return self

    # --- Build WHERE clause ---
    def _build_where(self, param_offset: int = 0) -> tuple[str, list]:
        if not self._filters:
            return "", []

        parts: list[str] = []
        params: list = []
        idx = param_offset
        for col, op, val, negated in self._filters:
            idx += 1
            if op in ("IS NULL", "IS NOT NULL"):
                idx -= 1  # no param consumed
                if negated:
                    op = "IS NOT NULL" if op == "IS NULL" else "IS NULL"
                parts.append(f"{col} {op}")
                continue
            if op == "IN":
                if not val:
                    # `IN ()` is a syntax error; an empty set matches nothing.
                    idx -= 1
                    parts.append("TRUE" if negated else "FALSE")
                    continue
                ph = ", ".join(f"${idx + j}" for j in range(len(val)))
                clause = f"{col} IN ({ph})"
                params.extend(val)
                idx += len(val) - 1
            elif op in ("@>", "&&"):
                # Lists bind as arrays; only a dict is a jsonb document.
                params.append(json.dumps(val) if isinstance(val, dict) else val)
                clause = f"{col} {op} ${idx}"
            else:
                params.append(val)
                clause = f"{col} {op} ${idx}"
            # NOT (...) follows SQL three-valued logic, as PostgREST's not.<op> does:
            # rows where the column is NULL are not returned by a negated comparison.
            parts.append(f"NOT ({clause})" if negated else clause)

        return " WHERE " + " AND ".join(parts), params

    # --- Execute ---
    def execute(self) -> PostgRESTResponse:
        """Run the query synchronously (called via asyncio.to_thread)."""
        return _run_async(self._run())

    async def _run(self) -> PostgRESTResponse:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            if self._op == "select":
                return await self._do_select(conn)
            elif self._op in ("insert", "upsert"):
                return await self._do_insert(conn)
            elif self._op == "update":
                return await self._do_update(conn)
            elif self._op == "delete":
                return await self._do_delete(conn)

    async def _embed_columns(self, conn, main_cols: list[str], embeds) -> list[str]:
        """Select-list entries: main columns, then one JSON subquery per embed.

        A correlated subquery per embed keeps the FROM clause to the base table, so
        main columns, filters and ORDER BY never collide with foreign column names,
        and an unmatched to-one embed is NULL rather than an object of NULLs.
        """
        table = self._table
        for name in table.split("."):
            _identifier(name)
        for col in main_cols:
            if col != "*":
                _identifier(col)
        out = [f"{table}.*" if c == "*" else f"{table}.{c}" for c in main_cols]
        base_cols = await _columns_of(conn, table)
        for i, (foreign, hint, cols) in enumerate(embeds):
            _identifier(foreign)
            if hint is not None:
                _identifier(hint)
            alias = f"_e{i}"
            if cols == ["*"]:
                obj = f"to_json({alias})"
            else:
                obj = "json_build_object(" + ", ".join(
                    f"'{_identifier(c)}', {alias}.{c}" for c in cols
                ) + ")"
            to_one, base_col, foreign_col = embed_join(
                table, foreign, hint, base_cols, await _columns_of(conn, foreign),
            )
            match = f"FROM {foreign} AS {alias} WHERE {alias}.{foreign_col} = {table}.{base_col}"
            if to_one:
                out.append(f"(SELECT {obj} {match}) AS {foreign}")
            else:
                out.append(f"COALESCE((SELECT json_agg({obj}) {match}), '[]'::json) AS {foreign}")
        return out

    async def _do_select(self, conn) -> PostgRESTResponse:
        where, params = self._build_where()

        main_cols, embeds = _parse_select_columns(self._columns)
        if embeds:
            select_list = ", ".join(await self._embed_columns(conn, main_cols, embeds))
        else:
            select_list = ", ".join(main_cols) if main_cols else "*"
        sql = f"SELECT {select_list} FROM {self._table}"
        sql += where

        if self._order_by:
            # Qualify column with table name to avoid ambiguity in JOINs
            order_col = self._order_by[0]
            if "." not in order_col:
                order_col = f"{self._table}.{order_col}"
            sql += f" ORDER BY {order_col} {self._order_by[1]}"
        if self._limit_val is not None:
            sql += f" LIMIT {self._limit_val}"
        if self._offset_val is not None:
            sql += f" OFFSET {self._offset_val}"

        logger.debug("SQL: %s PARAMS: %s", sql, params)
        rows = await _fetch(conn, sql, params)

        # Populate count if requested
        count_val = None
        if self._count == "exact":
            count_sql = f"SELECT COUNT(*) FROM {self._table}{where}"
            count_row = await _fetchval(conn, count_sql, params)
            count_val = count_row

        data = [_serialize_row(r) for r in rows]
        # asyncpg hands json back as text; nest it the way PostgREST does.
        for row in data:
            for foreign, _, _ in embeds:
                if row[foreign] is not None:
                    row[foreign] = json.loads(row[foreign])

        return PostgRESTResponse(data=data, count=count_val)

    async def _do_insert(self, conn) -> PostgRESTResponse:
        payload = self._payload
        rows_in = payload if isinstance(payload, list) else [payload]
        if not rows_in:
            return PostgRESTResponse(data=[])

        cols, values, params = self._insert_values(rows_in)
        sql = f"INSERT INTO {self._table} ({', '.join(cols)}) VALUES {values}"
        if self._op == "upsert":
            target, ignore = self._on_conflict
            if ignore:
                sql += f" ON CONFLICT ({', '.join(target)}) DO NOTHING"
            else:
                # With nothing but conflict columns, a no-op SET still returns the existing row.
                updated = [c for c in cols if c not in target] or target
                sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in updated)
                sql += f" ON CONFLICT ({', '.join(target)}) DO UPDATE SET {sets}"
        rows = await _fetch(conn, sql + " RETURNING *", params)
        return PostgRESTResponse(data=[_serialize_row(r) for r in rows])

    @staticmethod
    def _insert_values(rows_in: list[dict]) -> tuple[list[str], str, list]:
        """Column list, VALUES groups and their parameters for one INSERT of `rows_in`."""
        # Union of keys: first row's order, then keys first seen in later rows.
        cols = list(dict.fromkeys(key for row in rows_in for key in row))

        # One VALUES group per row. A key a row does not carry takes the column
        # default (NULL when it has none), as the single-row insert does by omitting it.
        groups: list[str] = []
        params: list = []
        for row in rows_in:
            slots = []
            for col in cols:
                if col in row:
                    params.append(row[col])
                    slots.append(f"${len(params)}")
                else:
                    slots.append("DEFAULT")
            groups.append(f"({', '.join(slots)})")
        return cols, ", ".join(groups), params

    async def _do_update(self, conn) -> PostgRESTResponse:
        update_data = self._payload or {}
        set_parts = []
        set_params = []
        for i, (col, val) in enumerate(update_data.items()):
            if isinstance(val, str) and val == "now()":
                set_parts.append(f"{col} = now()")
            else:
                set_parts.append(f"{col} = ${i+1}")
                set_params.append(val)

        param_offset = len(set_params)
        where, where_params = self._build_where(param_offset)
        sql = f"UPDATE {self._table} SET {', '.join(set_parts)}{where} RETURNING *"

        logger.debug("SQL: %s PARAMS: %s", sql, set_params + where_params)
        rows = await _fetch(conn, sql, [*set_params, *where_params])
        return PostgRESTResponse(data=[_serialize_row(r) for r in rows])

    async def _do_delete(self, conn) -> PostgRESTResponse:
        where, params = self._build_where()
        sql = f"DELETE FROM {self._table}{where} RETURNING *"
        rows = await _fetch(conn, sql, params)
        return PostgRESTResponse(data=[_serialize_row(r) for r in rows])


class _NegatedFilters:
    """What `QueryBuilder.not_` returns: exposes only the filter methods, each negated."""

    _FILTERS = frozenset({
        "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in_", "is_", "contains", "overlaps",
    })

    def __init__(self, builder: QueryBuilder):
        self._builder = builder

    def __getattr__(self, name: str):
        if name not in self._FILTERS:
            raise AttributeError(f"not_ can only negate filters, not {name!r}")
        apply = getattr(self._builder, name)

        def negated(*args, **kwargs) -> QueryBuilder:
            self._builder._negate_next = True
            try:
                return apply(*args, **kwargs)
            finally:
                self._builder._negate_next = False

        return negated


# ---------------------------------------------------------------------------
# RPC builder
# ---------------------------------------------------------------------------

class RPCBuilder:
    def __init__(self, func: str, params: dict):
        self._func = func
        self._params = params

    def execute(self) -> PostgRESTResponse:
        return _run_async(self._run())

    async def _run(self) -> PostgRESTResponse:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Named notation, as PostgREST binds: dict order is irrelevant and
            # omitted parameters take their SQL defaults.
            keys = list(self._params.keys())
            args = ", ".join(f"{k} => ${i+1}" for i, k in enumerate(keys))
            vals = [self._params[k] for k in keys]
            sql = f"SELECT * FROM {self._func}({args})"
            rows = await _fetch(conn, sql, vals)
            data = [_serialize_row(r) for r in rows]
            if data and await _returns_scalar(conn, self._func):
                return PostgRESTResponse(data=next(iter(data[0].values())))
            return PostgRESTResponse(data=data)


# ---------------------------------------------------------------------------
# Storage — MinIO/S3 via boto3
# ---------------------------------------------------------------------------

# Objects meant to be fetched anonymously live under this key prefix in the
# `html-files` bucket; the bucket policy grants anonymous download on it alone.
PUBLIC_PREFIX = "public/"


def public_object_url(bucket: str, key: str) -> str:
    """Browser-facing URL of a storage object. Only meaningful for keys under PUBLIC_PREFIX."""
    return f"{settings.storage_public_url.rstrip('/')}/{bucket}/{key}"


class StorageBucket:
    def __init__(self, bucket: str):
        self._bucket = bucket

    def _client(self):
        import boto3
        from botocore.client import Config as BotoConfig
        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def upload(self, path: str, file: bytes, file_options: dict | None = None):
        ct = (file_options or {}).get("content-type", "application/octet-stream")
        self._client().put_object(
            Bucket=self._bucket, Key=path, Body=file, ContentType=ct
        )
        return {"path": path}

    def download(self, path: str) -> bytes:
        resp = self._client().get_object(Bucket=self._bucket, Key=path)
        return resp["Body"].read()

    def remove(self, paths: list[str]):
        objs = [{"Key": p} for p in paths]
        self._client().delete_objects(
            Bucket=self._bucket, Delete={"Objects": objs}
        )
        return {"paths": paths}

    def update(self, path: str, file: bytes, file_options: dict | None = None):
        """Overwrite an existing object (same as upload in S3)."""
        return self.upload(path, file, file_options)


class StorageNamespace:
    def from_(self, bucket: str) -> StorageBucket:
        return StorageBucket(bucket)


# ---------------------------------------------------------------------------
# Main client — drop-in replacement for supabase-py Client
# ---------------------------------------------------------------------------

class DatabaseClient:
    """Drop-in replacement for supabase-py Client.

    Exposes .table(), .storage, .rpc() matching the Supabase client API
    so core/supabase.py can return this with zero callsite changes.
    """

    storage = StorageNamespace()

    def table(self, name: str) -> QueryBuilder:
        return QueryBuilder(name)

    def rpc(self, func: str, params: dict) -> RPCBuilder:
        return RPCBuilder(func, params)


# ---------------------------------------------------------------------------
# Factory — called by core/supabase.py
# ---------------------------------------------------------------------------

_client: DatabaseClient | None = None


def get_admin_client() -> DatabaseClient:
    """Return the singleton DatabaseClient (replaces Supabase admin client)."""
    global _client
    if _client is None:
        _client = DatabaseClient()
    return _client


def get_anon_client() -> DatabaseClient:
    """Same client — local dev has no anon/admin distinction."""
    return get_admin_client()


def get_user_client(access_token: str) -> DatabaseClient:
    """Same client — authz enforced at app level via user_id filters."""
    return get_admin_client()
