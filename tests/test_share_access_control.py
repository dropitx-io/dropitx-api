"""Live-DB tests: who may read a share, and what the team listing exposes.

Runs against the real Postgres + MinIO from CI. Only authentication is
overridden (dependency_overrides for get_current_user / get_optional_user);
the share rows, storage objects, team membership and queries are real.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from tests.conftest import PRIVATE_BODY, PUBLIC_BODY, SECRET_KEYS, act_as, unique_ip, walk_keys


@pytest.fixture
def missing_share_body(client):
    act_as(None)
    resp = client.get(f"/api/shares/does-not-exist-{uuid.uuid4().hex}/content")
    assert resp.status_code == 404
    return resp.json()


# ---------------------------------------------------------------------------
# Private shares: content and preview
# ---------------------------------------------------------------------------

class TestPrivateShareContent:
    def test_anonymous_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body
        assert PRIVATE_BODY not in resp.text

    def test_owner_reads_private_content(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PRIVATE_BODY
        assert resp.json()["is_private"] is True

    def test_non_owner_user_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_team_member_gets_404_for_private_content(self, client, seed, missing_share_body):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(owner)
        seed.team_with_share(teammate, share)
        act_as(teammate)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_burned_private_share_is_404_not_410_for_anonymous(self, client, seed, missing_share_body):
        share = seed.share(seed.user(), burned=True)
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_public_share_content_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PUBLIC_BODY


class TestPrivateSharePreview:
    def test_anonymous_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_non_owner_user_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_previews_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 200
        assert resp.json()["slug"] == share["slug"]

    def test_public_share_preview_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        act_as(None)

        assert client.get(f"/api/shares/{share['slug']}/preview").status_code == 200


# ---------------------------------------------------------------------------
# Private shares: the other two routes that hand out the content
# ---------------------------------------------------------------------------

class TestPrivateShareDownloadAndUnlock:
    def test_anonymous_gets_404_for_private_download(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_downloads_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 200
        assert resp.text == PRIVATE_BODY

    def test_non_owner_gets_404_for_private_unlock(self, client, seed, missing_share_body):
        from core.security import hash_password

        share = seed.share(seed.user(), password_hash=hash_password("hunter2"))
        act_as(seed.user())

        resp = client.post(f"/api/shares/{share['slug']}/unlock", json={"password": "hunter2"})

        assert resp.status_code == 404
        assert resp.json() == missing_share_body
        assert PRIVATE_BODY not in resp.text


# ---------------------------------------------------------------------------
# Team shares listing never exposes secrets
# ---------------------------------------------------------------------------

class TestTeamSharesListing:
    def test_member_listing_has_no_secrets_and_reports_has_password(self, client, seed):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(
            owner, password_hash="$2b$12$fixturehashfixturehashfixtur", is_private=False
        )
        team_slug = seed.team_with_share(teammate, share)
        act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert not SECRET_KEYS & set(walk_keys(items))
        assert share["delete_token"] not in resp.text
        assert "fixturehash" not in resp.text

        nested = items[0]["shares"]
        assert nested["has_password"] is True
        assert nested["id"] == share["id"]
        assert nested["slug"] == share["slug"]
        assert nested["filename"] == share["filename"]
        assert nested["user_id"] == owner.id
        assert nested["is_private"] is False
        for field in ("title", "mime_type", "view_count", "created_at", "expires_at",
                      "burn_after_reading", "encrypted"):
            assert field in nested

    def test_listing_reports_has_password_false_when_unprotected(self, client, seed):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(owner, is_private=False)
        team_slug = seed.team_with_share(teammate, share)
        act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        assert resp.json()[0]["shares"]["has_password"] is False


# ---------------------------------------------------------------------------
# CLI / multi uploads must keep password shares readable by their recipients
# ---------------------------------------------------------------------------

class TestUploadsStayReadable:
    def test_cli_file_upload_with_password_still_unlocks(self, client, seed):
        act_as(None)
        up = client.post(
            "/api/cli/upload",
            files={"file": ("note.md", b"# cli secret", "text/markdown")},
            data={"password": "pw-cli"},
            headers=unique_ip(),
        )
        assert up.status_code == 200, up.text
        slug = up.json()["slug"]
        row = seed.adopt(slug)

        gate = client.get(f"/api/shares/{slug}/content")
        assert gate.status_code == 200
        assert gate.json()["password_protected"] is True
        assert gate.json()["content"] == ""

        unlocked = client.post(f"/api/shares/{slug}/unlock", json={"password": "pw-cli"})
        assert unlocked.status_code == 200
        assert unlocked.json()["content"] == "# cli secret"
        assert row["is_private"] is False

    def test_cli_text_upload_with_password_still_unlocks(self, client, seed):
        act_as(None)
        up = client.post(
            "/api/cli/upload/text",
            data={"content": "cli text secret", "password": "pw-text"},
            headers=unique_ip(),
        )
        assert up.status_code == 200, up.text
        slug = up.json()["slug"]
        row = seed.adopt(slug)

        gate = client.get(f"/api/shares/{slug}/content")
        assert gate.status_code == 200
        assert gate.json()["password_protected"] is True

        unlocked = client.post(f"/api/shares/{slug}/unlock", json={"password": "pw-text"})
        assert unlocked.status_code == 200
        assert unlocked.json()["content"] == "cli text secret"
        assert row["is_private"] is False

    def test_anonymous_multi_upload_cannot_be_private(self, client):
        act_as(None)
        resp = client.post(
            "/api/upload/multi",
            files=[("files", ("a.html", b"<p>a</p>", "text/html"))],
            data={"is_private": "true"},
            headers=unique_ip(),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Private shares require sign-in"

    def test_signed_in_private_multi_upload_is_readable_by_owner_only(self, client, seed):
        owner = seed.user()
        act_as(owner)
        up = client.post(
            "/api/upload/multi",
            files=[("files", ("a.html", b"<p>a</p>", "text/html"))],
            data={"is_private": "true"},
            headers=unique_ip(),
        )
        assert up.status_code == 200, up.text
        slug = up.json()["slug"]
        seed.adopt(slug)

        assert client.get(f"/api/shares/{slug}/content").status_code == 200
        act_as(None)
        assert client.get(f"/api/shares/{slug}/content").status_code == 404


# ---------------------------------------------------------------------------
# Group ZIP download
# ---------------------------------------------------------------------------

def _zip_names(resp) -> set[str]:
    return set(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())


class TestGroupZipDownload:
    def _group(self, seed, owner):
        from core.security import hash_password

        group = seed.group(owner)
        shares = {
            "public": seed.share(owner, is_private=False, group_id=group),
            "private": seed.share(owner, is_private=True, group_id=group),
            "password": seed.share(
                owner, is_private=False, group_id=group, password_hash=hash_password("pw")
            ),
        }
        return group, shares

    def test_anonymous_zip_contains_only_open_shares(self, client, seed):
        owner = seed.user()
        group, shares = self._group(seed, owner)
        act_as(None)

        resp = client.get(f"/api/download/group/{group}", headers=unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {shares["public"]["filename"]}

    def test_non_owner_zip_contains_only_open_shares(self, client, seed):
        group, shares = self._group(seed, seed.user())
        act_as(seed.user())

        resp = client.get(f"/api/download/group/{group}", headers=unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {shares["public"]["filename"]}

    def test_owner_zip_contains_everything(self, client, seed):
        owner = seed.user()
        group, shares = self._group(seed, owner)
        act_as(owner)

        resp = client.get(f"/api/download/group/{group}", headers=unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {s["filename"] for s in shares.values()}

    def test_group_with_only_hidden_shares_looks_empty(self, client, seed):
        owner = seed.user()
        group = seed.group(owner)
        seed.share(owner, is_private=True, group_id=group)
        empty = seed.group(owner)
        act_as(None)

        hidden = client.get(f"/api/download/group/{group}", headers=unique_ip())
        nothing = client.get(f"/api/download/group/{empty}", headers=unique_ip())

        assert hidden.status_code == 404
        assert hidden.json() == nothing.json()


# ---------------------------------------------------------------------------
# Multi-file listing
# ---------------------------------------------------------------------------

class TestShareFilesListing:
    def test_anonymous_gets_404_for_private_share_files(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        seed.file_row(share, "a.html")
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_non_owner_gets_404_for_private_share_files(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        seed.file_row(share, "a.html")
        act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_lists_files_without_storage_paths(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        seed.file_row(share, "a.html")
        act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert [f["filename"] for f in files] == ["a.html"]
        assert "storage_path" not in set(walk_keys(resp.json()))

    def test_public_share_files_are_listed_without_storage_paths(self, client, seed):
        share = seed.share(seed.user(), is_private=False)
        seed.file_row(share, "b.html")
        act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 200
        assert [f["filename"] for f in resp.json()["files"]] == ["b.html"]
        assert "storage_path" not in set(walk_keys(resp.json()))
