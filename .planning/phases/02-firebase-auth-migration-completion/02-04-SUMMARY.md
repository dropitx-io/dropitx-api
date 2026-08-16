---
phase: 02-firebase-auth-migration-completion
plan: 04
subsystem: docs
tags: [firebase, jwt, rs256, documentation, auth, x509-certs]

# Dependency graph
requires:
  - phase: 02-firebase-auth-migration-completion/02-01
    provides: verified Firebase auth backend (provision_firebase_user fix, live-DB tests) establishing core/security.py + app/dependencies.py as the doc source of truth
provides:
  - Final 8 of 16 audited doc files reconciled to describe Firebase ID-token verification (RS256 vs Google x509 certs) as the live auth mechanism
  - Phase-level AUTH-05 grep now clean across docs/, README.md, CLAUDE.md (verify_supabase_jwt / Supabase JWKS: zero matches)
affects: [03-deployment-path (DEPLOY-01/DEPLOY-05 own the untouched storage/deployment-target claims), phase-4-testing (TESTING doc reconciliation)]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 16924   # chars/4 over the 8-file diff in commits ff7f37d..7a4fc23 (includes adopted pre-existing doc-refresh edits)
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Doc reconciliation keeps auth-mechanism clauses and storage/deployment-target claims in separate commits/phases (AUTH-05 vs DEPLOY-01/DEPLOY-05)"

key-files:
  created: []
  modified:
    - docs/DEPLOYMENT.md
    - docs/deployment-guide.md
    - docs/system-architecture.md
    - docs/project-roadmap.md
    - docs/code-standards.md
    - docs/design-guidelines.md
    - docs/project-overview-pdr.md
    - docs/API.md

key-decisions:
  - "Task 1 diagram fix relabeled the whole auth box (Supabase Auth/JWKS keys -> Firebase Auth/Firebase certs), not just the 'JWKS keys' cell — leaving the box titled 'Supabase Auth (JWT issuer)' would keep describing Supabase as the live auth mechanism and violate the plan's must-have truth, while neighboring table/bucket boxes stayed byte-identical (DEPLOY-05 territory)"
  - "Sequence-diagram cert-cache TTL corrected alongside the 'Fetch JWKS' relabel (10min -> 1hr) because the stale TTL is part of the same auth-mechanism step"
  - "Adopted the pre-existing uncommitted doc-refresh edits in deployment-guide.md, system-architecture.md, project-roadmap.md, project-overview-pdr.md — the plan's line references were authored against that working-tree state (same approach 02-03 recorded as a decision)"
  - "docs/API.md get_api_key stale line ref (:70, actual :96) logged to deferred-items.md instead of fixed — API-key citation staleness is outside the auth-mechanism scope"

patterns-established:
  - "Narrow doc-pass discipline: correct only the auth-mechanism token in mixed sentences, leave storage/deployment claims for their owning phase"

requirements-completed: [AUTH-05]

# Coverage metadata (#1602) — one entry per shipped deliverable.
coverage:
  - id: D1
    description: "Deployment-facing docs (DEPLOYMENT.md, deployment-guide.md, system-architecture.md, project-roadmap.md) describe Firebase — not Supabase JWT/JWKS — as the live auth mechanism, with storage/deployment-target claims untouched"
    requirement: AUTH-05
    verification:
      - kind: other
        ref: "grep -rn \"verify_supabase_jwt\\|Supabase Auth\\|JWKS URL\\|Supabase JWKS\" docs/DEPLOYMENT.md docs/deployment-guide.md docs/system-architecture.md docs/project-roadmap.md (exit 1 — zero matches; broader bare-JWKS grep also clean)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reference/standards docs (code-standards.md, design-guidelines.md, project-overview-pdr.md, API.md) describe Firebase as the live auth mechanism, with API.md's get_current_user/get_optional_user line refs corrected to app/dependencies.py:56/:84"
    requirement: AUTH-05
    verification:
      - kind: other
        ref: "grep -rn \"verify_supabase_jwt\\|Supabase Auth\\|Supabase JWKS\\|Supabase URL\" docs/code-standards.md docs/design-guidelines.md docs/project-overview-pdr.md docs/API.md (exit 1 — zero matches)"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-08-16
status: complete
---

# Phase 02 Plan 04: Firebase Auth Doc Reconciliation (Batch 2) Summary

