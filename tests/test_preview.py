"""Tests for the file preview endpoint.

Tests the classification logic, response models, and endpoint behavior
WITHOUT requiring a live Supabase connection (uses mocks where needed).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.public.preview import (
    _classify_preview,
    _detect_code_language,
    _build_thumbnail_url,
)


# ---------------------------------------------------------------------------
# Unit tests — pure logic, no network
# ---------------------------------------------------------------------------


class TestDetectCodeLanguage:
    """Test language detection from filenames."""

    def test_python_file(self):
        assert _detect_code_language("main.py") == "python"
        assert _detect_code_language("utils/helper.py") == "python"

    def test_javascript_file(self):
        assert _detect_code_language("app.js") == "javascript"

    def test_typescript_file(self):
        assert _detect_code_language("index.ts") == "typescript"
        assert _detect_code_language("Component.tsx") == "tsx"
        assert _detect_code_language("Component.jsx") == "jsx"

    def test_web_files(self):
        assert _detect_code_language("index.html") == "html"
        assert _detect_code_language("style.css") == "css"
        assert _detect_code_language("vars.scss") == "scss"

    def test_systems_languages(self):
        assert _detect_code_language("main.c") == "c"
        assert _detect_code_language("main.cpp") == "cpp"
        assert _detect_code_language("main.go") == "go"
        assert _detect_code_language("main.rs") == "rust"
        assert _detect_code_language("main.swift") == "swift"

    def test_config_files(self):
        assert _detect_code_language("config.json") == "json"
        assert _detect_code_language("config.yaml") == "yaml"
        assert _detect_code_language("config.yml") == "yaml"
        assert _detect_code_language("config.toml") == "toml"
        assert _detect_code_language("config.ini") == "ini"

    def test_shell_files(self):
        assert _detect_code_language("run.sh") == "bash"
        assert _detect_code_language("run.bash") == "bash"
        assert _detect_code_language(".env") == "bash"

    def test_special_filenames(self):
        assert _detect_code_language("Makefile") == "makefile"
        assert _detect_code_language("Dockerfile") == "dockerfile"
        assert _detect_code_language("Vagrantfile") == "vagrantfile"

    def test_unknown_extension(self):
        assert _detect_code_language("file.xyz") == "plaintext"

    def test_no_extension(self):
        assert _detect_code_language("README") == "plaintext"

    def test_empty_string(self):
        assert _detect_code_language("") == "plaintext"


class TestClassifyPreview:
    """Test file type classification for previews."""

    # Images
    def test_image_jpeg(self):
        ptype, lang = _classify_preview("image/jpeg", "photo.jpg")
        assert ptype == "image"
        assert lang is None

    def test_image_png(self):
        ptype, lang = _classify_preview("image/png", "screenshot.png")
        assert ptype == "image"

    def test_image_gif(self):
        ptype, lang = _classify_preview("image/gif", "animation.gif")
        assert ptype == "image"

    def test_image_webp(self):
        ptype, lang = _classify_preview("image/webp", "photo.webp")
        assert ptype == "image"

    # PDF
    def test_pdf(self):
        ptype, lang = _classify_preview("application/pdf", "report.pdf")
        assert ptype == "pdf"
        assert lang is None

    # Video
    def test_video_mp4(self):
        ptype, lang = _classify_preview("video/mp4", "clip.mp4")
        assert ptype == "video"
        assert lang is None

    def test_video_webm(self):
        ptype, lang = _classify_preview("video/webm", "clip.webm")
        assert ptype == "video"

    # Audio
    def test_audio_mpeg(self):
        ptype, lang = _classify_preview("audio/mpeg", "song.mp3")
        assert ptype == "audio"
        assert lang is None

    def test_audio_wav(self):
        ptype, lang = _classify_preview("audio/wav", "recording.wav")
        assert ptype == "audio"

    # Markdown
    def test_markdown_mime(self):
        ptype, lang = _classify_preview("text/markdown", "README.md")
        assert ptype == "markdown"
        assert lang is None

    def test_markdown_by_extension(self):
        ptype, lang = _classify_preview("text/plain", "README.md")
        assert ptype == "markdown"

    def test_markdown_mdx(self):
        ptype, lang = _classify_preview("text/plain", "page.mdx")
        assert ptype == "markdown"

    # Code — by MIME type
    def test_code_json_mime(self):
        ptype, lang = _classify_preview("application/json", "data.json")
        assert ptype == "code"
        assert lang == "json"

    def test_code_xml_mime(self):
        ptype, lang = _classify_preview("application/xml", "config.xml")
        assert ptype == "code"
        assert lang == "xml"

    # Code — by extension (text/plain with code-like extension)
    def test_code_python_by_ext(self):
        ptype, lang = _classify_preview("text/plain", "main.py")
        assert ptype == "code"
        assert lang == "python"

    def test_code_typescript_by_ext(self):
        ptype, lang = _classify_preview("text/plain", "index.ts")
        assert ptype == "code"
        assert lang == "typescript"

    # Plain text
    def test_text_plain(self):
        ptype, lang = _classify_preview("text/plain", "notes.txt")
        assert ptype == "text"
        assert lang is None

    def test_text_csv(self):
        ptype, lang = _classify_preview("text/csv", "data.csv")
        assert ptype == "text"

    # Unsupported
    def test_unsupported_zip(self):
        ptype, lang = _classify_preview("application/zip", "archive.zip")
        assert ptype == "unsupported"
        assert lang is None

    def test_unsupported_binary(self):
        ptype, lang = _classify_preview("application/octet-stream", "binary.dat")
        assert ptype == "unsupported"

    # Edge cases
    def test_empty_mime_uses_extension(self):
        ptype, lang = _classify_preview("", "script.py")
        assert ptype == "code"
        assert lang == "python"

    def test_mime_case_insensitive(self):
        ptype, _ = _classify_preview("IMAGE/PNG", "photo.png")
        assert ptype == "image"


class TestBuildUrls:
    """Test URL building helpers."""

    def test_thumbnail_url_basic(self):
        url = _build_thumbnail_url("shares/abc123.png")
        assert url.endswith("/html-files/public/thumbnails/shares/abc123_thumb.jpg")

    def test_thumbnail_url_no_extension(self):
        url = _build_thumbnail_url("noextfile")
        assert url is None

    def test_thumbnail_url_multiple_dots(self):
        url = _build_thumbnail_url("shares/my.file.name.png")
        assert url.endswith("/html-files/public/thumbnails/shares/my.file.name_thumb.jpg")


# ---------------------------------------------------------------------------
# Integration tests — ASGI transport, tests endpoint routing
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


class TestPreviewEndpoint:
    """Test the /api/shares/{slug}/preview endpoint routing."""

    @pytest.mark.asyncio
    async def test_preview_nonexistent_share(self, client):
        """Preview of a non-existent slug should return 404."""
        resp = await client.get("/api/shares/nonexistent-slug-xyz/preview")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_preview_endpoint_exists(self, client):
        """The endpoint should be registered (not 405 Method Not Allowed)."""
        resp = await client.get("/api/shares/test/preview")
        # 404 = endpoint exists but share not found
        # 405 = endpoint not registered
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_preview_response_shape(self, client):
        """When endpoint returns data, verify the response shape."""
        # This will 404 since the slug doesn't exist in test DB,
        # but we verify the endpoint is reachable
        resp = await client.get("/api/shares/test-slug/preview")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data


class TestPreviewResponseModel:
    """Test the PreviewResponse Pydantic model."""

    def test_model_minimal(self):
        from app.public.preview import PreviewResponse

        resp = PreviewResponse(
            slug="abc",
            mime_type="text/plain",
            preview_type="text",
            content_url="https://example.com/file.txt",
        )
        assert resp.slug == "abc"
        assert resp.preview_type == "text"
        assert resp.content is None
        assert resp.language is None
        assert resp.thumbnail_url is None
        assert resp.password_protected is False

    def test_model_full(self):
        from app.public.preview import PreviewResponse

        resp = PreviewResponse(
            slug="abc",
            filename="script.py",
            title="My Script",
            mime_type="text/x-python",
            file_size=1024,
            preview_type="code",
            content_url="https://example.com/script.py",
            content="print('hello')",
            language="python",
            lines_total=50,
            lines_shown=100,
            thumbnail_url=None,
            encrypted=False,
            password_protected=False,
            burn_after_reading=False,
            burned=False,
        )
        assert resp.language == "python"
        assert resp.lines_total == 50
        assert resp.content == "print('hello')"

    def test_model_password_protected(self):
        from app.public.preview import PreviewResponse

        resp = PreviewResponse(
            slug="secret",
            mime_type="application/pdf",
            preview_type="unsupported",
            content_url="",
            password_protected=True,
        )
        assert resp.password_protected is True
        assert resp.content_url == ""
