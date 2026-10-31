"""Shared fixtures and helpers for the live-DB and endpoint tests."""

from __future__ import annotations

import uuid

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


def act_as(user: User | None) -> None:
    """Authenticate every request as `user` (None = anonymous)."""
    app.dependency_overrides.clear()
    if user is None:
        app.dependency_overrides[get_optional_user] = lambda: None
        return
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def walk_keys(node):
    """Yield every dict key found anywhere in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


class Seed:
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
    s = Seed()
    yield s
    s.cleanup()


def unique_ip() -> dict:
    """Own rate-limit bucket per call (CF-Connecting-IP is the trusted header)."""
    return {"cf-connecting-ip": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}
