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
import threading
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
_pool: asyncpg.Pool | None = None


def _start_background_loop():
    """Start a dedicated event loop in a background thread for asyncpg."""
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop

    def _run_loop():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_forever()

    _loop_thread = threading.Thread(target=_run_loop, daemon=True)
    _loop_thread.start()

    # Wait for loop to be ready
    import time
    for _ in range(100):
        if _loop is not None and _loop.is_running():
            return _loop
        time.sleep(0.01)

    raise RuntimeError("Failed to start background event loop")


def _run_async(coro):
    """Submit a coroutine to the background loop and block until done."""
    loop = _start_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


async def _get_pool() -> asyncpg.Pool:
    global _pool
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
        self.data = data or []
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
        elif hasattr(val, "hex") and not isinstance(val, (str, bytes)):
            out[key] = str(val)
        elif isinstance(val, list):
            out[key] = list(val)
        else:
            out[key] = val
    return out


def _parse_select_columns(columns: str):
    """Parse PostgREST select syntax into main columns and JOIN specs.

    Examples:
        "team_id, role, joined_at, teams(*)"
            → (["team_id", "role", "joined_at"], [("team_id", "teams", "*")])
        "*, user_profiles!user_id(display_name, avatar_url)"
            → (["*"], [("user_id", "user_profiles", "display_name, avatar_url")])
        "*, teams(id, name, slug), user_profiles!invited_by(id, display_name)"
            → (["*"], [("team_id", "teams", "id, name, slug"), ("invited_by", "user_profiles", "id, display_name")])

    Returns:
        (main_columns: list[str], joins: list[(fk_col, fk_table, fk_cols)])
    """
    import re

    main_cols = []
    joins = []

    # Split on commas, but not inside parentheses
    parts = re.split(r",\s*(?![^()]*\))", columns)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Check if this is a nested foreign table select: table(cols) or table!fk_col(cols)
        match = re.match(r"^(\w+)(?:!(\w+))?\((.+)\)$", part)
        if match:
            fk_table = match.group(1)
            explicit_fk = match.group(2)  # e.g. "user_id" from "user_profiles!user_id(...)"
            nested_cols = match.group(3)

            # Determine FK column: explicit or guess "{table_singular}_id"
            if explicit_fk:
                fk_col = explicit_fk
            else:
                # Guess: "teams" → "team_id", "user_profiles" → "user_id"
                if fk_table.endswith("s"):
                    fk_col = fk_table[:-1] + "_id"
                else:
                    fk_col = fk_table + "_id"

            joins.append((fk_col, fk_table, nested_cols))
        else:
            # Regular column
            main_cols.append(part)

    return main_cols, joins


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


async def _bind(conn, sql: str, params: list | tuple):
    """Prepare `sql` and convert str params to what their declared type needs."""
    stmt = await conn.prepare(sql)
    args = list(params)
    for i, declared in enumerate(stmt.get_parameters()):
        convert = _PARAM_CONVERTERS.get(declared.name)
        if convert is not None and i < len(args) and isinstance(args[i], str):
            args[i] = convert(args[i])
    return stmt, args


async def _fetch(conn, sql: str, params: list | tuple = ()):
    stmt, args = await _bind(conn, sql, params)
    return await stmt.fetch(*args)


async def _fetchval(conn, sql: str, params: list | tuple = ()):
    stmt, args = await _bind(conn, sql, params)
    return await stmt.fetchval(*args)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

