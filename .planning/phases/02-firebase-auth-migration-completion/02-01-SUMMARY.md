---
phase: 02-firebase-auth-migration-completion
plan: 01
subsystem: auth
tags: [firebase, postgres, plpgsql, rpc, provisioning, fastapi, pytest, live-db]

# Dependency graph
requires:
  - phase: 01-security-hardening
    provides: live local Postgres/MinIO boundary-test convention (docker compose up -d + uuid-fresh identifiers)
provides:
  - Working provision_firebase_user RPC (constraint-named ON CONFLICT + fully-qualified RETURN QUERY) applied to infra/init, migration 009, and the live dropitx-pg DB
  - tests/test_auth_session_live.py — live-DB coverage of the 401 -> session -> 200 contract, idempotent re-provisioning with email update, and the concurrent first-login race
affects: [02-02, 02-03, 02-04, phase-3-deployment, k8s-migrate-job]

# Actuals (#2632) — pairs with the plan's estimate (55,000 tokens, confidence: low).
# Realized diff is far smaller: an interrupted prior session had already authored most
# of the SQL fix and test draft; this run verified/corrected them and drove TDD gates.
actuals:
  tokens: 1800    # chars/4 over the 3 task commits' realized diff
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ON CONFLICT ON CONSTRAINT <name> as the standard workaround when a RETURNS TABLE OUT parameter collides with an ON CONFLICT column list (bare column lists cannot be qualified in Postgres)"
    - "Live auth tests fake only JWT verification: dependency_overrides[get_firebase_claims] for route-level Depends, patched app.dependencies.verify_firebase_jwt + Bearer header for get_current_user's direct-call path"

key-files:
  created:
    - tests/test_auth_session_live.py
    - migrations/009_fix_provision_firebase_user.sql
  modified:
    - infra/init/02_rpc_functions.sql

key-decisions:
  - "Fix shipped as new migration 009 (008 left immutable per 02-VALIDATION Wave 0); infra/init/02_rpc_functions.sql and 009 carry byte-identical function bodies"
  - "Live test fakes only the Firebase JWT check; RPC and all DB lookups run against real Postgres (the mocked test_auth_session.py structurally cannot catch this bug class)"
  - "RED asserts the desired 200 and fails against the buggy RPC's live 500 ambiguous-column error — proves live reproduction and satisfies TDD's must-fail gate"

patterns-established:
  - "Pattern: live-DB auth flow tests patch app.dependencies.verify_firebase_jwt (tests/test_dependencies.py convention) so get_current_user's direct get_firebase_claims call is exercisable without real Firebase tokens"
  - "Pattern: constraint-named ON CONFLICT inside RETURNS TABLE functions whose OUT parameters share a column name with the target table"

requirements-completed: [AUTH-02, AUTH-03]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "Fixed provision_firebase_user RPC — first-time GET /api/auth/session provisions auth.users + user_profiles and returns the profile; repeat calls idempotent with email reflected"
    requirement: AUTH-02
    verification:
      - kind: integration
        ref: "tests/test_auth_session_live.py#test_full_provision_and_401_then_success_flow"
        status: pass
      - kind: other
        ref: "docker compose exec -T postgres psql -U dropitx -d dropitx -f - < migrations/009_fix_provision_firebase_user.sql (exit 0, idempotent)"
        status: pass
      - kind: manual_procedural
        ref: "SELECT * FROM provision_firebase_user('manual-verify-uid','a@b.com') twice — one row both times, no ambiguous-column error; cleaned up via DELETE"
        status: pass
    human_judgment: false
  - id: D2
    description: "Protected-route provisioning contract — GET /api/v1/keys 401 user_not_provisioned before session, 200 after"
    requirement: AUTH-03
    verification:
      - kind: integration
        ref: "tests/test_auth_session_live.py#test_full_provision_and_401_then_success_flow"
        status: pass
    human_judgment: false
  - id: D3
    description: "Concurrent first-login race — two simultaneous first-time session calls for the same uid both 200, exactly one auth.users + one user_profiles row, no stale-401 window afterward"
    requirement: AUTH-02
    verification:
      - kind: integration
        ref: "tests/test_auth_session_live.py#test_concurrent_first_time_session_calls_no_500"
        status: pass
    human_judgment: false

# Metrics
duration: 15min
completed: 2026-08-16
status: complete
---

# Phase 2 Plan 01: Firebase Provisioning RPC Fix Summary

**provision_firebase_user fixed via constraint-named ON CONFLICT + fully-qualified RETURN QUERY (new migration 009 + infra/init), proven live against real Postgres by a new non-mocked test suite covering the 401 -> session -> 200 flow, idempotent re-provisioning, and the concurrent first-login race**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-16T05:32:00Z
- **Completed:** 2026-08-16T05:47:00Z
- **Tasks:** 2 (TDD: RED -> GREEN for Task 1, coverage task 2)
- **Files modified:** 3

## Accomplishments
- Fixed the ambiguous `user_id` PL/pgSQL error that made 100% of real provisioning calls fail: `ON CONFLICT ON CONSTRAINT user_profiles_user_id_key` + `user_profiles.`-qualified RETURN QUERY, applied identically to `infra/init/02_rpc_functions.sql` (in place) and new `migrations/009_fix_provision_firebase_user.sql` (008 kept immutable), and executed live against `dropitx-pg`
- New `tests/test_auth_session_live.py` (2 tests, both passing): full 401 `user_not_provisioned` -> session 200 -> protected 200 flow, idempotent second call with email update (exactly 1 profile row), and two concurrent first-time session calls both 200 with exactly one row in each table and no stale-401 window — the coverage gap the design spec flagged and mocked tests structurally cannot catch
- RED was a genuine live reproduction: with the buggy 008 definition restored on the live DB, the test failed with the actual 500 `column reference "user_id" is ambiguous` error before the fix was applied

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing live test** - `5205a4d` (test)
2. **Task 1 (GREEN): fix provision_firebase_user** - `49e3ed8` (feat)
3. **Task 2: concurrent first-login coverage** - `14f2b51` (test)

