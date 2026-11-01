"""Live-DB tests: editor publishes keep their content type through update and restore.

Markdown (language "markdown", or a filename ending .md) is stored and served as
text/markdown; everything else the editor publishes stays text/html.
"""

from __future__ import annotations

import pytest

from tests.conftest import act_as, unique_ip

MARKDOWN = "# Heading\n\nSome *markdown* text."


def _publish(client, seed, **body) -> dict:
    resp = client.post("/api/publish", json=body, headers=unique_ip())
    assert resp.status_code == 200, resp.text
    return seed.adopt(resp.json()["slug"])


def _object_type(seed, path: str) -> str:
    bucket = seed.db.storage.from_("html-files")
    return bucket._client().head_object(Bucket="html-files", Key=path)["ContentType"]


def _download_type(client, slug: str) -> str:
    resp = client.get(f"/api/shares/{slug}/download", headers=unique_ip())
    assert resp.status_code == 200, resp.text
    return resp.headers["content-type"].split(";")[0]


@pytest.mark.parametrize(
    "body",
    [
        {"content": MARKDOWN, "language": "markdown"},
        {"content": MARKDOWN, "filename": "notes.md"},
        {"content": MARKDOWN, "filename": "NOTES.MD"},
    ],
    ids=["language", "filename", "filename-uppercase"],
)
def test_markdown_publish_is_stored_and_served_as_markdown(client, seed, body):
    act_as(seed.user())

    row = _publish(client, seed, **body)

    assert row["mime_type"] == "text/markdown"
    assert row["filename"].lower().endswith(".md")
    assert _object_type(seed, row["storage_path"]).startswith("text/markdown")
    assert _download_type(client, row["slug"]) == "text/markdown"
    assert not row["content_text"].startswith("#")


def test_html_publish_stays_html(client, seed):
    act_as(seed.user())

    row = _publish(client, seed, content="<h1>Hello</h1>")

    assert row["mime_type"] == "text/html"
    assert row["filename"].endswith(".html")
    assert _object_type(seed, row["storage_path"]).startswith("text/html")
    assert _download_type(client, row["slug"]) == "text/html"


def test_updating_a_markdown_publish_keeps_it_markdown(client, seed):
    act_as(seed.user())
    row = _publish(client, seed, content=MARKDOWN, language="markdown")

    resp = client.put(f"/api/publish/{row['slug']}", json={"content": "# Second"}, headers=unique_ip())

    assert resp.status_code == 200, resp.text
    updated = seed.db.table("shares").select("*").eq("id", row["id"]).execute().data[0]
    assert updated["mime_type"] == "text/markdown"
    assert updated["content_text"] == "Second"
    assert _object_type(seed, row["storage_path"]).startswith("text/markdown")


def test_restoring_a_markdown_version_keeps_it_markdown(client, seed):
    act_as(seed.user())
    row = _publish(client, seed, content=MARKDOWN, language="markdown")
    client.put(f"/api/publish/{row['slug']}", json={"content": "# Second"}, headers=unique_ip())
    versions = seed.db.table("share_versions").select("*").eq("share_slug", row["slug"]).execute().data
    seed.objects.extend(v["storage_path"] for v in versions if v.get("storage_path"))

    resp = client.post(f"/api/shares/{row['slug']}/versions/1/restore")

    assert resp.status_code == 200, resp.text
    assert _object_type(seed, row["storage_path"]).startswith("text/markdown")
    assert _download_type(client, row["slug"]) == "text/markdown"
