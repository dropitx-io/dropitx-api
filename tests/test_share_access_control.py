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
from fastapi.testclient import TestClient

from app.dependencies import User, get_current_user, get_optional_user
from app.main import app
from core.supabase import get_admin_client

SECRET_KEYS = {"password_hash", "delete_token"}
PRIVATE_BODY = "<h1>private body</h1>"
PUBLIC_BODY = "<h1>public body</h1>"


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _act_as(user: User | None) -> None:
    """Authenticate every request as `user` (None = anonymous)."""
    app.dependency_overrides.clear()
    if user is None:
        app.dependency_overrides[get_optional_user] = lambda: None
        return
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def _walk_keys(node):
    """Yield every dict key found anywhere in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


class _Seed:
    """Rows created by one test, removed on teardown."""

    def __init__(self):
        self.db = get_admin_client()
        self.users: list[str] = []
        self.shares: list[str] = []
        self.teams: list[str] = []
        self.objects: list[str] = []
        self.groups: list[str] = []

    def user(self) -> User:
        uid = f"acl-{uuid.uuid4().hex}"
        self.db.table("auth.users").insert({"id": uid, "email": f"{uid}@example.com"}).execute()
        self.users.append(uid)
        return User(id=uid, email=f"{uid}@example.com")

    def share(self, owner: User, *, body: str = PRIVATE_BODY, **overrides) -> dict:
        slug = f"acl-{uuid.uuid4().hex[:12]}"
        path = f"shares/{slug}.html"
        self.db.storage.from_("html-files").upload(
            path, body.encode(), file_options={"content-type": "text/html"}
        )
        self.objects.append(path)
        row = {
            "slug": slug,
            "title": "ACL fixture",
            "filename": f"{slug}.html",
            "storage_path": path,
            "mime_type": "text/html",
            "source": "upload",
            "user_id": owner.id,
            "is_private": True,
            "delete_token": f"tok-{uuid.uuid4().hex}",
        }
        row.update(overrides)
        created = self.db.table("shares").insert(row).execute().data[0]
        self.shares.append(created["id"])
        return created

    def team_with_share(self, member: User, share: dict) -> str:
        slug = f"acl-team-{uuid.uuid4().hex[:10]}"
        team = self.db.table("teams").insert(
            {"name": "ACL team", "slug": slug, "owner_id": share["user_id"]}
        ).execute().data[0]
        self.teams.append(team["id"])
        self.db.table("team_members").insert(
            {"team_id": team["id"], "user_id": member.id, "role": "viewer"}
        ).execute()
        self.db.table("team_shares").insert(
            {"team_id": team["id"], "share_id": share["id"], "shared_by": share["user_id"]}
        ).execute()
        return slug

    def adopt(self, slug: str) -> dict:
        """Track a share created through the API so cleanup removes it."""
        row = self.db.table("shares").select("*").eq("slug", slug).execute().data[0]
        self.shares.append(row["id"])
        if row.get("storage_path"):
            self.objects.append(row["storage_path"])
        return row

    def group(self, owner: User) -> str:
        slug = f"acl-group-{uuid.uuid4().hex[:10]}"
        self.db.table("share_groups").insert({"slug": slug, "user_id": owner.id}).execute()
        self.groups.append(slug)
        return slug

    def file_row(self, share: dict, filename: str) -> dict:
        return self.db.table("share_files").insert({
            "share_id": share["id"],
            "storage_path": f"shares/{share['slug']}-{filename}",
            "filename": filename,
            "mime_type": "text/html",
            "file_size": 5,
            "sort_order": 0,
        }).execute().data[0]

    def cleanup(self):
        for team_id in self.teams:
            self.db.table("teams").delete().eq("id", team_id).execute()
        for share_id in self.shares:
            self.db.table("shares").delete().eq("id", share_id).execute()
        if self.objects:
            self.db.storage.from_("html-files").remove(self.objects)
        for slug in self.groups:
            self.db.table("share_groups").delete().eq("slug", slug).execute()
        for uid in self.users:
            self.db.table("auth.users").delete().eq("id", uid).execute()


@pytest.fixture
def seed():
    s = _Seed()
    yield s
    s.cleanup()


@pytest.fixture
def missing_share_body(client):
    _act_as(None)
    resp = client.get(f"/api/shares/does-not-exist-{uuid.uuid4().hex}/content")
    assert resp.status_code == 404
    return resp.json()


# ---------------------------------------------------------------------------
# Private shares: content and preview
# ---------------------------------------------------------------------------

class TestPrivateShareContent:
    def test_anonymous_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body
        assert PRIVATE_BODY not in resp.text

    def test_owner_reads_private_content(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PRIVATE_BODY
        assert resp.json()["is_private"] is True

    def test_non_owner_user_gets_404_for_private_content(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_team_member_gets_404_for_private_content(self, client, seed, missing_share_body):
        owner, teammate = seed.user(), seed.user()
        share = seed.share(owner)
        seed.team_with_share(teammate, share)
        _act_as(teammate)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_burned_private_share_is_404_not_410_for_anonymous(self, client, seed, missing_share_body):
        share = seed.share(seed.user(), burned=True)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_public_share_content_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/content")

        assert resp.status_code == 200
        assert resp.json()["content"] == PUBLIC_BODY


class TestPrivateSharePreview:
    def test_anonymous_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_non_owner_user_gets_404_for_private_preview(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_previews_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/preview")

        assert resp.status_code == 200
        assert resp.json()["slug"] == share["slug"]

    def test_public_share_preview_stays_anonymous(self, client, seed):
        share = seed.share(seed.user(), body=PUBLIC_BODY, is_private=False)
        _act_as(None)

        assert client.get(f"/api/shares/{share['slug']}/preview").status_code == 200


# ---------------------------------------------------------------------------
# Private shares: the other two routes that hand out the content
# ---------------------------------------------------------------------------

class TestPrivateShareDownloadAndUnlock:
    def test_anonymous_gets_404_for_private_download(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_downloads_private_share(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/download")

        assert resp.status_code == 200
        assert resp.text == PRIVATE_BODY

    def test_non_owner_gets_404_for_private_unlock(self, client, seed, missing_share_body):
        from core.security import hash_password

        share = seed.share(seed.user(), password_hash=hash_password("hunter2"))
        _act_as(seed.user())

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
        _act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert not SECRET_KEYS & set(_walk_keys(items))
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
        _act_as(teammate)

        resp = client.get(f"/api/dashboard/teams/{team_slug}/shares")

        assert resp.status_code == 200
        assert resp.json()[0]["shares"]["has_password"] is False


def _unique_ip() -> dict:
    """Own rate-limit bucket per call (CF-Connecting-IP is the trusted header)."""
    return {"cf-connecting-ip": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}


# ---------------------------------------------------------------------------
# CLI / multi uploads must keep password shares readable by their recipients
# ---------------------------------------------------------------------------

class TestUploadsStayReadable:
    def test_cli_file_upload_with_password_still_unlocks(self, client, seed):
        _act_as(None)
        up = client.post(
            "/api/cli/upload",
            files={"file": ("note.md", b"# cli secret", "text/markdown")},
            data={"password": "pw-cli"},
            headers=_unique_ip(),
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
        _act_as(None)
        up = client.post(
            "/api/cli/upload/text",
            data={"content": "cli text secret", "password": "pw-text"},
            headers=_unique_ip(),
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
        _act_as(None)
        resp = client.post(
            "/api/upload/multi",
            files=[("files", ("a.html", b"<p>a</p>", "text/html"))],
            data={"is_private": "true"},
            headers=_unique_ip(),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Private shares require sign-in"

    def test_signed_in_private_multi_upload_is_readable_by_owner_only(self, client, seed):
        owner = seed.user()
        _act_as(owner)
        up = client.post(
            "/api/upload/multi",
            files=[("files", ("a.html", b"<p>a</p>", "text/html"))],
            data={"is_private": "true"},
            headers=_unique_ip(),
        )
        assert up.status_code == 200, up.text
        slug = up.json()["slug"]
        seed.adopt(slug)

        assert client.get(f"/api/shares/{slug}/content").status_code == 200
        _act_as(None)
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
        _act_as(None)

        resp = client.get(f"/api/download/group/{group}", headers=_unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {shares["public"]["filename"]}

    def test_non_owner_zip_contains_only_open_shares(self, client, seed):
        group, shares = self._group(seed, seed.user())
        _act_as(seed.user())

        resp = client.get(f"/api/download/group/{group}", headers=_unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {shares["public"]["filename"]}

    def test_owner_zip_contains_everything(self, client, seed):
        owner = seed.user()
        group, shares = self._group(seed, owner)
        _act_as(owner)

        resp = client.get(f"/api/download/group/{group}", headers=_unique_ip())

        assert resp.status_code == 200
        assert _zip_names(resp) == {s["filename"] for s in shares.values()}

    def test_group_with_only_hidden_shares_looks_empty(self, client, seed):
        owner = seed.user()
        group = seed.group(owner)
        seed.share(owner, is_private=True, group_id=group)
        empty = seed.group(owner)
        _act_as(None)

        hidden = client.get(f"/api/download/group/{group}", headers=_unique_ip())
        nothing = client.get(f"/api/download/group/{empty}", headers=_unique_ip())

        assert hidden.status_code == 404
        assert hidden.json() == nothing.json()


# ---------------------------------------------------------------------------
# Multi-file listing
# ---------------------------------------------------------------------------

class TestShareFilesListing:
    def test_anonymous_gets_404_for_private_share_files(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        seed.file_row(share, "a.html")
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_non_owner_gets_404_for_private_share_files(self, client, seed, missing_share_body):
        share = seed.share(seed.user())
        seed.file_row(share, "a.html")
        _act_as(seed.user())

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 404
        assert resp.json() == missing_share_body

    def test_owner_lists_files_without_storage_paths(self, client, seed):
        owner = seed.user()
        share = seed.share(owner)
        seed.file_row(share, "a.html")
        _act_as(owner)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert [f["filename"] for f in files] == ["a.html"]
        assert "storage_path" not in set(_walk_keys(resp.json()))

    def test_public_share_files_are_listed_without_storage_paths(self, client, seed):
        share = seed.share(seed.user(), is_private=False)
        seed.file_row(share, "b.html")
        _act_as(None)

        resp = client.get(f"/api/shares/{share['slug']}/files")

        assert resp.status_code == 200
        assert [f["filename"] for f in resp.json()["files"]] == ["b.html"]
        assert "storage_path" not in set(_walk_keys(resp.json()))
