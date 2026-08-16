# Requirements: DropItX API

**Defined:** 2026-08-15
**Core Value:** Let anyone go from "I have HTML/Markdown/text" to "here's a shareable, optionally password-protected/E2E-encrypted URL" in one API call, reliably.

Scope note: DropItX API's core product features (content sharing, security primitives, team collaboration, discovery/analytics, file management, programmatic API) already shipped v0.1.0–v0.3.0 — see PROJECT.md's **Validated** section. This roadmap covers the stabilization work needed next: closing an open security audit, finishing the in-progress Firebase Auth migration, finalizing a deployment path, and reaching the PRD's own >80% test-coverage target.

## v1 Requirements

Requirements for this roadmap. Each maps to exactly one phase.

### Security Hardening (SEC)

- [x] **SEC-01**: Anonymous callers cannot encrypt or overwrite an existing share — `POST /shares/{slug}/encrypt` requires the owner's JWT or a valid `delete_token`, mirroring the `_authorize_owner` check already used by `set-password`/`burn`/`delete`
- [x] **SEC-02**: Repeated password guesses against `POST /shares/{slug}/reencrypt` are rate-limited (fail-closed), consistent with `/unlock`
- [x] **SEC-03**: `GET /api/download/group/{slug}` enforces a per-IP rate limit before downloading files and building a ZIP in memory
- [x] **SEC-04**: Public read paths (`GET /shares/{slug}/content`, `/download`, `/preview`) enforce a lightweight per-IP rate limit distinct from the password-only throttle
- [x] **SEC-05**: `GET /api/dashboard/domains/resolve/{domain}` is protected by an internal-only guard (shared secret header) or a rate limit, since it is reachable from the public internet via Cloudflare Tunnel
- [x] **SEC-06**: `GET /api/u/{username}` returns a normal profile response (200) instead of erroring on every call (`true` → `True` bug fix)

### Firebase Auth Migration Completion (AUTH)

