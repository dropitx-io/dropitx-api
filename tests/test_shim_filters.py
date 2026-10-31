"""Live-DB tests: filter operators of the DB shim that take list values.

An empty `in_` list matches nothing, and array containment/overlap bind real
arrays. Runs against the real Postgres from CI.
"""

from __future__ import annotations

import uuid

from core.supabase import get_admin_client
from tests.conftest import act_as


def test_in_with_empty_list_returns_no_rows(seed):
    seed.share(seed.user(), is_private=False)
    db = get_admin_client()

    rows = db.table("shares").select("id").in_("id", []).execute().data

    assert rows == []


def test_negated_in_with_empty_list_matches_every_row(seed):
    share = seed.share(seed.user(), is_private=False)
    db = get_admin_client()

    rows = (
        db.table("shares").select("id")
        .eq("id", share["id"])
        .not_.in_("id", [])
        .execute()
        .data
    )

    assert [row["id"] for row in rows] == [share["id"]]


def test_team_shares_listing_tolerates_a_row_without_a_share(client, seed):
    member = seed.user()
    db = get_admin_client()
    team = db.table("teams").insert(
        {"name": "Orphan row team", "slug": f"orphan-{uuid.uuid4().hex[:10]}", "owner_id": member.id}
    ).execute().data[0]
    seed.teams.append(team["id"])
    db.table("team_members").insert(
        {"team_id": team["id"], "user_id": member.id, "role": "viewer"}
    ).execute()
    db.table("team_shares").insert(
        {"team_id": team["id"], "share_id": None, "shared_by": member.id}
    ).execute()
    act_as(member)

    resp = client.get(f"/api/dashboard/teams/{team['slug']}/shares")

    assert resp.status_code == 200
    assert resp.json()[0]["shares"] is None


def test_contains_matches_a_text_array_column(seed):
    tag = f"t{uuid.uuid4().hex[:10]}"
    tagged = seed.share(seed.user(), is_private=False, tags=[tag, "other"])
    seed.share(seed.user(), is_private=False, tags=["unrelated"])
    db = get_admin_client()

    rows = db.table("shares").select("id").contains("tags", [tag]).execute().data

    assert [row["id"] for row in rows] == [tagged["id"]]


def test_overlaps_matches_a_text_array_column(seed):
    tag = f"t{uuid.uuid4().hex[:10]}"
    tagged = seed.share(seed.user(), is_private=False, tags=[tag])
    db = get_admin_client()

    rows = db.table("shares").select("id").overlaps("tags", [tag, "absent"]).execute().data

    assert [row["id"] for row in rows] == [tagged["id"]]


def test_explore_filters_by_tag(client, seed):
    tag = f"t{uuid.uuid4().hex[:10]}"
    tagged = seed.share(seed.user(), is_private=False, tags=[tag])
    act_as(None)

    resp = client.get("/api/explore", params={"tag": tag})

    assert resp.status_code == 200
    assert [share["slug"] for share in resp.json()["shares"]] == [tagged["slug"]]