**Reconciled the remaining 8 of 16 audited doc files to describe Firebase ID-token verification (RS256 against Google's x509 certs, FIREBASE_PROJECT_ID audience) instead of Supabase JWT/JWKS, completing AUTH-05's doc-accuracy pass**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-16T06:03:58Z
- **Completed:** 2026-08-16T06:11:01Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- All 8 files in this batch now match `core/security.py::verify_firebase_jwt` reality: Google x509 cert endpoint, 1-hour `_CERTS_TTL` cache with `kid`-miss refetch, `FIREBASE_PROJECT_ID` audience/issuer checks
- Deployment setup instructions no longer send operators down a dead-end Supabase JWKS-URL path — `FIREBASE_PROJECT_ID` from the Firebase console is the documented step (docs/DEPLOYMENT.md line 65, docs/deployment-guide.md auth-settings block)
- docs/API.md auth contract corrected: Firebase ID token + provisioning requirement (`401 user_not_provisioned`), with stale `app/dependencies.py:41/:58` citations updated to the current `:56/:84`
- Plan-level AND phase-level verification greps pass: `verify_supabase_jwt` / `Supabase JWKS` now return zero matches across all of `docs/`, `README.md`, and `CLAUDE.md` (combined 02-03 + 02-04 effort, satisfying 02-VALIDATION.md's phase check)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix deployment-facing docs** - `ff7f37d` (docs)
2. **Task 2: Fix reference/standards docs** - `7a4fc23` (docs)

## Files Created/Modified
- `docs/DEPLOYMENT.md` - line 5 auth token split from the Supabase clause; JWKS-URL step replaced with FIREBASE_PROJECT_ID + cert caching
- `docs/deployment-guide.md` - Firebase console auth settings; auto-fetched cert endpoint replaces JWKS curl; troubleshooting row checks FIREBASE_PROJECT_ID vs aud/iss
- `docs/system-architecture.md` - auth diagram box (Firebase Auth / Firebase certs), Fetch-Firebase-certs step (cached 1hr), Firebase Cert Caching bullet with kid-miss refetch, Redis future-work bullet
- `docs/project-roadmap.md` - JWT verification changelog line (Firebase ID token, RS256)
- `docs/code-standards.md` - JWT verification standard line (Firebase x509 certs, FIREBASE_PROJECT_ID audience)
- `docs/design-guidelines.md` - auth guideline, httpx scope, in-memory cache exception (1hr TTL)
- `docs/project-overview-pdr.md` - Authentication NFR, deployment Auth line, registration label, built-in Auth bullet
- `docs/API.md` - JWT bullet (Firebase Auth, provisioned-user contract, corrected line refs), JWT label in auth legend

## Decisions Made
- Relabeled the full auth box in system-architecture.md's diagram (not just the "JWKS keys" cell): a box still titled "Supabase Auth (JWT issuer)" would keep describing Supabase as the live JWT issuer, violating the plan's must-have truth. The "(JWT issuer)" subtitle itself is accurate for Firebase and was kept; neighboring table/bucket boxes were left byte-identical per the DEPLOY-05 prohibition.
- Corrected "(cached 10min)" to "(cached 1hr)" in the same sequence-diagram step as the "Fetch JWKS" relabel — the stale TTL is part of the same auth-mechanism step (`_CERTS_TTL = 3600`).
- Adopted the interrupted prior session's uncommitted doc-refresh edits in 4 of the 8 files (deployment-guide.md, system-architecture.md, project-roadmap.md, project-overview-pdr.md) after verifying the plan's line references were authored against that working-tree state; the refresh content itself contains no auth-mechanism corrections (this plan supplies those).
- Left docs/DEPLOYMENT.md's Render framing, `SUPABASE_URL`-required-for-auth assumption, and all bucket/table-count claims untouched — Phase 3 DEPLOY-01/DEPLOY-05 territory, per the plan's prohibitions.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- One out-of-scope discovery logged to `deferred-items.md` (new file, phase directory): `docs/API.md` line 28 cites `get_api_key` at `app/dependencies.py:70` but the function sits at line 96. Not fixed — it is an API-key citation, not a Supabase/Firebase auth-mechanism claim, so it falls outside this plan's named scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- AUTH-05's doc-accuracy requirement is complete across all 16 audited files plus core/supabase.py (02-03 + 02-04 combined)
- Phase-level grep from 02-VALIDATION.md passes: `grep -rn "verify_supabase_jwt\|Supabase JWKS" docs/ README.md CLAUDE.md` → empty
- 02-02 remains paused at its human checkpoint (env example files) — the only outstanding piece of Phase 2
- Phase 3 (Deployment Path Finalization) owns the deliberately untouched claims: Render-vs-k8s/Dokploy framing, SUPABASE_URL-for-auth assumption (DEPLOY-01), bucket count/naming (DEPLOY-05)

---
*Phase: 02-firebase-auth-migration-completion*
*Completed: 2026-08-16*
