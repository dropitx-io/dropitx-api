---
phase: 01-security-hardening
verified: 2026-08-15T23:30:00Z
status: passed
score: 15/15 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 1: Security Hardening Verification Report

**Phase Goal:** Public endpoints can no longer be used to hijack shares or exhaust server resources over the Cloudflare Tunnel
**Verified:** 2026-08-15T23:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Anonymous callers cannot encrypt an existing share without owner JWT/delete_token (SEC-01) | VERIFIED | `app/public/encryption.py:179-184` — `encrypt_share` calls `authorize_owner(row, user, body.delete_token)` after a 401-if-neither guard. Manually spot-checked with a mocked existing row: no-auth → `401 {"detail":"Authentication required"}`; wrong `delete_token` → `403 {"detail":"Not authorized to modify this share"}`. See Behavioral Spot-Checks. |
| 2 | Empty-string `delete_token` treated identically to no token (never matches) | VERIFIED | `app/public/_share_auth.py:12`: `if delete_token and row.get("delete_token") == delete_token` — empty string is falsy, short-circuits, never matches a null-stored token. |
| 3 | Repeated password guesses against `/reencrypt` are throttled and eventually 429 (SEC-02) | VERIFIED | `app/public/encryption.py:270-277` — `check_password_rate_limit(ip, slug)` runs before `_fetch_share_for_encrypt`. Live-DB boundary test `TestPasswordRateLimitBoundary::test_nth_succeeds_and_n_plus_1th_rejected` PASSED (5th succeeds, 6th rejected). |
| 4 | `GET /api/u/{username}` returns 200/404 instead of 500 (SEC-06) | VERIFIED | `app/public/profiles.py:71` — `.eq("is_public", True)` (bool literal, not bare name). `tests/test_profiles.py` (2 tests) PASSED. |
| 5 | Zero-shares public profile returns 200 with `share_count=0`, not 404 | VERIFIED | `tests/test_profiles.py::test_public_profile_zero_shares_returns_200` PASSED — mocked profile row + empty shares list → `200`, `share_count == 0`. |
| 6 | `GET /api/download/group/{slug}` rejects excessive requests per IP with 429 before ZIP build (SEC-03) | VERIFIED | `app/internal/download.py:70-84` — `check_bulk_download_rate_limit(ip)` is the first statement, before `_fetch_group`. Live-DB boundary test `TestBulkDownloadRateLimitBoundary` PASSED (10th succeeds, 11th rejected). |
| 7 | Public read paths (`content`/`download`/`preview`) reject bursts per IP with 429, distinct from password throttle (SEC-04) | VERIFIED | `app/public/shares.py:146-153,481-488`, `app/public/preview.py:295-299` — `check_public_read_rate_limit(ip)` as first statement in all three, before any DB/storage fetch. Live-DB boundary test `TestPublicReadRateLimitBoundary` PASSED (60th succeeds, 61st rejected). |
| 8 | `GET /api/dashboard/domains/resolve/{domain}` is no longer freely callable without rate limit (SEC-05) | VERIFIED | `app/dashboard/domains.py:353-368` — `check_domain_resolve_rate_limit(ip)` as first statement, before `get_admin_client()`. Live-DB boundary test `TestDomainResolveRateLimitBoundary` PASSED (60th succeeds, 61st rejected). |
| 9 | Rate-limit checks run before storage I/O even for empty/nonexistent share groups (SEC-03 ordering) | VERIFIED | Code inspection confirms `check_bulk_download_rate_limit` precedes `_fetch_group(slug)` unconditionally — 429 short-circuits regardless of group existence. |
| 10 | 5th password-guess attempt succeeds, 6th rejected with 429 (exact boundary) | VERIFIED | `tests/test_rate_limit_boundaries.py::TestPasswordRateLimitBoundary` — ran live against local Postgres, PASSED. |
| 11 | 10th bulk-download request succeeds, 11th rejected with 429 (exact boundary) | VERIFIED | `tests/test_rate_limit_boundaries.py::TestBulkDownloadRateLimitBoundary` — ran live, PASSED. |
| 12 | 60th public-read / domain-resolve request succeeds, 61st rejected with 429 (exact boundary, x2) | VERIFIED | `tests/test_rate_limit_boundaries.py::TestPublicReadRateLimitBoundary`, `TestDomainResolveRateLimitBoundary` — ran live, both PASSED. |
| 13 | 429 responses carry a `Retry-After` header on all 5 new/extended rate-limited routes | VERIFIED | Code inspection: all 5 call sites (`encryption.py` x1 password + x2 public-read, `download.py`, `preview.py`, `shares.py` x3, `domains.py`) construct `headers={"Retry-After": str(max(rate.reset, 1))}` on the 429 branch. |
| 14 | No new rate-limiting mechanism introduced; all buckets reuse `_check_rpc` convention | VERIFIED | `core/rate_limit.py:97-109` — `check_bulk_download_rate_limit`, `check_public_read_rate_limit`, `check_domain_resolve_rate_limit` are one-line `_check_rpc(...)` wrappers, matching `check_upload_rate_limit`/`check_oembed_rate_limit`'s existing shape. |
| 15 | All 6 SEC-01..06 audit findings closed, requirements traced correctly | VERIFIED | REQUIREMENTS.md marks SEC-01..06 `[x]` and "Complete" in traceability table; all 6 map to Phase 1 with no orphans. |

