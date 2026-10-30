"""Live-DB tests: /api/search returns the public shares the search_shares RPC finds."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.supabase import get_admin_client


@pytest.fixture
def shares():
    """Insert public shares carrying a phrase; removed on teardown."""
    db = get_admin_client()
    ids: list[str] = []

    def make(phrase: str, **overrides) -> str:
        slug = f"search-{uuid.uuid4().hex[:10]}"
        row = {
            "slug": slug,
            "filename": f"{slug}.html",
            "storage_path": f"shares/{slug}.html",
            "mime_type": "text/html",
            "source": "upload",
            "is_private": False,
            "delete_token": f"tok-{uuid.uuid4().hex}",
            "content_text": phrase,
        }
        row.update(overrides)
        ids.append(db.table("shares").insert(row).execute().data[0]["id"])
        return slug

    yield make
    for share_id in ids:
        db.table("shares").delete().eq("id", share_id).execute()


def _search(phrase: str):
    return TestClient(app).get("/api/search", params={"q": phrase})


def test_search_returns_matching_public_share(shares):
    phrase = f"needle{uuid.uuid4().hex}"
    slug = shares(phrase)

    resp = _search(phrase)

    assert resp.status_code == 200, resp.text
    assert [r["slug"] for r in resp.json()["results"]] == [slug]


def test_search_does_not_reveal_password_protected_share_content(shares):
    phrase = f"needle{uuid.uuid4().hex}"
    shares(phrase, password_hash="not-a-real-hash")
    open_slug = shares(phrase)

    resp = _search(phrase)

    assert resp.status_code == 200, resp.text
    assert [r["slug"] for r in resp.json()["results"]] == [open_slug]
