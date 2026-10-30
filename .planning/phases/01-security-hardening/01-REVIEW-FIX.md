---
phase: 01-security-hardening
fixed_at: 2026-08-15T15:50:16Z
review_path: .planning/phases/01-security-hardening/01-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 01-security-hardening: Code Review Fix Report

**Fixed at:** 2026-08-15T15:50:16Z
**Source review:** .planning/phases/01-security-hardening/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (Critical: 1, Warning: 3 — Info findings IN-01/IN-02 out of scope per `fix_scope: critical_warning`)
- Fixed: 4
- Skipped: 0

**Verification environment:** Fixes were applied and verified inside the isolated worktree (`.claude/worktrees/rf-01-14497-1786808695`, branch `gsd-reviewfix/01-14497`), then fast-forwarded onto `gsd/v0.1.0-milestone` during cleanup. Syntax checks used `ast.parse`; import-resolution and test runs used the main checkout's `.venv` (`/Users/ddphuong/Projects/next-labs/dropitx/dropitx-api/.venv`) since the worktree has no virtualenv of its own. Both are reproducible from the main checkout post-cleanup.

## Fixed Issues

### CR-01: All 5 new rate limiters are keyed on a client-spoofable IP, defeating the mitigation

**Files modified:** `app/dependencies.py`
**Commit:** `2f9319a`
**Applied fix:** Per explicit user direction (this deployment sits behind Cloudflare Tunnel), `get_client_ip()` now trusts only the `CF-Connecting-IP` header — set by Cloudflare's edge and not forgeable by the end client through the tunnel — instead of the client-supplied `X-Forwarded-For`/`X-Real-IP` headers. When `CF-Connecting-IP` is absent, it falls back to `request.client.host` (the direct connection IP) rather than any client-controlled header, so a missing Cloudflare header degrades to "one shared bucket" instead of "attacker-chosen bucket." This is the single root-cause fix point; all 5 rate limiters (`domains.py`, `download.py`, `encryption.py`, `preview.py`, `shares.py`) consume `get_client_ip()` and are fixed transitively — no call sites needed changes.

### WR-01: "Public-reads" rate-limiting is incomplete — two public DB-hitting endpoints were left out

**Files modified:** `app/public/encryption.py`, `app/public/shares.py`
**Commit:** `f47cafe`
**Applied fix:** Added a `Request` parameter and `check_public_read_rate_limit(get_client_ip(request))` guard (429 on failure, matching the existing pattern in `get_share_content`/`download_share`/`get_share_preview`) to `GET /shares/{slug}/encryption-info` and `GET /shares/{slug}/download-status`, closing the two gaps in SEC-04's public-read rate-limiting scope.

### WR-02: New SEC-01 regression tests can raise instead of asserting cleanly without a live DB

**Files modified:** `tests/test_all_endpoints.py`
**Commit:** `19e20a8`
**Applied fix:** Added `@patch("app.public.encryption.get_admin_client")` to `test_encrypt_share_no_auth` and `test_encrypt_share_empty_delete_token`, mocking the `.table("shares").select("*").eq("slug", ...).execute()` chain to return `data=[]` (so `_fetch_share_for_encrypt` raises a clean 404 instead of propagating a raw `OSError` from a failed DB connection) — matching the mocking pattern already used in `tests/test_profiles.py` and `tests/test_custom_domains.py`. Verified: both tests now pass without `docker compose up -d`; full `test_all_endpoints.py` run shows the same 9 pre-existing DB-dependent failures as before (unchanged, not part of this phase) and both target tests moved from failing to passing, with no new failures introduced.

### WR-03: `_authorize_owner` is duplicated verbatim across two modules, and is now live code in both

**Files modified:** `app/public/_share_auth.py` (new), `app/public/shares.py`, `app/public/encryption.py`
**Commit:** `06aa5f9`
**Applied fix:** Extracted the identical `_authorize_owner` helper into a new shared module `app/public/_share_auth.py` (as `authorize_owner`), imported and called from both `shares.py` (3 call sites) and `encryption.py` (1 call site), removing both duplicate definitions. Verified no circular import: `app/public/_share_auth.py` imports `User` from `app.dependencies`, which is the same direction `shares.py`/`encryption.py` already import from; confirmed by actually importing both modules end-to-end via the project's `.venv`.

## Skipped Issues

None — all in-scope findings were fixed. IN-01 and IN-02 were not attempted (out of scope for `fix_scope: critical_warning`).

---

_Fixed: 2026-08-15T15:50:16Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
