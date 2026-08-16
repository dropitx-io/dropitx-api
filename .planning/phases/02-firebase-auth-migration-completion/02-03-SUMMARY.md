---
phase: 02-firebase-auth-migration-completion
plan: "03"
subsystem: auth
tags: [firebase, jwt, documentation, auth-migration, x509-certs]

# Dependency graph
requires:
  - phase: 02-firebase-auth-migration-completion
    provides: "verified Firebase auth backend (provisioning RPC fix + live-DB tests from 02-01) establishing core/security.py::verify_firebase_jwt as the doc source of truth"
provides:
  - "First 9 of 16 audited files (CLAUDE.md, README.md, ARCHITECTURE.md, CONFIGURATION.md, core/supabase.py, DEVELOPMENT.md, TESTING.md, GETTING-STARTED.md, codebase-summary.md) now describe Firebase — not Supabase JWT/JWKS — as the live auth mechanism"
  - "FIREBASE_PROJECT_ID documented as the auth env var (CONFIGURATION.md env table row + CLAUDE.md env section)"
affects: [02-04 (remaining 7 audit files), 03-deployment-path (DEPLOY-05 storage-layout doc pass), 04-testing (testing-strategy doc reconciliation)]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
actuals:
  tokens: 13922   # chars/4 over the realized diff of the 9 files (estimate was 34000)
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Doc-reconciliation pass pattern: correct only the auth-referring clause of a conflated sentence; leave storage/DB-layout claims for the phase that owns them (Phase 3 DEPLOY-05)"

key-files:
  created: []
  modified:
    - CLAUDE.md
    - README.md
    - docs/ARCHITECTURE.md
    - docs/CONFIGURATION.md
    - core/supabase.py
    - docs/DEVELOPMENT.md
    - docs/TESTING.md
    - docs/GETTING-STARTED.md
    - docs/codebase-summary.md

key-decisions:
  - "Adopted the plan's narrow AUTH-05 scope: where a sentence conflates auth with storage/DB claims, only the auth clause was corrected; broader storage-layout staleness left for Phase 3's DEPLOY-05"
  - "Kept docs/TESTING.md lines 107-131 (supabase_url/supabase_anon_key/supabase_service_role_key mock instructions) byte-identical — those are real code identifier names, not auth-mechanism prose"
  - "Kept docs/GETTING-STARTED.md Supabase-project walkthrough (lines 13-16, 59-63, 96-155) untouched — separate, larger onboarding inaccuracy explicitly out of AUTH-05 scope"
  - "Adopted pre-existing uncommitted doc-refresh edits found in CLAUDE.md, README.md, docs/codebase-summary.md (interrupted prior session) — verified against the plan, then layered the auth corrections on top; they shipped inside this plan's task commits"

patterns-established:
  - "Auth doc wording: 'Firebase ID token verification via core/security.py::verify_firebase_jwt — RS256 against Google's rotating public x509 certs, aud/iss checked against FIREBASE_PROJECT_ID; SUPABASE_URL retained only for storage-URL construction'"

requirements-completed: [AUTH-05]  # partial: 9 of 16 audited files; 02-04 covers the remaining 7

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "Core project docs (CLAUDE.md, README.md, docs/ARCHITECTURE.md, docs/CONFIGURATION.md, core/supabase.py) describe Firebase, not Supabase JWT/JWKS, as the live auth mechanism"
    requirement: AUTH-05
    verification:
      - kind: other
        ref: 'grep -rn "verify_supabase_jwt\|Supabase Auth\|Supabase JWKS\|JWKS endpoint" CLAUDE.md README.md docs/ARCHITECTURE.md docs/CONFIGURATION.md core/supabase.py → exit 1 (no matches)'
        status: pass
      - kind: other
        ref: 'grep -n "FIREBASE_PROJECT_ID" docs/CONFIGURATION.md → env-table row present at line 13'
        status: pass
      - kind: other
        ref: 'git diff docs/ARCHITECTURE.md — storage-bucket/Postgres clauses byte-identical; only auth clauses changed'
        status: pass
    human_judgment: false
  - id: D2
    description: "Dev-workflow docs (docs/DEVELOPMENT.md, docs/TESTING.md, docs/GETTING-STARTED.md, docs/codebase-summary.md) describe Firebase as the live auth mechanism, with out-of-scope content intentionally untouched"
    requirement: AUTH-05
    verification:
      - kind: other
        ref: 'grep -rn "verify_supabase_jwt\|Supabase Auth\|Supabase JWKS" docs/DEVELOPMENT.md docs/TESTING.md docs/GETTING-STARTED.md docs/codebase-summary.md → exit 1 (no matches)'
        status: pass
      - kind: other
        ref: 'diff vs HEAD: docs/GETTING-STARTED.md single hunk @@ -5 +5 @@ only; protected ranges 13-16/59-63/96-155 byte-identical'
        status: pass
      - kind: other
        ref: 'diff vs HEAD: docs/TESTING.md lines 107-131 byte-identical; hunks touch only lines 5/35/103/105'
        status: pass
    human_judgment: false