**Score:** 15/15 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/public/encryption.py` | `encrypt_share` auth guard, `reencrypt_share` rate limit | VERIFIED | Both wired; `authorize_owner` imported from shared module (post-WR-03 fix) |
| `app/public/profiles.py` | `true` → `True` fix | VERIFIED | Line 71 confirmed |
| `core/rate_limit.py` | 3 new rate-limit functions | VERIFIED | `check_bulk_download_rate_limit`, `check_public_read_rate_limit`, `check_domain_resolve_rate_limit` present, correct signatures |
| `app/internal/download.py` | Rate limit before ZIP build | VERIFIED | First statement, before `_fetch_group` |
| `app/public/shares.py` | Rate limit on content/download/download-status | VERIFIED | 3 call sites confirmed (incl. WR-01 fix for `download-status`) |
| `app/public/preview.py` | Rate limit on preview | VERIFIED | 1 call site confirmed |
| `app/dashboard/domains.py` | Rate limit on resolve | VERIFIED | Confirmed, route path/method unchanged |
| `app/public/_share_auth.py` | Shared `authorize_owner` (post-review dedup) | VERIFIED | New module, no circular import, both call sites updated (3 in shares.py, 1 in encryption.py) |
| `app/dependencies.py` | `get_client_ip` trusts `CF-Connecting-IP` only (CR-01 fix) | VERIFIED | Lines 175-186 confirmed — no longer trusts client-supplied `X-Forwarded-For`/`X-Real-IP` |
| `tests/test_profiles.py` | New mocked route tests | VERIFIED | 2 tests, both pass, substantive (real mocked row + real assertions) |
| `tests/test_rate_limit_boundaries.py` | Live-DB boundary tests (4 classes) | VERIFIED | All 4 classes present and pass against live Postgres |
| `tests/test_custom_domains.py` | Domain-resolve mocked test | VERIFIED | `TestResolveCustomDomain::test_resolve_custom_domain_not_configured` passes; `TestDomainRoutesExist` unmodified/still passes |
| `tests/test_all_endpoints.py` | New/updated tests for SEC-01/02/06 | VERIFIED (with caveat) | Tests pass, but two SEC-01 tests exercise the 404-not-found path, not the 401 path — see Anti-Patterns/Warning below |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `encrypt_share` | `authorize_owner` | direct call, post-fetch | WIRED | Confirmed via read + manual invocation |
| `reencrypt_share` | `check_password_rate_limit` | pre-fetch call | WIRED | Confirmed check-before-fetch order |
| `bulk_download_group` | `check_bulk_download_rate_limit` | pre-fetch call | WIRED | Confirmed check-before-fetch order |
| `get_share_content`/`download_share`/`get_download_status` | `check_public_read_rate_limit` | pre-fetch call | WIRED | All 3 confirmed pre-fetch |
| `get_share_preview` | `check_public_read_rate_limit` | pre-fetch call | WIRED | Confirmed |
| `resolve_custom_domain` | `check_domain_resolve_rate_limit` | pre-fetch call | WIRED | Confirmed |
| `get_public_profile` | `.eq("is_public", True)` | query construction | WIRED | Confirmed real Python bool, not bare identifier |
| All 5 new rate limiters | `get_client_ip` → `CF-Connecting-IP` | transitive | WIRED | Confirmed all consume `app.dependencies.get_client_ip`, which was fixed at its single root-cause point (CR-01) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast-tier suite (no live DB), SEC-01/02/06 targeted tests | `pytest tests/test_all_endpoints.py -k "encrypt_share or reencrypt or public_profile" -v` | 4 passed | PASS |
| `tests/test_profiles.py` full run | `pytest tests/test_profiles.py -v` | 2 passed | PASS |
| `tests/test_custom_domains.py` full run | `pytest tests/test_custom_domains.py -v` | 17 passed | PASS |
| Live-DB rate-limit boundary suite (all 4 classes) | `pytest tests/test_rate_limit_boundaries.py -v` (docker compose up) | 4 passed (5th/10th/60th succeed, 6th/11th/61st rejected, all 4 buckets) | PASS |
| Full test suite regression (live DB) | `pytest` | 246 passed, 5 failed (all 5 pre-existing/documented in `deferred-items.md`, none touching phase-modified files — confirmed via `git show --stat` across all phase commits) | PASS (no new regressions) |
| Manual behavioral trace: `encrypt_share` real auth-guard paths, existing row mocked | inline Python script invoking the ASGI app with a mocked existing share row (no user, no delete_token) | `401 {"detail":"Authentication required"}` | PASS |
| Manual behavioral trace: `encrypt_share` wrong `delete_token` on existing row | same script, `delete_token="wrong-token"` vs stored `"real-token"` | `403 {"detail":"Not authorized to modify this share"}` | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SEC-01 | 01-01 | Anonymous callers cannot encrypt/overwrite an existing share | SATISFIED | `authorize_owner` wired into `encrypt_share`; manually verified 401/403 |
| SEC-02 | 01-01 | `/reencrypt` password guesses rate-limited fail-closed | SATISFIED | `check_password_rate_limit` wired pre-fetch; boundary test passes live |
| SEC-03 | 01-02 | `/download/group/{slug}` per-IP rate limit before ZIP build | SATISFIED | `check_bulk_download_rate_limit` wired pre-fetch; boundary test passes live |
| SEC-04 | 01-02 | Public read paths rate-limited distinct from password throttle | SATISFIED | `check_public_read_rate_limit` wired into content/download/preview + (post-review) encryption-info/download-status; boundary test passes live |
| SEC-05 | 01-02 | `/dashboard/domains/resolve/{domain}` protected by rate limit | SATISFIED | `check_domain_resolve_rate_limit` wired pre-fetch; boundary test passes live |
| SEC-06 | 01-01 | `GET /api/u/{username}` returns normal response, not 500 | SATISFIED | `true` → `True` fix confirmed; genuine mocked-row tests pass |

No orphaned requirements — all 6 SEC-01..06 IDs declared in plan frontmatter match REQUIREMENTS.md exactly, all marked Complete.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_all_endpoints.py` | 264-289 | `test_encrypt_share_no_auth`/`test_encrypt_share_empty_delete_token` mock the share-lookup chain to return `data=[]`, which makes `_fetch_share_for_encrypt` 404 *before* the auth-guard code is ever reached — the tests pass via the tolerant `(401, 404, 500)` range but for the "share not found" reason, not the "unauthenticated" reason they're named for | WARNING | Not a functional security gap — the actual 401/403 behavior is real and was independently confirmed by direct execution against a mocked *existing* row (see Behavioral Spot-Checks). But these two persisted regression tests provide no protection against a future regression that removes/reorders the auth guard, since they'd still pass via the same 404 path. Recommend a follow-up test using a mocked existing row (as `tests/test_profiles.py` already does) to genuinely exercise the 401/403 branches. |

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any of the 9 phase-modified production files (`app/public/encryption.py`, `app/public/profiles.py`, `app/public/shares.py`, `app/public/preview.py`, `app/dashboard/domains.py`, `app/internal/download.py`, `core/rate_limit.py`, `app/dependencies.py`, `app/public/_share_auth.py`).

