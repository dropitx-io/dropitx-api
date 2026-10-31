"""Live-DB tests: column constraints in infra/init that code relies on."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from core.supabase import get_admin_client


def _new_share(**fields) -> dict:
    return {"slug": f"sd-{uuid.uuid4().hex[:12]}", "filename": "a.md", **fields}


def test_share_is_not_private_unless_said_so():
    db = get_admin_client()
    row = db.table("shares").insert(_new_share()).execute().data[0]
    try:
        assert row["is_private"] is False
    finally:
        db.table("shares").delete().eq("id", row["id"]).execute()


def test_share_privacy_cannot_be_null():
    db = get_admin_client()
    slug_row = _new_share(is_private=None)

    with pytest.raises(asyncpg.NotNullViolationError):
        db.table("shares").insert(slug_row).execute()

    assert db.table("shares").select("id").eq("slug", slug_row["slug"]).execute().data == []
