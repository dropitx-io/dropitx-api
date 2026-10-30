# Roadmap: DropItX API

## Overview

DropItX API's core product (content sharing, security primitives, team collaboration, discovery, file management, programmatic API) already shipped across v0.1.0–v0.3.0. This roadmap covers the stabilization milestone that follows: close a live security audit on now internet-facing public endpoints, finish and verify the in-progress Firebase Auth backend migration (substantially already coded on `firebase-auth-backend-api`), finalize a single deployment path with a working from-empty bootstrap, and reach the PRD's own stated >80% test-coverage target with docs that match reality. Each phase leaves the system in a verifiably safer or more complete state than the last, ending with coverage measured against the final, hardened behavior.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Security Hardening** - Close the CRITICAL/HIGH findings from the 2026-08-12 public-endpoint audit before they're exploited over the Cloudflare Tunnel (completed 2026-08-15)
- [ ] **Phase 2: Firebase Auth Migration Completion** - Verify, finish, and document the already-coded Firebase Auth backend end-to-end
- [ ] **Phase 3: Deployment Path Finalization** - Pick and harden one deployment target with a working from-empty DB bootstrap and real end-to-end verification
- [ ] **Phase 4: Test Coverage & Reliability** - Reach the PRD's >80% coverage target with enforced CI and reconciled testing docs

## Phase Details

### Phase 1: Security Hardening

**Goal**: Public endpoints can no longer be used to hijack shares or exhaust server resources over the Cloudflare Tunnel
**Depends on**: Nothing (first phase — addresses live, currently-exploitable vulnerabilities)
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06
**Success Criteria** (what must be TRUE):

  1. Anonymous callers cannot encrypt or overwrite another user's share — `POST /shares/{slug}/encrypt` requires the owner's JWT or a valid `delete_token`, and non-owners get a 401/403 instead of a 200 takeover
  2. Repeated password guesses against `POST /shares/{slug}/reencrypt` are throttled and eventually rejected with 429 instead of allowed indefinitely
  3. `GET /api/download/group/{slug}` rejects excessive requests per IP (429) instead of building unlimited in-memory ZIP archives
  4. Public read paths (share content, download, preview) reject request bursts per IP instead of serving unlimited traffic
  5. `GET /api/dashboard/domains/resolve/{domain}` is no longer freely callable from the public internet without an internal credential or a rate limit
  6. `GET /api/u/{username}` returns a normal 200 profile response instead of a 500 on every call

**Plans**: 2/2 plans executed

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — SEC-01/02/06: encrypt_share owner auth, reencrypt_share rate limit, profiles.py NameError fix

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — SEC-03/04/05: new rate-limit buckets for bulk-download, public reads, domain-resolve

### Phase 2: Firebase Auth Migration Completion

**Goal**: DropItX's identity model is fully and verifiably Firebase-based end-to-end, with documentation matching reality
**Depends on**: Phase 1
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05
**Success Criteria** (what must be TRUE):

  1. Any protected route (dashboard, publish, images, v1 keys, etc.) accepts a valid Firebase ID token and correctly resolves the calling user via the `TEXT`-keyed `auth.users` table
  2. A first-time Firebase login via `GET /api/auth/session` provisions `auth.users` + `user_profiles` and returns the profile; calling it again with the same uid does not duplicate rows and reflects an updated email
  3. Calling a protected route with a valid-but-never-provisioned Firebase token returns `401 user_not_provisioned`; after calling `GET /api/auth/session`, the same route succeeds
  4. `FIREBASE_PROJECT_ID` is present in `.env.example`, `.env.local.example`, and the deployed environment's secret/config for every active deployment target
  5. `CLAUDE.md` and the architecture/config docs describe Firebase — not Supabase JWT/JWKS — as the live auth mechanism

**Plans**: 3/4 plans executed

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Fix provision_firebase_user RPC (ambiguous column bug), verify live single-caller + concurrent-caller flows (AUTH-02, AUTH-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 02-02-PLAN.md — AUTH-01 regression check + manual FIREBASE_PROJECT_ID env addition (AUTH-01, AUTH-04)
- [x] 02-03-PLAN.md — Doc reconciliation pass A: CLAUDE.md, README.md, core docs (AUTH-05)
- [x] 02-04-PLAN.md — Doc reconciliation pass B: deployment/reference docs (AUTH-05)

### Phase 3: Deployment Path Finalization

**Goal**: One deployment path is fully specified, bootstraps a working database from empty, and is verified end-to-end before any traffic cutover
**Depends on**: Phase 2 (deployment verification needs the finalized auth/identity model)
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, DEPLOY-05, DEPLOY-06
**Success Criteria** (what must be TRUE):

  1. The chosen target's migration plan correctly reflects the current Firebase-based auth requirements, not the pre-migration Supabase-JWT assumption
  2. The chosen deployment target keeps a working S3-compatible storage backend — no upload/publish/share-read/encryption route fails from missing storage config
  3. A fresh, empty database on the chosen target is bootstrapped with schema, RPCs, and the Firebase-uid migration before the app serves traffic
  4. Deployment verification exercises a real authenticated request, a storage round-trip, and a rate-limited path — not just `GET /docs` and a bare 401 — before any rollback path is torn down
  5. Deployment-facing docs consistently describe the same two-bucket storage layout (`html-files`, `shares`; thumbnails nested inside `html-files`)

**Plans**: TBD

Plans:

- [ ] 03-01: TBD (populated by /gsd-plan-phase)

### Phase 4: Test Coverage & Reliability

**Goal**: Test coverage is measured, meets the PRD's own target, and is enforced automatically, with accurate testing documentation
**Depends on**: Phase 1, Phase 2, Phase 3 (coverage should reflect the final, hardened behavior across security, auth, and deployment work)
**Requirements**: TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):

  1. Running `pytest` locally or in CI reports a coverage percentage (`pytest-cov` configured)
  2. A CI workflow runs the test suite with coverage automatically on push/PR
  3. Reported line coverage for `app/`, `core/`, and `models/` is at or above 80%
  4. `TESTING.md` and `DEVELOPMENT.md` describe one consistent, accurate account of which tests require live Postgres/MinIO and which don't

**Plans**: TBD

Plans:

- [ ] 04-01: TBD (populated by /gsd-plan-phase)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Security Hardening | 2/2 | Complete    | 2026-08-15 |
| 2. Firebase Auth Migration Completion | 3/4 | In Progress|  |
| 3. Deployment Path Finalization | 0/TBD | Not started | - |
| 4. Test Coverage & Reliability | 0/TBD | Not started | - |
