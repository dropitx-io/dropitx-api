"""Live-DB tests: GET /api/u/{username} and /api/u/{username}/shares return only public data.

A profile is reachable once it has a username and its owner made it public. Its
share list holds the owner's open shares only: no private, password-protected,
burned, expired, burn-after-reading or one-time-download shares.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from core.security import hash_password
from tests.conftest import act_as, unique_ip, walk_keys


def _profile(seed, *, is_public=True, **fields):
    user = seed.user()
    username = f"pp-{uuid.uuid4().hex[:10]}"
    seed.db.table("user_profiles").insert({
        "user_id": user.id, "username": username, "is_public": is_public,
        "display_name": "Public Person", "bio": "hello", **fields,
    }).execute()
    return user, username


def _ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_public_profile_has_no_private_fields(client, seed):
    user, username = _profile(seed)
    act_as(None)

    resp = client.get(f"/api/u/{username}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == username
    assert body["display_name"] == "Public Person"
    assert user.email not in resp.text
    assert user.id not in resp.text
    assert not {"email", "user_id", "is_public"} & set(walk_keys(body))


def test_lookup_ignores_case(client, seed):
    _, username = _profile(seed)

    assert client.get(f"/api/u/{username.upper()}").status_code == 200


def test_a_profile_that_is_not_public_is_404(client, seed):
    _, username = _profile(seed, is_public=False)

    assert client.get(f"/api/u/{username}").status_code == 404
    assert client.get(f"/api/u/{username}/shares").status_code == 404


def test_share_list_and_stats_hold_only_open_shares(client, seed):
    user, username = _profile(seed)
    open_share = seed.share(user, is_private=False, view_count=7, created_at=_ago(1))
    older_open = seed.share(user, is_private=False, view_count=3, created_at=_ago(2))
    hidden = [
        seed.share(user, is_private=True),
        seed.share(user, is_private=False, password_hash=hash_password("pw")),
        seed.share(user, is_private=False, burned=True),
        seed.share(user, is_private=False, expires_at=_ago(1)),
        seed.share(user, is_private=False, burn_after_reading=True),
        seed.share(user, is_private=False, one_time_download=True),
    ]
    seed.db.table("share_stars").insert({"share_id": open_share["id"], "user_id": user.id}).execute()
    act_as(None)

    shares = client.get(f"/api/u/{username}/shares", headers=unique_ip())
    profile = client.get(f"/api/u/{username}", headers=unique_ip())

    assert shares.status_code == 200, shares.text
    listed = shares.json()["shares"]
    assert [s["slug"] for s in listed] == [open_share["slug"], older_open["slug"]]
    assert listed[0]["star_count"] == 1
    for h in hidden:
        assert h["slug"] not in shares.text
    assert not {"password_hash", "delete_token", "storage_path", "user_id", "content_text"} & set(walk_keys(shares.json()))
    stats = profile.json()
    assert (stats["share_count"], stats["total_views"], stats["total_stars"]) == (2, 10, 1)


def test_share_list_sorts_and_paginates(client, seed):
    user, username = _profile(seed)
    few_views = seed.share(user, is_private=False, view_count=1, created_at=_ago(1))
    many_views = seed.share(user, is_private=False, view_count=50, created_at=_ago(2))

    by_views = client.get(f"/api/u/{username}/shares?sort=views", headers=unique_ip()).json()
    first_page = client.get(f"/api/u/{username}/shares?limit=1", headers=unique_ip()).json()
    second_page = client.get(f"/api/u/{username}/shares?limit=1&page=2", headers=unique_ip()).json()

    assert [s["slug"] for s in by_views["shares"]] == [many_views["slug"], few_views["slug"]]
    assert [s["slug"] for s in first_page["shares"]] == [few_views["slug"]] and first_page["has_more"] is True
    assert [s["slug"] for s in second_page["shares"]] == [many_views["slug"]] and second_page["has_more"] is False


def test_custom_slug_of_a_user_with_a_username_stays_reachable(client, seed):
    """Custom slugs are not prefixed with the username: a slug never contains '/'."""
    user, _ = _profile(seed)
    act_as(user)
    custom = f"page-{uuid.uuid4().hex[:8]}"

    resp = client.post("/api/publish", json={"content": "<p>hi</p>", "custom_slug": custom}, headers=unique_ip())

    assert resp.status_code == 200, resp.text
    slug = resp.json()["slug"]
    seed.adopt(slug)
    assert slug == custom
    assert client.get(f"/api/shares/{slug}").status_code == 200
