"""Live-DB test: concurrent first use of the DB shim starts one loop and one pool.

Runs against the real Postgres from CI. The module globals are reset to a cold
start for the test and restored afterwards, so no second loop or pool outlives it.
"""

from __future__ import annotations

import threading

import pytest

import core.db as db

_GLOBALS = ("_loop", "_loop_thread", "_pool", "_pool_lock")


@pytest.fixture
def cold_start():
    """Reset the shim to its never-used state; tear down whatever the test started."""
    saved = {name: getattr(db, name, None) for name in _GLOBALS}
    for name in _GLOBALS:
        setattr(db, name, None)
    try:
        yield
    finally:
        started_loop, started_thread, started_pool = db._loop, db._loop_thread, db._pool
        if started_pool is not None and started_loop is not None and started_loop.is_running():
            db._run_async(started_pool.close())
        if started_loop is not None and started_loop.is_running():
            started_loop.call_soon_threadsafe(started_loop.stop)
        if started_thread is not None:
            started_thread.join(timeout=5)
        for name, value in saved.items():
            setattr(db, name, value)


def test_concurrent_first_use_shares_one_loop_and_one_pool(cold_start):
    workers = 8
    barrier = threading.Barrier(workers)
    pools: list = []
    errors: list = []

    async def get_pool():
        return await db._get_pool()

    def worker():
        try:
            barrier.wait()
            pools.append(db._run_async(get_pool()))
        except Exception as exc:  # surfaced by the assertion below
            errors.append(exc)

    before = set(threading.enumerate())
    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    loop_threads = [
        t for t in threading.enumerate() if t not in before and t.name == "db-event-loop"
    ]

    assert not errors
    assert len(pools) == workers
    assert len({id(pool) for pool in pools}) == 1
    assert len(loop_threads) == 1