### Human Verification Required

None. All must-haves resolved to VERIFIED via code inspection, existing/live test execution, or direct behavioral spot-check.

### Gaps Summary

No blocking gaps. One WARNING-level test-quality note (see Anti-Patterns above): the two SEC-01 regression tests in `tests/test_all_endpoints.py` assert a tolerant status-code range that they satisfy via the wrong code path (404 instead of 401), because the WR-02 review-fix's mock returns an empty row unconditionally. The underlying security fix itself (owner/delete_token authorization on `encrypt_share`) is correctly implemented and was independently, empirically confirmed against a mocked existing row during this verification. This does not block the phase — the goal ("public endpoints can no longer be used to hijack shares or exhaust server resources") is achieved and evidenced — but is worth a follow-up test-hardening task.

Separately noted for context (not a gap in this phase): `01-REVIEW-VERIFY.md`'s WR-04 finding (the `CF-Connecting-IP` trust assumption is only as strong as network-layer enforcement that the app is reachable solely through the Cloudflare Tunnel — `k8s/api.yaml`'s current `NodePort` doesn't enforce this) has already been explicitly tracked as `DEPLOY-06` for Phase 3 per this repo's own commit history (`a4a4db5`) and REQUIREMENTS.md. Confirmed present and correctly scoped out of Phase 1.

---

_Verified: 2026-08-15T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
