# README Review: DropItX API

**File:** `/Users/ddphuong/Projects/next-labs/dropitx-api/README.md`
**Date:** 2026-05-02
**Reviewer:** code-reviewer

---

## Overall Assessment

The README is well-structured with a good TOC, clear command reference, and useful examples. However, it has **accuracy issues** (stale/missing routes), a **broken quick-start** (`.env.example` does not exist), and **omissions** relative to the actual codebase. The inconsistencies between the README and the CLAUDE.md suggest these docs drifted apart.

---

## Critical Issues

### 1. Quick Start references non-existent `.env.example`

README line 32: `cp .env.example .env`

The file `/Users/ddphuong/Projects/next-labs/dropitx-api/.env.example` does **not exist**. A developer following these instructions will get an error on the first run.

**Fix:** Either create `.env.example` with the template from the Configuration section, or replace the `cp` line with a direct instruction to create `.env` manually.

### 2. API Reference is incomplete -- many routes undocumented

The README lists ~20 routes. The actual codebase has ~35+ routes. Missing from the README:

**Dashboard/team routes (all JWT-authenticated, under `/api/dashboard/teams`):**

| Method | Path | In Code | In README |
|--------|------|---------|-----------|
| `GET` | `/teams/{slug}` | `teams.py:80` | **Missing** |
| `PATCH` | `/teams/{slug}` | `teams.py:90` | **Missing** |
| `DELETE` | `/teams/{slug}` | `teams.py:113` | **Missing** |
| `PATCH` | `/teams/{slug}/members` | `teams.py:149` | **Missing** |
| `DELETE` | `/teams/{slug}/members` | `teams.py:177` | **Missing** |
| `GET` | `/teams/{slug}/invites` | `team_invites.py:35` | **Missing** |
| `POST` | `/teams/{slug}/invites` | `team_invites.py:53` | **Missing** |
| `DELETE` | `/teams/{slug}/invites` | `team_invites.py:90` | **Missing** |
| `POST` | `/teams/{slug}/invites/bulk` | `team_invites.py:117` | **Missing** |
| `POST` | `/teams/{slug}/invites/{invite_id}/resend` | `team_invites.py:164` | **Missing** |
| `GET` | `/teams/{slug}/events` | `team_invites.py:211` | **Missing** |
| `GET` | `/teams/{slug}/shares` | `team_invites.py:236` | **Missing** |

**Public routes:**

| Method | Path | In Code | In README |
|--------|------|---------|-----------|
| `DELETE` | `/api/shares/{slug}` | `shares.py:70` | **Missing** |
| `POST` | `/api/shares/{slug}/set-password` | `shares.py:110` | **Missing** |

That is 14 undocumented routes, nearly half the API surface.

### 3. Auth table has inaccuracies

README Authentication section lists the API Key auth mechanism as:
> `Authorization: Bearer shk_...` or `sht_...` -- v1 documents

This is correct but incomplete. The `/api/v1/keys` endpoints use **JWT auth** (via `get_current_user`), not API key auth. The table implies all v1 routes use API keys. Need to split or clarify that `/api/v1/keys` uses JWT.

Also: the README says upload uses "Optional JWT" but the `publish` endpoint at `POST /api/publish` requires **mandatory JWT** (`get_current_user`, not `get_optional_user`). The Auth table correctly says "JWT" for publish, but the Authenticated Endpoints table groups it with upload which may confuse.

---

## High Priority

### 4. README/CLAUDE.md auth description mismatch for keys

CLAUDE.md says `/api/v1/keys` uses "JWT (cookie)". The README's Auth table says the Bearer header format. The code in `keys.py` uses `get_current_user` which extracts from the `Authorization: Bearer` header (not a cookie). The CLAUDE.md "cookie" mention is stale/misleading. At minimum, the README should note JWT tokens work via Bearer header.

### 5. No badges

