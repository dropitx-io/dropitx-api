---
phase: 01-security-hardening
plan: 01
subsystem: api
tags: [fastapi, authentication, rate-limiting, bugfix, security]

# Dependency graph
requires: []
provides:
  - "encrypt_share requires owner JWT or matching delete_token (401/403 instead of anonymous 200 takeover)"
  - "reencrypt_share is rate-limited 5/10min per ip:slug before touching storage (429 fail-closed)"
  - "GET /api/u/{username} returns 200/404 instead of 500 (NameError fixed)"
  - "tests/test_rate_limit_boundaries.py scaffold for live-DB rate-limit boundary tests (Plan 01-02 appends more classes)"
affects: [01-02]

actuals:
  tokens: 1981
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Owner-or-delete_token auth guard (get_optional_user + _authorize_owner) reused verbatim across mutating share routes"
    - "Check-before-fetch rate limiting (check_password_rate_limit before the DB fetch) reused verbatim across password-guess routes"

key-files:
  created:
    - tests/test_profiles.py
    - tests/test_rate_limit_boundaries.py
  modified:
    - app/public/encryption.py
    - app/public/profiles.py
    - tests/test_all_endpoints.py

key-decisions:
  - "Reused existing _authorize_owner/check_password_rate_limit helpers verbatim rather than introducing new abstractions, per plan's prohibitions"
  - "Started local Postgres/MinIO via docker compose up -d to run live-DB boundary tests and confirm true GREEN state instead of relying on tolerant assertions alone"

patterns-established:
  - "encrypt_share now mirrors set_password's auth-guard shape exactly (fetch -> 401-if-neither -> _authorize_owner)"
  - "reencrypt_share now mirrors unlock_share's rate-limit shape exactly (ip -> check_password_rate_limit -> 429-if-not-success -> fetch)"

requirements-completed: [SEC-01, SEC-02, SEC-06]

coverage:
  - id: D1
    description: "POST /shares/{slug}/encrypt rejects anonymous/non-owner callers with 401/403 instead of a silent takeover"
    requirement: "SEC-01"
    verification:
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestOptionalAuthEndpoints::test_encrypt_share_no_auth"
        status: pass
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestOptionalAuthEndpoints::test_encrypt_share_empty_delete_token"
        status: pass
    human_judgment: false
  - id: D2
    description: "POST /shares/{slug}/reencrypt is rate-limited before storage fetch; 5th attempt succeeds, 6th is rejected with 429"
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestOptionalAuthEndpoints::test_reencrypt_share_no_auth_or_rate_limited"
        status: pass
      - kind: integration
        ref: "tests/test_rate_limit_boundaries.py#TestPasswordRateLimitBoundary::test_nth_succeeds_and_n_plus_1th_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "GET /api/u/{username} returns 200/404 instead of 500; zero-shares public profile is 200 with share_count=0"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "tests/test_profiles.py#TestGetPublicProfile::test_public_profile_zero_shares_returns_200"
        status: pass
      - kind: unit
        ref: "tests/test_profiles.py#TestGetPublicProfile::test_public_profile_not_found_returns_404"
        status: pass
      - kind: unit
        ref: "tests/test_all_endpoints.py#TestPublicEndpoints::test_public_profile_not_found"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-08-15
status: complete
---

# Phase 1 Plan 1: Security Hardening — Auth Gaps + Rate Limiting + 500 Fix Summary

**Closed 3 CRITICAL/HIGH security-audit findings by wiring existing helpers (`_authorize_owner`, `check_password_rate_limit`) into two previously-unprotected routes and fixing a one-character `NameError` that returned 500 on every profile lookup.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-08-15T15:14:00Z (approx, per STATE.md session start)
- **Completed:** 2026-08-15T15:23:12Z
- **Tasks:** 3
- **Files modified:** 5 (2 new test files, 3 modified)

## Accomplishments
- `POST /shares/{slug}/encrypt` now requires an owner JWT or matching `delete_token` — previously any anonymous caller could take over and encrypt someone else's share
- `POST /shares/{slug}/reencrypt` is now rate-limited 5/10min per `ip:slug` (fail-closed) before it touches storage, matching `unlock_share`'s existing pattern — previously password guesses were unbounded
- `GET /api/u/{username}` no longer 500s on every call (bare `true` -> `True` fix); a public profile with zero shares now correctly returns 200 with `share_count: 0` instead of erroring

