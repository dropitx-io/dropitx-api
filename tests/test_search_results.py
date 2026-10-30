"""Live-DB test: /api/search returns the public shares the search_shares RPC finds."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app
from core.supabase import get_admin_client


def test_search_returns_matching_public_share():
    db = get_admin_client()
    marker = f"needle{uuid.uuid4().hex}"
    slug = f"search-{uuid.uuid4().hex[:10]}"
    row = db.table("shares").insert({
        "slug": slug,
        "title": marker,
        "filename": f"{slug}.html",
        "storage_path": f"shares/{slug}.html",
        "mime_type": "text/html",
        "source": "upload",
        "is_private": False,
        "delete_token": f"tok-{uuid.uuid4().hex}",
    }).execute().data[0]
    try:
        resp = TestClient(app).get("/api/search", params={"q": marker})
    finally:
        db.table("shares").delete().eq("id", row["id"]).execute()

    assert resp.status_code == 200, resp.text
    assert [r["slug"] for r in resp.json()["results"]] == [slug]
