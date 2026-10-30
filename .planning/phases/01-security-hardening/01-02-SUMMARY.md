---
phase: 01-security-hardening
plan: 02
subsystem: api
tags: [fastapi, rate-limiting, security, dos-mitigation]

# Dependency graph
requires:
  - phase: 01-security-hardening
    provides: "01-01's tests/test_rate_limit_boundaries.py scaffold (TestPasswordRateLimitBoundary + _fresh_ip_slug helper convention)"
provides:
  - "GET /api/download/group/{slug} rate-limited 10/60s per IP (fail-open), checked before any storage fetch"
  - "GET /shares/{slug}/content, /download, /preview rate-limited 60/60s per IP (fail-open), distinct from the password-guess bucket"
  - "GET /api/dashboard/domains/resolve/{domain} rate-limited 60/60s per IP (fail-open)"
affects: []

actuals:
  tokens: 2708
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Check-before-fetch rate limiting (ip -> check_*_rate_limit -> 429-if-not-success -> fetch) extended to three more route families, reusing the exact _check_rpc wrapper convention and oembed.py's complete 429 shape (message + Retry-After header)"

key-files:
  created: []
  modified:
    - core/rate_limit.py
    - app/internal/download.py
    - app/public/shares.py
    - app/public/preview.py
    - app/dashboard/domains.py
    - tests/test_all_endpoints.py
    - tests/test_custom_domains.py
    - tests/test_rate_limit_boundaries.py

key-decisions:
  - "Reused the exact _check_rpc-backed wrapper convention (check_upload_rate_limit/check_oembed_rate_limit shape) for all three new buckets rather than introducing a new mechanism, per the plan's explicit prohibition"
  - "All three new buckets stay fail-open, matching the plan's prohibition against making cost/DoS-abuse buckets fail-closed"
  - "No shared-secret/internal-auth header added to domains/resolve — rate limiting alone satisfies SEC-05's minimum bar per the plan's explicit scope boundary"

patterns-established:
  - "check_bulk_download_rate_limit/check_public_read_rate_limit/check_domain_resolve_rate_limit all mirror check_oembed_rate_limit's one-line-wrapper shape exactly"

requirements-completed: [SEC-03, SEC-04, SEC-05]

coverage:
  - id: D1
    description: "GET /api/download/group/{slug} rejects excessive requests per IP with 429 before building the in-memory ZIP; 10th request succeeds, 11th is rejected"
    requirement: "SEC-03"
    verification:
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestPublicEndpoints::test_download_group_not_found"
        status: pass
      - kind: integration
        ref: "tests/test_rate_limit_boundaries.py#TestBulkDownloadRateLimitBoundary::test_nth_succeeds_and_n_plus_1th_rejected"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /shares/{slug}/content, /download, /preview each reject bursts per IP with 429 (60/min), distinct from the password-guess bucket; existing not-found tests unaffected"
    requirement: "SEC-04"
    verification:
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestPublicEndpoints::test_share_content_not_found, test_share_download_not_found, test_share_preview_not_found"
        status: pass
      - kind: integration
        ref: "tests/test_rate_limit_boundaries.py#TestPublicReadRateLimitBoundary::test_nth_succeeds_and_n_plus_1th_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "GET /api/dashboard/domains/resolve/{domain} is no longer freely callable without a rate limit; 60th request succeeds, 61st is rejected; route still functions correctly with new Request param/imports"
    requirement: "SEC-05"
    verification:
      - kind: unit
        ref: "tests/test_custom_domains.py#TestResolveCustomDomain::test_resolve_custom_domain_not_configured"
        status: pass
      - kind: unit
        ref: "tests/test_custom_domains.py#TestDomainRoutesExist::test_all_domain_routes_registered"
        status: pass
      - kind: integration
        ref: "tests/test_rate_limit_boundaries.py#TestDomainResolveRateLimitBoundary::test_nth_succeeds_and_n_plus_1th_rejected"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-08-15
status: complete
---

# Phase 1 Plan 2: Rate Limiting for Bulk Download, Public Reads, and Domain Resolve Summary

**Closed the remaining 3 CRITICAL/MEDIUM security-audit findings by adding three new fail-open `_check_rpc`-backed rate-limit buckets (`check_bulk_download_rate_limit`, `check_public_read_rate_limit`, `check_domain_resolve_rate_limit`) wired as the first statement into five previously-unthrottled route handlers.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-15T22:24:00Z (approx)
- **Completed:** 2026-08-15T22:52:00Z (approx)
- **Tasks:** 3
- **Files modified:** 8 (5 production, 3 test)

## Accomplishments
- `GET /api/download/group/{slug}` now rejects the 11th bulk-download request/min per IP with 429 before any storage fetch or ZIP build — closes the unbounded in-memory ZIP DoS (SEC-03)
- `GET /shares/{slug}/content`, `/download`, and `/preview` each now reject the 61st public-read request/min per IP with 429, distinct from the existing password-guess throttle (SEC-04)
- `GET /api/dashboard/domains/resolve/{domain}` — an internal-only route now reachable from the public internet via Cloudflare Tunnel — now rejects the 61st request/min per IP with 429 (SEC-05)
- Both audit-flagged 6-finding sets (SEC-01..06, this plan plus 01-01) are now closed