## Task Commits

Each task was committed atomically:

1. **Task 1: SEC-01 — encrypt_share requires owner JWT or delete_token** - `691e365` (feat)
2. **Task 2: SEC-02 — reencrypt_share rate-limited before fetch** - `6d5f359` (feat)
3. **Task 3: SEC-06 — fix profiles.py NameError (true -> True)** - `a1cda7c` (fix)

**Plan metadata:** (this commit, docs)

_Note: Tasks were marked `tdd="true"` in the plan; RED state was confirmed interactively before each GREEN fix but RED itself was not committed separately — each task landed as a single commit containing both the failing-then-passing test and the implementation, per the plan's task boundaries._

## Files Created/Modified
- `app/public/encryption.py` - `encrypt_share` gains `get_optional_user` + `_authorize_owner` guard; `reencrypt_share` gains `check_password_rate_limit` check-before-fetch
- `app/public/profiles.py` - one-line fix: `.eq("is_public", true)` -> `.eq("is_public", True)`
- `tests/test_all_endpoints.py` - added `test_encrypt_share_no_auth`, `test_encrypt_share_empty_delete_token`, `test_reencrypt_share_no_auth_or_rate_limited`, `test_public_profile_not_found`
- `tests/test_profiles.py` (new) - mocked route tests for `get_public_profile` (zero-shares 200, not-found 404)
- `tests/test_rate_limit_boundaries.py` (new) - live-DB `TestPasswordRateLimitBoundary` proving the 5th attempt succeeds and 6th is rejected

## Decisions Made
- Started the local Postgres/MinIO stack via `docker compose up -d` (Rancher Desktop was not yet running; started it and waited for the daemon) so that live-DB boundary tests and full-suite regression checks could run for real, rather than relying solely on tolerant status-code assertions
- Installed `asyncpg`/`boto3`/etc. from the project's own `requirements.txt` into the `.venv` (already-declared dependencies, just not yet installed in this environment) — not a new/unreviewed package, so no package-legitimacy checkpoint was needed

## Deviations from Plan

None - plan executed exactly as written. All three tasks reused existing helpers verbatim (`_authorize_owner`, `check_password_rate_limit`) with no new abstractions, matching the plan's explicit prohibitions.

## Issues Encountered
- Local dev environment had no live Postgres/MinIO running and was missing `asyncpg`/`boto3` in the `.venv` despite being pinned in `requirements.txt` — resolved by installing from the existing lockfile-adjacent `requirements.txt` and starting `docker compose up -d`, not by adding new dependencies.
- Discovered 5 pre-existing, out-of-scope test failures unrelated to this plan's files (`test_health_deep`, and 4 failures in `tests/test_public_api_validation.py` touching `app/public/shares.py`'s comments/set-password handlers). Verified via `git show` that `tests/test_public_api_validation.py` is byte-identical to its pre-plan state — these are not regressions introduced here. Logged to `.planning/phases/01-security-hardening/deferred-items.md` per the scope-boundary rule; not fixed.

## User Setup Required

None - no external service configuration required. (Local Postgres/MinIO via `docker compose up -d` is a dev-environment prerequisite already documented in CLAUDE.md, not new setup introduced by this plan.)

## Next Phase Readiness
- SEC-01, SEC-02, SEC-06 closed; the remaining 3 audit findings (out of 6 total) are Plan 01-02's scope, which depends on this plan (wave 2)
- `tests/test_rate_limit_boundaries.py` is scaffolded with one class (`TestPasswordRateLimitBoundary`) — Plan 01-02 is expected to append additional boundary-test classes to this same file per the plan's "Artifacts this phase produces" note
- Full test suite is green except the 5 pre-existing, unrelated failures documented in `deferred-items.md` — these should be triaged separately, not blocking Plan 01-02

---
*Phase: 01-security-hardening*
*Completed: 2026-08-15*

## Self-Check: PASSED
