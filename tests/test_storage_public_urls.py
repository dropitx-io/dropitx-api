"""Public object URLs and private-by-default storage.

Runs against the real Postgres + MinIO from CI, whose bucket policy allows
anonymous download only on ``html-files/public``. Only authentication and the
upload rate limiter are replaced; every storage object and share row is real.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.dependencies import User, get_current_user, get_optional_user
from app.main import app
from core.config import Settings, settings
from core.db import public_object_url
from core.rate_limit import RateLimitResult
from core.supabase import get_admin_client

HTML = b"<h1>storage url fixture</h1>"


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _anonymous_get(url: str) -> httpx.Response:
    return httpx.get(url, timeout=10)


@pytest.fixture(autouse=True)
def _no_upload_rate_limit(monkeypatch):
    ok = RateLimitResult(success=True, limit=1000, remaining=1000, reset=0)
    for module in (
        "app.internal.upload",
        "app.internal.publish",
        "app.internal.multi_upload",
    ):
        monkeypatch.setattr(f"{module}.check_upload_rate_limit", lambda ip, _ok=ok: _ok)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def owner() -> User:
    uid = f"url-{uuid.uuid4().hex}"
    db = get_admin_client()
    db.table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
    user = User(id=uid, email=f"{uid}@example.com")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    yield user
    db.table("shares").delete().eq("user_id", uid).execute()
    db.table("auth.users").delete().eq("id", uid).execute()


@pytest.fixture
def objects():
    """Storage keys (in html-files) created by a test, removed afterwards."""
    keys: list[str] = []
    yield keys
    if keys:
        get_admin_client().storage.from_("html-files").remove(keys)


def _share_row(slug: str) -> dict:
    return get_admin_client().table("shares").select("*").eq("slug", slug).execute().data[0]


class TestPublicObjectUrl:
    def test_formats_bucket_and_key_under_storage_public_url(self, monkeypatch):
        monkeypatch.setattr(settings, "storage_public_url", "https://files.example.test/")
        assert (
            public_object_url("html-files", "public/uploads/u/a.png")
            == "https://files.example.test/html-files/public/uploads/u/a.png"
        )

    def test_default_points_at_local_minio_and_supabase_setting_is_gone(self, monkeypatch):
        monkeypatch.delenv("STORAGE_PUBLIC_URL", raising=False)
        assert Settings(_env_file=None).storage_public_url == "http://localhost:9000"
        assert "supabase_url" not in Settings.model_fields


class TestImageUpload:
    def test_image_is_stored_under_public_prefix_and_anonymously_readable(
        self, client, owner, objects
    ):
        resp = client.post(
            "/api/images/upload",
            files={"file": ("pic.png", _png_bytes(), "image/png")},
        )
        assert resp.status_code == 200, resp.text
        key = f"public/uploads/{owner.id}/pic.png"
        objects.append(key)
        body = resp.json()
        assert body["url"] == public_object_url("html-files", key)
        assert "storage/v1/object" not in body["url"]
        assert _anonymous_get(body["url"]).status_code == 200


class TestPrivateShareObjects:
    def test_password_protected_share_object_is_not_anonymously_readable(
        self, client, owner, objects
    ):
        resp = client.post(
            "/api/upload",
            files={"file": ("secret.html", HTML, "text/html")},
            data={"password": "hunter22"},
        )
        assert resp.status_code == 200, resp.text
        row = _share_row(resp.json()["slug"])
        objects.append(row["storage_path"])
        direct = _anonymous_get(f"{settings.s3_endpoint}/html-files/{row['storage_path']}")
        assert direct.status_code == 403

    def test_share_content_object_is_not_under_public_prefix(self, client, owner, objects):
        resp = client.post(
            "/api/upload", files={"file": ("a.html", HTML, "text/html")}
        )
        row = _share_row(resp.json()["slug"])
        objects.append(row["storage_path"])
        assert not row["storage_path"].startswith("public/")


class TestShareContentResponsesCarryNoStorageUrl:
    @staticmethod
    def _assert_share_page(url: str, slug: str):
        assert url == f"{settings.frontend_url.rstrip('/')}/s/{slug}"
        assert "storage/v1/object" not in url
        assert "html-files" not in url

    def test_upload(self, client, owner, objects):
        resp = client.post("/api/upload", files={"file": ("a.html", HTML, "text/html")})
        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        objects.append(_share_row(slug)["storage_path"])
        self._assert_share_page(resp.json()["url"], slug)

    def test_upload_batch(self, client, owner, objects):
        resp = client.post(
            "/api/upload/batch",
            files=[
                ("files", ("a.html", HTML, "text/html")),
                ("files", ("b.html", HTML, "text/html")),
            ],
        )
        assert resp.status_code == 200, resp.text
        for f in resp.json()["files"]:
            objects.append(_share_row(f["slug"])["storage_path"])
            self._assert_share_page(f["url"], f["slug"])

    def test_publish_and_republish(self, client, owner, objects):
        resp = client.post("/api/publish", json={"content": "<p>hi</p>"})
        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        objects.append(_share_row(slug)["storage_path"])
        self._assert_share_page(resp.json()["url"], slug)

        again = client.put(f"/api/publish/{slug}", json={"content": "<p>hi again</p>"})
        assert again.status_code == 200, again.text
        self._assert_share_page(again.json()["url"], slug)

    def test_multi_upload(self, client, owner, objects):
        resp = client.post(
            "/api/upload/multi",
            files=[("files", ("a.html", HTML, "text/html"))],
        )
        assert resp.status_code == 200, resp.text
        slug = resp.json()["slug"]
        for f in resp.json()["files"]:
            objects.append(f["storage_path"])
        self._assert_share_page(resp.json()["url"], slug)

    def test_preview_content_url(self, client, owner, objects):
        slug = client.post(
            "/api/upload", files={"file": ("a.html", HTML, "text/html")}
        ).json()["slug"]
        objects.append(_share_row(slug)["storage_path"])
        resp = client.get(f"/api/shares/{slug}/preview")
        assert resp.status_code == 200, resp.text
        self._assert_share_page(resp.json()["content_url"], slug)


class TestThumbnails:
    def test_thumbnail_is_stored_publicly_and_preview_links_to_it(self, client, owner, objects):
        from core.thumbnail import maybe_generate_thumbnail

        slug = client.post(
            "/api/upload", files={"file": ("p.png", _png_bytes(), "image/png")}
        ).json()["slug"]
        row = _share_row(slug)
        objects.append(row["storage_path"])
        base = row["storage_path"].rsplit(".", 1)[0]
        key = f"public/thumbnails/{base}_thumb.jpg"
        objects.append(key)

        url = asyncio.run(
            maybe_generate_thumbnail(_png_bytes(), "image/png", row["storage_path"])
        )
        assert url == public_object_url("html-files", key)
        assert _anonymous_get(url).status_code == 200

        preview = client.get(f"/api/shares/{slug}/preview").json()
        assert preview["thumbnail_url"] == url

    def test_no_thumbnail_is_made_for_a_password_protected_upload(self, client, owner, objects):
        with patch("core.thumbnail.maybe_generate_thumbnail", new=AsyncMock()) as gen:
            resp = client.post(
                "/api/upload",
                files={"file": ("p.png", _png_bytes(), "image/png")},
                data={"password": "hunter22"},
            )
            assert resp.status_code == 200, resp.text
            objects.append(_share_row(resp.json()["slug"])["storage_path"])
            gen.assert_not_called()

    def test_thumbnail_is_still_made_for_an_open_upload(self, client, owner, objects):
        with patch("core.thumbnail.maybe_generate_thumbnail", new=AsyncMock()) as gen:
            resp = client.post(
                "/api/upload", files={"file": ("p.png", _png_bytes(), "image/png")}
            )
            assert resp.status_code == 200, resp.text
            objects.append(_share_row(resp.json()["slug"])["storage_path"])
            gen.assert_called_once()


class TestOEmbed:
    def test_embed_url_is_frontend_embed_page(self, client, owner, objects):
        slug = client.post(
            "/api/upload", files={"file": ("a.html", HTML, "text/html")}
        ).json()["slug"]
        objects.append(_share_row(slug)["storage_path"])
        resp = client.get("/api/oembed", params={"url": f"https://dropitx.test/s/{slug}"})
        assert resp.status_code == 200, resp.text
        embed = f"{settings.frontend_url.rstrip('/')}/embed/{slug}"
        assert f'src="{embed}"' in resp.json()["html"]
        assert resp.json()["provider_url"] == settings.frontend_url.rstrip("/")
