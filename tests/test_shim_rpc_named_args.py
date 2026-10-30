"""Live-DB test: the shim binds RPC parameters by name, as PostgREST does."""

from __future__ import annotations

import uuid

import pytest

from core.db import _get_pool, _run_async
from core.supabase import get_admin_client


async def _ddl(sql: str):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)


@pytest.fixture
def joiner():
    name = f"shim_rpc_{uuid.uuid4().hex[:10]}"
    _run_async(_ddl(
        f"CREATE FUNCTION {name}(p_first text, p_second text, p_sep text DEFAULT '-') "
        f"RETURNS text LANGUAGE sql AS $$ SELECT p_first || p_sep || p_second $$"
    ))
    yield name
    _run_async(_ddl(f"DROP FUNCTION {name}(text, text, text)"))


def test_params_bind_by_name_not_dict_order(joiner):
    resp = get_admin_client().rpc(joiner, {"p_second": "b", "p_first": "a"}).execute()

    assert resp.data == [{joiner: "a-b"}]


def test_omitted_params_take_their_defaults(joiner):
    resp = get_admin_client().rpc(joiner, {"p_sep": "+", "p_second": "b", "p_first": "a"}).execute()
    assert resp.data == [{joiner: "a+b"}]

    resp = get_admin_client().rpc(joiner, {"p_first": "a", "p_second": "b"}).execute()
    assert resp.data == [{joiner: "a-b"}]


def test_no_params_calls_with_empty_argument_list():
    resp = get_admin_client().rpc("now", {}).execute()

    assert len(resp.data) == 1
