"""Binary shares must stay readable: content is served base64-encoded."""

from __future__ import annotations

import base64
import uuid

from core.security import hash_password
from tests.conftest import act_as, unique_ip

PDF_BYTES = b"%PDF-1.4\n%\x93\x8f\x00\xff binary payload \x00\x01\x02"


def seed_pdf_share(seed, *, password: str | None = None) -> dict:
    """Insert a public PDF share whose bytes are not valid UTF-8."""
    owner = seed.user()
    slug = f"pdf-{uuid.uuid4().hex[:12]}"
    path = f"shares/{slug}.pdf"
    seed.db.storage.from_("html-files").upload(
        path, PDF_BYTES, file_options={"content-type": "application/pdf"}
    )
    seed.objects.append(path)
    row = {
        "slug": slug,
        "title": "CV",
        "filename": "cv.pdf",
        "storage_path": path,
        "mime_type": "application/pdf",
        "source": "upload",
        "user_id": owner.id,
        "is_private": False,
        "delete_token": f"tok-{uuid.uuid4().hex}",
    }
    if password:
        row["password_hash"] = hash_password(password)
    created = seed.db.table("shares").insert(row).execute().data[0]
    seed.shares.append(created["id"])
    return created


class TestBinaryShareContent:
    def test_public_binary_share_returns_base64(self, client, seed):
        share = seed_pdf_share(seed)
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip())

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("encoding") == "base64"
        assert base64.b64decode(body["content"]) == PDF_BYTES

    def test_text_share_content_stays_utf8(self, client, seed):
        share = seed.share(seed.user(), body="<h1>hello</h1>", is_private=False)
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content", headers=unique_ip())

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("encoding") == "utf8"
        assert body["content"] == "<h1>hello</h1>"

    def test_unlock_binary_share_returns_base64(self, client, seed):
        share = seed_pdf_share(seed, password="s3cret-pass")
        act_as(None)

        resp = client.post(
            f"/api/shares/{share['slug']}/unlock",
            json={"password": "s3cret-pass"},
            headers=unique_ip(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("encoding") == "base64"
        assert base64.b64decode(body["content"]) == PDF_BYTES