**Plan metadata:** see final docs commit (docs(02-01): complete plan)

## Files Created/Modified
- `infra/init/02_rpc_functions.sql` - corrected `provision_firebase_user` body (banner comment preserved); fresh-boot source of truth
- `migrations/009_fix_provision_firebase_user.sql` - new migration superseding 008; header documents the OUT-parameter collision; applied to pre-existing DBs via k8s/migrate-job glob
- `tests/test_auth_session_live.py` - live-DB integration tests: single-caller flow + concurrent race; only Firebase JWT verification is faked

## Decisions Made
- Fix as new migration 009 (not in-place 008 edit) per 02-VALIDATION Wave 0; infra/init fixed in place (no migration history); byte-identical function bodies enforced and diff-verified
- Test-auth strategy: `app.dependency_overrides[get_firebase_claims]` for `/api/auth/session` (route-level `Depends`, plan-specified) plus `patch("app.dependencies.verify_firebase_jwt")` + Bearer header for `/api/v1/keys` — everything downstream (RPC, user lookups) is live
- RED assertion style: assert desired 200 so the test fails against the buggy RPC (asserting the buggy 500 would make RED pass trivially and violate TDD's fail-fast rule)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan's override-only claims pattern could not exercise the protected route**
- **Found during:** Task 1 (RED phase)
- **Issue:** `get_current_user` calls `get_firebase_claims(request)` directly (plain Python call, not via the DI container), so `dependency_overrides[get_firebase_claims]` — honored by `/api/auth/session` — is invisible to `/api/v1/keys`; the real JWT check ran and returned `401 "Missing or invalid Authorization header"` (string detail), failing the `detail.code` assertion for the wrong reason
- **Fix:** Additionally patch `app.dependencies.verify_firebase_jwt` to return the fixed claims and send a dummy Bearer header — the established convention in `tests/test_dependencies.py`; the real `get_current_user` DB-lookup path stays fully live
- **Files modified:** tests/test_auth_session_live.py
- **Verification:** 401 assertion now passes against the real unprovisioned-lookup path; both tests green
- **Committed in:** 5205a4d (part of RED commit)

**2. [Rule 1 - Bug] Pre-existing test draft used the wrong protected-route path**
- **Found during:** Task 1 (pre-existing-work verification, before any run)
- **Issue:** The interrupted prior session's draft called `/api/keys` — not a mounted route (keys router mounts under `/api/v1` via `app/v1/router.py`); would 404 instead of exercising `get_current_user`
- **Fix:** Corrected to `/api/v1/keys` (also read_first-confirmed against `app/v1/keys.py` list endpoint)
- **Files modified:** tests/test_auth_session_live.py
- **Verification:** Live 401/200 assertions pass
- **Committed in:** 5205a4d

**3. [Rule 1 - Bug] Pre-existing 009 migration header lacked the required supersedes context**
- **Found during:** Task 1 (pre-existing-work verification)
- **Issue:** Draft 009 header was a verbatim copy of 008's 3-line comment, omitting the plan-required note that 009 supersedes 008's buggy `ON CONFLICT`/`RETURN QUERY` (OUT-parameter collision)
- **Fix:** Rewrote the header lines to document the collision and 008's immutability; function body already byte-identical to infra/init (verified via extracted-block diff)
- **Files modified:** migrations/009_fix_provision_firebase_user.sql
- **Verification:** `diff` of the two CREATE OR REPLACE blocks reports identical; 009 applies clean (exit 0)
- **Committed in:** 49e3ed8

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bug corrections to interrupted-session drafts)
**Impact on plan:** All fixes were required to make the plan's own behavior spec executable; no scope creep. The pre-existing partial work (SQL fix + test draft from the interrupted session) was verified against the plan and adopted with the corrections above.

## TDD Gate Compliance

- RED gate: `5205a4d` — `test(02-01): add failing live test...` — run failed for the RIGHT reason (live 500 `column reference "user_id" is ambiguous`, confirmed in captured log output) after restoring the buggy 008 definition on the live DB
- GREEN gate: `49e3ed8` — `feat(02-01): fix provision_firebase_user...` — after applying 009 live, `test_full_provision_and_401_then_success_flow` passes
- REFACTOR: not needed (no cleanup beyond the fix; tests already conventional)
- Tracer feedback gate: re-ran the tracer `<verify>` (009 re-apply + test) after GREEN — passed; auto mode active (`auto_advance: true`)

## Issues Encountered
None beyond the documented deviations. Full-suite check: exactly the 5 pre-existing STATE.md-documented failures (`test_health_deep` + 4 in `test_public_api_validation.py`), 248 passed, no new failures.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- AUTH-02 and AUTH-03 now pass live; `GET /api/auth/session` works end-to-end against real Postgres for the first time
- `migrations/009_fix_provision_firebase_user.sql` is picked up automatically by `k8s/migrate-job.yaml`'s `migrations/*.sql` glob for pre-existing DBs; fresh boots get the fix from `infra/init/02_rpc_functions.sql`
- Plans 02-02 (AUTH-01/AUTH-04), 02-03 and 02-04 (AUTH-05) can proceed on a working provisioning entrypoint

## Self-Check: PASSED

All key files exist on disk; all 3 task commits verified in git log (`5205a4d`, `49e3ed8`, `14f2b51`); `git log --grep='02-01'` returns 3 commits.

---
*Phase: 02-firebase-auth-migration-completion*
*Completed: 2026-08-16*