- [ ] **AUTH-01**: Every protected route accepts a valid Firebase ID token and resolves the correct authenticated user via the `TEXT`-keyed `auth.users` table
- [x] **AUTH-02**: A first-time Firebase login via `GET /api/auth/session` provisions `auth.users` + `user_profiles` rows and returns the profile; repeat calls with the same uid are idempotent (no duplicate rows) and reflect updated email
- [x] **AUTH-03**: A Firebase-authenticated user hitting a protected route before ever calling `/api/auth/session` gets `401 user_not_provisioned`; after calling it, the same route succeeds
- [ ] **AUTH-04**: `FIREBASE_PROJECT_ID` is documented in `.env.example`/`.env.local.example` and present in every active deployment target's environment/secrets
- [x] **AUTH-05**: Project docs (`CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, and related) describe Firebase — not Supabase JWT/JWKS — as the live auth mechanism

### Deployment Path Finalization (DEPLOY)

- [ ] **DEPLOY-01**: The Dokploy (or chosen target's) migration design is re-verified against the current Firebase-based `core/security.py`, correcting the pre-migration assumption that `SUPABASE_URL` is required for JWT auth
- [ ] **DEPLOY-02**: The chosen deployment target retains a working S3-compatible storage backend (MinIO or equivalent) — no upload/publish/share-read/encryption route fails due to missing storage config
- [ ] **DEPLOY-03**: A fresh, empty database on the chosen deployment target is bootstrapped with schema, RPCs, and the Firebase-uid migration before the app receives traffic
- [ ] **DEPLOY-04**: Deployment verification exercises a real authenticated request, a storage round-trip, and a rate-limited path — not just `GET /docs` and a bare 401 — before any rollback path is torn down
- [ ] **DEPLOY-05**: Deployment-facing docs (`DEPLOYMENT.md`, `CONFIGURATION.md`, `deployment-guide.md`, `system-architecture.md`, `codebase-summary.md`) consistently describe the same two-bucket storage layout (`html-files`, `shares`; thumbnails nested inside `html-files`)
- [ ] **DEPLOY-06**: The chosen deployment target enforces that the API is reachable only through Cloudflare Tunnel (e.g. `ClusterIP` service + in-cluster `cloudflared`, or a firewalled `NodePort`, or a shared-secret header check) — `core/rate_limit.py`'s IP-based limiters trust `CF-Connecting-IP` (per Phase 1's CR-01 fix), which is only trustworthy when direct access is actually blocked; `k8s/api.yaml`'s current `NodePort` on port 30080 does not enforce this

### Test Coverage & Reliability (TEST)

- [ ] **TEST-01**: `pytest-cov` (or equivalent) is configured, reports a coverage percentage on every run, and is enforced by a new CI workflow on push/PR
- [ ] **TEST-02**: Line coverage across `app/`, `core/`, and `models/` is at or above 80%, matching the PRD's own explicit v0.3.0 acceptance target
- [ ] **TEST-03**: `TESTING.md` and `DEVELOPMENT.md` are reconciled into one accurate description of which tests require live Postgres/MinIO and which don't, matching actual test behavior

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Performance & Observability

- **PERF-01**: Connection pooling for the Postgres/MinIO admin client (currently a fresh client per call)
- **PERF-02**: Redis cache for JWKS/shares to reduce repeated fetches
- **PERF-03**: CDN for static assets; read replicas / sharded storage at higher scale
- **OBS-01**: Structured request/response logging beyond current request-ID tracking
- **OBS-02**: Error/uptime monitoring (e.g. Sentry) — no APM/monitoring SDK currently bundled

### Platform Expansion

- **PLAT-01**: Admin dashboard (internal tooling)
- **PLAT-02**: Billing/subscription management
- **PLAT-03**: Webhooks
- **PLAT-04**: API v2

### Tooling Consolidation

- **CLI-01**: Decide whether to keep both `dropitx-api/cli/` (Node) and the sibling `dropitx-cli` (Python) or consolidate — flagged as open tech debt in `docs/project-roadmap.md`, no decision made yet

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Rich text editing | Frontend concern, lives in the `dropitx/` repo |
| Email delivery for team invites | Invite links are constructed here; delivery is external |
| User registration/sign-up UI | Handled by Firebase Auth on the frontend |
| Real-time collaboration | Eventual consistency only, by design |
| Billing/subscription management | Not yet implemented, no revenue model defined (tracked as v2 PLAT-02) |
| Admin dashboard | Internal tooling only, not built (tracked as v2 PLAT-01) |
| Frontend Firebase Google-sign-in wiring | Separate fast-follow spec (`docs/2026-08-12-firebase-google-login-implementation.md`) that lives in the `dropitx/` frontend repo |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | Phase 1 | Complete |
| SEC-02 | Phase 1 | Complete |
| SEC-03 | Phase 1 | Complete |
| SEC-04 | Phase 1 | Complete |
| SEC-05 | Phase 1 | Complete |
| SEC-06 | Phase 1 | Complete |
| AUTH-01 | Phase 2 | Pending |
| AUTH-02 | Phase 2 | Complete |
| AUTH-03 | Phase 2 | Complete |
| AUTH-04 | Phase 2 | Pending |
| AUTH-05 | Phase 2 | Complete |
| DEPLOY-01 | Phase 3 | Pending |
| DEPLOY-02 | Phase 3 | Pending |
| DEPLOY-03 | Phase 3 | Pending |
| DEPLOY-04 | Phase 3 | Pending |
| DEPLOY-05 | Phase 3 | Pending |
| DEPLOY-06 | Phase 3 | Pending |
| TEST-01 | Phase 4 | Pending |
| TEST-02 | Phase 4 | Pending |
| TEST-03 | Phase 4 | Pending |

**Coverage:**

- v1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0 ✓

---
*Requirements defined: 2026-08-15*
*Last updated: 2026-08-15 after initial roadmap creation (ingest-based)*