# Metrics
duration: 3min
completed: 2026-08-16
status: complete
---

# Phase 2 Plan 3: Firebase Auth Doc Reconciliation Summary

**9 core/dev docs plus one stale docstring corrected to describe Firebase ID-token verification (RS256 vs Google's x509 certs, `FIREBASE_PROJECT_ID`) instead of Supabase JWKS as the live auth mechanism — first 9 of 16 audited files, AUTH-05**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-16T05:56:54Z
- **Completed:** 2026-08-16T06:00:41Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Eliminated every `verify_supabase_jwt` / "Supabase Auth" / "Supabase JWKS" / "JWKS endpoint" reference from the first 9 files of 02-RESEARCH.md's Doc Staleness Audit table (plan-level grep across all 9 files: exit 1, zero matches)
- Documented `FIREBASE_PROJECT_ID` as the required auth env var: new env-table row in `docs/CONFIGURATION.md`, CLAUDE.md env section + `core/config.py` module bullet, and DEPLOYMENT-auth-dependency lines recast from "Supabase Auth (JWKS) required" to "Firebase project credentials (`FIREBASE_PROJECT_ID`) required"
- Corrected the cache-TTL figure everywhere it appeared: 10-minute Supabase JWKS cache → `_CERTS_TTL` 1-hour Google x509 cert cache (README, ARCHITECTURE, CONFIGURATION, DEVELOPMENT, codebase-summary)
- Split conflated sentences per the plan's scope decision: auth clause corrected (Firebase), storage/DB-layout claims (Postgres/Storage "live in Supabase", two buckets) left byte-identical for Phase 3's DEPLOY-05
- De-conflated `docs/TESTING.md`'s mocking prose: the offline suite mocks a PostgREST-compatible shim (local Postgres/MinIO client) and Firebase JWT verification — while the `supabase_*` mock-instruction identifiers (lines 107-131) were kept untouched as real code names
- `docs/DEVELOPMENT.md` local-setup no longer claims a Supabase project is needed: auth = Firebase (`FIREBASE_PROJECT_ID`), data/storage = local Postgres + MinIO via `docker compose up -d`

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix core project docs** - `dbb4253` (docs)
2. **Task 2: Fix dev-workflow docs** - `71f9a9b` (docs)

**Plan metadata:** committed with SUMMARY/state updates (docs)

## Files Created/Modified

- `CLAUDE.md` - auth bullet, JWT route label, security/config module bullets, deployment auth dependency, env-var framing → Firebase; SUPABASE_* marked legacy storage-URL only
- `README.md` - auth table row + JWT verification sentence → Firebase RS256 vs Google certs, ~1h `_CERTS_TTL`
- `docs/ARCHITECTURE.md` - overview auth clauses (lines 6, 8), mermaid nodes (`Auth (Firebase)`, `JWT (Firebase)`), data-flow step 2, key-abstraction row → `verify_firebase_jwt`
- `docs/CONFIGURATION.md` - `SUPABASE_URL` row de-JWKS'd to legacy storage-only framing; new `FIREBASE_PROJECT_ID` row; cert-cache paragraph corrected
- `core/supabase.py` - stale module docstring line ("Supabase Auth ... still goes through cloud Supabase URL") corrected
- `docs/DEVELOPMENT.md` - local-setup, async-bridge note, 401 troubleshooting → Firebase wording
- `docs/TESTING.md` - offline-suite intro + mocking-strategy heading/prose reworded; anchor link updated; technical mock instructions untouched
- `docs/GETTING-STARTED.md` - line 5 word swap only (Supabase → Firebase)
- `docs/codebase-summary.md` - overview auth sentence, security JWT bullet, deployment Auth row → Firebase

## Decisions Made

- Followed the plan's narrow AUTH-05 reading (the one 02-RESEARCH.md recommended): auth-mechanism claims only; storage-layout/bucket-count claims intentionally left stale for Phase 3's DEPLOY-05
- Supabase-project walkthrough in GETTING-STARTED.md and `supabase_*` mock identifiers in TESTING.md deliberately untouched (documented in acceptance criteria, verified byte-identical)
- Pre-existing uncommitted doc-refresh edits in CLAUDE.md, README.md, docs/codebase-summary.md adopted into this plan's commits after verifying they matched the plan's expected baseline (plan line references were authored against them)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Corrected docs/ARCHITECTURE.md line 6 auth clause (audit-table row the plan's action list omitted)**
- **Found during:** Task 1
- **Issue:** The plan's action enumerated ARCHITECTURE.md lines 8/33/39/62/83-84 but the 02-RESEARCH.md audit table also flags line 6 ("authentication, the Postgres database, and object storage all live in Supabase"), which describes Supabase as the auth home — violating the plan's must_haves truth #1 if left
- **Fix:** Corrected only the auth clause ("authentication uses Firebase ID tokens verified against Google's public certs"); the Postgres/Storage clauses in the same sentence left byte-identical per the scope decision
- **Files modified:** docs/ARCHITECTURE.md
- **Verification:** git diff confirms storage/DB clauses unchanged; plan-level grep passes
- **Committed in:** dbb4253 (Task 1 commit)

**2. [Rule 2 - Missing Critical] Corrected CLAUDE.md core/config.py bullet's "(Auth only now)" parenthetical**
- **Found during:** Task 1
- **Issue:** The plan directed CLAUDE.md lines 11/41/49/87/91-92, but the adjacent `core/config.py` module bullet still claimed the legacy `supabase_*` settings were "(Auth only now)" — the exact misdirection (SUPABASE_URL governs auth) this plan exists to remove
- **Fix:** Rewrote the bullet to `firebase_project_id` (auth, required) + legacy `supabase_url` (storage-URL construction only; not used for auth), matching core/config.py's actual fields
- **Files modified:** CLAUDE.md
- **Verification:** CLAUDE.md passes the acceptance grep; bullet now matches core/config.py:1-24
- **Committed in:** dbb4253 (Task 1 commit)

**3. [Rule 1 - Bug] Updated docs/TESTING.md line 35 anchor link to renamed heading**
- **Found during:** Task 2
- **Issue:** Plan-directed heading rename ("Mocking strategy for Supabase" → "Mocking strategy for the DB/storage client and Firebase auth") would have orphaned the intra-doc link `[Mocking strategy](#mocking-strategy-for-supabase)` at line 35
- **Fix:** Updated the anchor to `#mocking-strategy-for-the-dbstorage-client-and-firebase-auth`
- **Files modified:** docs/TESTING.md
- **Verification:** heading slug matches link target; grep passes
- **Committed in:** 71f9a9b (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 missing-critical audit completions, 1 broken-link fix)
**Impact on plan:** All three close gaps the plan's own must_haves/scope-decision required; no scope creep — storage/DB claims untouched throughout.

## Issues Encountered

None - both tasks' `<verify>` greps passed on the first run; `core/supabase.py` docstring change parse-checked clean (`ast.parse`).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 02-04 (remaining 7 audit-table files: DEPLOYMENT.md, deployment-guide.md, system-architecture.md, code-standards.md, design-guidelines.md, project-overview-pdr.md, project-roadmap.md, API.md) can proceed — grep confirms those files still carry the stale references (`docs/deployment-guide.md`, `docs/project-overview-pdr.md`, `docs/project-roadmap.md`, `docs/API.md`, `docs/code-standards.md` verified stale this session)
- 02-02 remains paused at its human checkpoint (env-example files) — untouched by this plan, per orchestrator instruction
- AUTH-05 requirement: this plan covers 9 of 16 audited files; the requirement is only fully satisfied once 02-04 lands (shared-ID gate applied when marking complete)
- Storage-layout/bucket-count claims in all 9 files intentionally left for Phase 3's DEPLOY-05

## Self-Check: PASSED

- Commits `dbb4253` (Task 1) and `71f9a9b` (Task 2) found in git log
- All 9 modified files exist on disk
- Plan-level verification grep re-run against all 9 files: exit 1 (zero stale auth-mechanism matches)

---
*Phase: 02-firebase-auth-migration-completion*
*Completed: 2026-08-16*