## Task Commits

Each task was committed atomically:

1. **Task 1: SEC-03 — bulk_download_group rate-limited before ZIP build** - `03ebdcb` (feat)
2. **Task 2: SEC-04 — public read paths rate-limited (content, download, preview)** - `6bd2583` (feat)
3. **Task 3: SEC-05 — domains/resolve rate-limited** - `eafe4dc` (feat)

_Note: Tasks were marked `tdd="true"` in the plan; RED state was confirmed interactively before each GREEN wiring (ImportError on the not-yet-defined rate-limit function), but RED itself was not committed separately — each task landed as a single commit containing both the test and the implementation, matching Plan 01-01's task boundaries. Task 3's `test_resolve_custom_domain_not_configured` passed immediately even pre-wiring (the unmodified route already 404s on empty data) — this matched the plan's own framing of that test as a regression guard against `NameError`/`ImportError` from the new imports/param, not a strict RED gate, so no fail-fast investigation was triggered._

## Files Created/Modified
- `core/rate_limit.py` - added `check_bulk_download_rate_limit`, `check_public_read_rate_limit`, `check_domain_resolve_rate_limit` (all `_check_rpc`-backed, fail-open)
- `app/internal/download.py` - `bulk_download_group` gains `Request` param + rate-limit check as first statement, before `_fetch_group`
- `app/public/shares.py` - `get_share_content` and `download_share` each gain the rate-limit check as first statement, before `_fetch_share`
- `app/public/preview.py` - `get_share_preview` gains the rate-limit check as first statement, before `_fetch_share`
- `app/dashboard/domains.py` - `resolve_custom_domain` gains `Request` param + rate-limit check as first statement, before `get_admin_client`
- `tests/test_all_endpoints.py` - no new tests added (existing `test_download_group_not_found`, `test_share_content_not_found`, `test_share_download_not_found`, `test_share_preview_not_found` verified still passing unmodified)
- `tests/test_custom_domains.py` - added `TestResolveCustomDomain::test_resolve_custom_domain_not_configured`, imports `TestClient`
- `tests/test_rate_limit_boundaries.py` - appended `TestBulkDownloadRateLimitBoundary`, `TestPublicReadRateLimitBoundary`, `TestDomainResolveRateLimitBoundary` to the file Plan 01-01 created, plus a new `_fresh_ip()` helper

## Decisions Made
- Reused the exact `_check_rpc`-backed one-line-wrapper convention (`check_oembed_rate_limit`'s shape) for all three new functions — no new rate-limiting mechanism introduced
- All three buckets are fail-open, matching the plan's explicit prohibition against making cost/DoS-abuse buckets fail-closed
- No shared-secret/internal-auth header added to `domains/resolve` — rate limiting alone satisfies SEC-05's minimum bar, per the plan's explicit out-of-scope note

## Deviations from Plan

None - plan executed exactly as written. All three tasks reused the existing `_check_rpc` wrapper convention verbatim, matching the plan's explicit prohibitions (no new rate-limiting mechanism, no fail-closed buckets, no shared-secret header, no route path/method changes, no `core/exceptions.py` envelope).

One clarifying note (not a deviation): the plan's `<verify>` command text `pytest tests/test_rate_limit_boundaries.py -k bulk_download` (and similarly `-k domain_resolve`/`-k public_read`) doesn't match pytest's substring `-k` filter against the actual CamelCase class names (`TestBulkDownloadRateLimitBoundary`, etc. — no underscore). Ran with `-k Bulk`/`-k Public`/`-k DomainResolve` instead to select the same tests; behavior and pass/fail outcome are identical.

## Issues Encountered
None beyond the pre-existing, out-of-scope failures already documented in `.planning/phases/01-security-hardening/deferred-items.md` from Plan 01-01 (`test_health_deep` + 4 in `tests/test_public_api_validation.py`). Re-ran the full suite after this plan's changes and confirmed these are the *only* 5 failures, with no new regressions — none of the files these failures touch (`app/main.py` health route, `shares.py`'s comments/set-password handlers) were modified by this plan.

## User Setup Required

None - no external service configuration required. Local Postgres/MinIO stack (`docker compose up -d`) was already running from Plan 01-01 and used as-is for this plan's live-DB boundary-test verification.

## Next Phase Readiness
- All 6 SEC-01..06 findings from the 2026-08-12 security audit are now closed across Plans 01-01 and 01-02
- Full test suite: 246 passed, 5 failed (all 5 are the pre-existing, out-of-scope failures documented in `deferred-items.md`; none touch files this plan modified)
- Phase 1 (Security Hardening) is ready for phase-level verification

---
*Phase: 01-security-hardening*
*Completed: 2026-08-15*

## Self-Check: PASSED