class QueryBuilder:
    """Fluent builder mimicking PostgREST / supabase-py table API."""

    def __init__(self, table: str):
        self._table = table
        self._op: str = "select"
        self._columns: str = "*"
        self._filters: list[tuple[str, str, Any]] = []
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

    def update(self, update_data: dict) -> "QueryBuilder":
        self._op = "update"
        self._payload = update_data
        return self

    def delete(self) -> "QueryBuilder":
        self._op = "delete"
        return self

    # --- Filters (PostgREST operators) ---
    def eq(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "=", val)); return self

    def neq(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "!=", val)); return self

    def gt(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, ">", val)); return self

    def gte(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, ">=", val)); return self

    def lt(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "<", val)); return self

    def lte(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "<=", val)); return self

    def like(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "LIKE", val)); return self

    def ilike(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "ILIKE", val)); return self

    def in_(self, col: str, val: list) -> "QueryBuilder":
        self._filters.append((col, "IN", val)); return self

    def is_(self, col: str, val: Any) -> "QueryBuilder":
        if val is None or (isinstance(val, str) and val.lower() == "null"):
            self._filters.append((col, "IS NULL", None))
        elif isinstance(val, str) and val.lower() == "not.null":
            self._filters.append((col, "IS NOT NULL", None))
        else:
            self._filters.append((col, "IS", val))
        return self

    def contains(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "@>", val)); return self

    def overlaps(self, col: str, val: Any) -> "QueryBuilder":
        self._filters.append((col, "&&", val)); return self

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
        for col, op, val in self._filters:
            idx += 1
            if op == "IS NULL":
                parts.append(f"{col} IS NULL")
                idx -= 1  # no param consumed
            elif op == "IS NOT NULL":
                parts.append(f"{col} IS NOT NULL")
                idx -= 1  # no param consumed
            elif op == "IN":
                ph = ", ".join(f"${idx + j}" for j in range(len(val)))
                parts.append(f"{col} IN ({ph})")
                params.extend(val)
                idx += len(val) - 1
            elif op in ("@>", "&&"):
                params.append(val if isinstance(val, str) else json.dumps(val))
                parts.append(f"{col} ${idx}")
            else:
                params.append(val)
                parts.append(f"{col} {op} ${idx}")

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
            elif self._op == "insert":
                return await self._do_insert(conn)
            elif self._op == "update":
                return await self._do_update(conn)
            elif self._op == "delete":
                return await self._do_delete(conn)

    async def _do_select(self, conn) -> PostgRESTResponse:
        where, params = self._build_where()

        # Parse columns: may include nested foreign table selects like:
        #   "team_id, role, joined_at, teams(*)"
        #   "*, user_profiles!user_id(display_name, avatar_url)"
        #   "*, teams(id, name, slug), user_profiles!invited_by(id, display_name)"
        select_parts, join_specs = _parse_select_columns(self._columns)

        # Build base SELECT (only columns from the main table)
        main_cols = ", ".join(select_parts) if select_parts else "*"
        sql = f"SELECT {main_cols} FROM {self._table}"

        # Add JOINs for nested foreign table selects
        join_clauses = []
        for i, (fk_col, fk_table, fk_cols) in enumerate(join_specs):
            alias = f"_j{i}"
            join_clauses.append(
                f" LEFT JOIN {fk_table} AS {alias} ON {self._table}.{fk_col} = {alias}.id"
            )

        sql += "".join(join_clauses)
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

        return PostgRESTResponse(
            data=[_serialize_row(r) for r in rows],
            count=count_val,
        )

    async def _do_insert(self, conn) -> PostgRESTResponse:
        payload = self._payload
        if isinstance(payload, list):
            if not payload:
                return PostgRESTResponse(data=[])
            cols = list(payload[0].keys())
        else:
            cols = list(payload.keys())

        col_list = ", ".join(cols)
        if isinstance(payload, list):
            all_vals = []
            for row in payload:
                all_vals.extend(row.get(c) for c in cols)
            ph = ", ".join(f"${i+1}" for i in range(len(cols) * len(payload)))
            sql = f"INSERT INTO {self._table} ({col_list}) VALUES ({ph}) RETURNING *"
            rows = await _fetch(conn, sql, all_vals)
        else:
            vals = [payload[c] for c in cols]
            ph = ", ".join(f"${i+1}" for i in range(len(cols)))
            sql = f"INSERT INTO {self._table} ({col_list}) VALUES ({ph}) RETURNING *"
            rows = await _fetch(conn, sql, vals)

        return PostgRESTResponse(data=[_serialize_row(r) for r in rows])

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
            keys = list(self._params.keys())
            placeholders = ", ".join(f"${i+1}" for i in range(len(keys)))
            vals = [self._params[k] for k in keys]
            sql = f"SELECT * FROM {self._func}({placeholders})"
            rows = await _fetch(conn, sql, vals)
            return PostgRESTResponse(data=[_serialize_row(r) for r in rows])


# ---------------------------------------------------------------------------
# Storage — MinIO/S3 via boto3
# ---------------------------------------------------------------------------

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

    def get_public_url(self, path: str) -> str:
        return f"{settings.s3_endpoint}/{self._bucket}/{path}"


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