Best practice for open-source Python API projects is to include badges (CI status, Python version, license, coverage). The README has none. At minimum, add:
- Python version badge
- License badge (or clarify if truly private -- see issue #9)

### 6. No Contributing / Development Setup section

No CONTRIBUTING.md, no `.github/` directory, no development setup beyond Quick Start. Missing:
- PR workflow expectations
- Code style (ruff, black, etc.)
- How to run linting
- Pre-commit hooks

The `pyproject.toml` has `[project.optional-dependencies] dev` but no mention of linting tools.

---

## Medium Priority

### 7. Project Structure tree is incomplete

README lists `core/` and `app/` but omits:
- `models/` is mentioned in the tree but only as a single line -- could list subfiles (`share.py`, `team.py`, `api_key.py`, `analytics.py`)
- `tests/` directory exists (currently empty) but not mentioned
- `supabase/` directory (present per git status, likely contains migrations)
- `plans/`, `docs/`, `.claude/` (development infrastructure)

### 8. Missing response format documentation

The README shows request examples but never documents response shapes. For a programmatic API (especially the v1 endpoints), developers need to know the JSON response schema. The `DocumentResponse`, `ApiKeyCreateResponse`, `PublishResponse` models exist in code but are not documented.

### 9. License inconsistency

README says "Private -- all rights reserved." but no LICENSE file exists in the repo. If the project is truly private, this is fine. If it will be open-sourced, needs a proper LICENSE file and badge.

### 10. No Supabase setup instructions

The README says "Supabase project with Auth, Postgres, and Storage configured" as a requirement but gives no guidance on:
- Required RPC functions (`search_shares`, `check_rate_limit`, `increment_share_views`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`)
- Required tables (shares, teams, team_members, team_invites, team_events, team_shares, api_keys, share_views, user_profiles)
- Storage bucket creation (`html-files`, `shares`)
- RLS policies

The `supabase/` directory exists (per git status) but is untracked. Point developers there if it contains the schema.

### 11. Vercel deployment section is sparse

"Requires `@vercel/python` runtime" but there is no `vercel.json` in the repo. The CLAUDE.md mentions entry point `app/main.py` but the Vercel build for Python typically needs either `vercel.json` or a specific project config. The README should clarify whether auto-detection works or if config is needed.

---

## Low Priority

### 12. Search example query parameter inconsistency

README search example uses `?q=hello&page=1&limit=10`. The actual endpoint in `search.py` has default `limit=20`, so the example shows `limit=10` which is valid but not the default. Minor, but could confuse.

### 13. No error response documentation

API error shapes are not documented. FastAPI returns `{"detail": "..."}` by default, which is implicit but worth documenting for consumers.

### 14. CLAUDE.md has a route the README omits

CLAUDE.md mentions `/api/shares/{slug}` for "Public share delete, password set/unlock". The README only documents `/api/shares/{slug}/unlock` under public endpoints. The full `shares.py` file has 3 endpoints (delete, set-password, unlock) but only unlock appears in the README.

---

## Positive Observations

- Good TOC with clear section hierarchy
- ASCII architecture diagram is helpful and concise
- curl examples for all three auth methods (JWT, API key, unauthenticated)
- Configuration section with env var table is thorough
- Key patterns section effectively communicates async/compensting/rate-limiting design
- Commands table is clean and actionable

---

## Recommended Actions

1. **[Critical]** Create `.env.example` or remove the `cp` instruction from Quick Start
2. **[Critical]** Add the 14 missing API routes to the API Reference tables
3. **[Critical]** Fix auth table to clarify `/api/v1/keys` uses JWT, not API key
4. **[High]** Add badges (Python version at minimum)
5. **[High]** Add Contributing section or CONTRIBUTING.md
6. **[Medium]** Add Supabase setup section or link to `supabase/` directory
7. **[Medium]** Document v1 response schemas (DocumentResponse, ApiKeyCreateResponse)
8. **[Medium]** Update Project Structure tree to include `models/`, `tests/`, `supabase/`

---

## Unresolved Questions

1. Is this project intended to be open-sourced? If so, a LICENSE file and Contributing guide are needed. If not, the README's "Private" license line is acceptable but `git clone` instructions are odd for a private repo.
2. Does the `supabase/` directory contain migration files that should be referenced from the README?
3. Are there plans to add linting/formatting tooling (ruff, black)? If so, the Commands table and Contributing section should reflect that.
