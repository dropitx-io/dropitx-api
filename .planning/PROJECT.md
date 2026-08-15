# DropItX API

## What This Is

FastAPI backend for DropItX, a file/text sharing product with team collaboration. Users upload HTML/Markdown content or text, share it via public URLs (optionally password-protected or end-to-end encrypted), and collaborate in teams. Consumed by the Next.js frontend (`dropitx/`) and the Python CLI (`dropitx-cli/`); this repo owns only the backend service — frontend and CLI work happen in their sibling repos.

## Core Value

Let anyone go from "I have HTML/Markdown/text" to "here's a shareable, optionally password-protected/E2E-encrypted URL" in one API call, reliably — everything else (teams, search, analytics) is secondary to that core loop working.

## Requirements

### Validated

<!-- Shipped and confirmed working — inferred from codebase + PRD acceptance checklist (docs/project-overview-pdr.md, all items checked except test coverage). -->

- ✓ Content sharing & management (upload, publish, custom slugs, password protection, burn-after-reading, download limits, expiration, view tracking, multi-file/batch shares, version history) — shipped v0.1.0–v0.3.0
- ✓ Security & privacy primitives (E2E encryption AES-256-GCM + PBKDF2, bcrypt password protection, API key auth `shk_`/`sht_`, JWT-based team access, numeric role hierarchy, custom domains with DNS verification) — shipped v0.1.0–v0.3.0
- ✓ Team collaboration (team CRUD, bulk email invites, RBAC, team API keys, shared document libraries, team event audit log) — shipped v0.1.0–v0.3.0
- ✓ Discovery & analytics (full-text search, explore gallery, public profiles, view tracking, star/favorite, oEmbed, language detection, QR codes) — shipped v0.2.0–v0.3.0
- ✓ File management (file request/upload links, bulk ZIP download, file preview by type, type detection, auto-cleanup of expired uploads) — shipped v0.2.0–v0.3.0
- ✓ Programmatic API (personal/team API keys, full document CRUD, version/revision endpoints, rate-limited stateless access, OpenAPI docs) — shipped v0.1.0–v0.3.0
- ✓ Data + storage migrated off Supabase cloud to local PostgreSQL + MinIO via a hand-rolled PostgREST-compatible shim (`core/db.py`) — shipped, commit `7b7b8c3`
- ✓ Firebase ID-token verification wired into `core/security.py`, replacing Supabase JWKS verification for JWT auth — shipped, commit `da48448`

### Active

<!-- Current roadmap scope — the stabilization work needed after core features shipped. Full detail in REQUIREMENTS.md. -->

- [ ] Close the CRITICAL and HIGH findings from the 2026-08-12 security audit on public endpoints (unauthenticated share takeover, unrated bulk-download DoS, unrated public reads)
- [ ] Finish and verify the Firebase Auth backend migration end-to-end (provisioning, identity model, error handling) and reconcile docs that still describe Supabase JWT as the live auth mechanism
- [ ] Finalize one deployment path (k8s or Dokploy) with a working from-empty DB migration step and a verified auth+storage round-trip before any traffic cutover
- [ ] Reach the PRD's own stated >80% test coverage target with coverage tooling and CI enforcement, and reconcile the two conflicting testing-strategy docs

### Out of Scope

- Rich text editing — frontend concern, lives in the `dropitx/` repo
- Email delivery for team invites — invite links are constructed here; delivery is external
- User registration/sign-up UI — handled by Firebase Auth on the frontend
- Real-time collaboration — eventual consistency only, by design
- Billing/subscription management — not yet implemented, no revenue model defined
- Admin dashboard — internal tooling only, not built
- Frontend Firebase Google-sign-in wiring (`docs/2026-08-12-firebase-google-login-implementation.md`) — a separate fast-follow spec that lives in the `dropitx/` frontend repo, not this repo's scope

## Context

- **Backend is hybrid, mid-migration off Supabase cloud.** Data + storage now run on local PostgreSQL + MinIO. Auth was Supabase JWT/JWKS, then migrated to Firebase ID-token verification on the currently-checked-out branch `firebase-auth-backend-api` (commit `da48448`, 2026-08-12) — **not yet merged to `main`**. Several docs (`CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/DEVELOPMENT.md`, etc.) still describe the pre-migration Supabase-JWT model; `CLAUDE.md`'s working tree even states "JWT verification still calls out to a cloud Supabase project's JWKS endpoint," which is stale — `core/security.py` verifies Firebase tokens today.
- **Firebase Auth backend is substantially already implemented, not just designed.** `docs/2026-08-12-firebase-auth-backend-api-design.md` is marked "Design (awaiting spec sign-off)," but the schema migration (`migrations/007_firebase_uid_text.sql`), provisioning RPC (`migrations/008_provision_firebase_user.sql`), `get_firebase_claims` / provision-aware `get_current_user` (`app/dependencies.py`), and `GET /api/auth/session` (`app/auth/`) are all coded and covered by `tests/test_auth_session.py` and `tests/test_dependencies.py`. Treat remaining work as "verify, merge, and close doc gaps," not "design from scratch."
- **Security audit findings are still open.** `plans/reports/security-audit-260812-1452-public-endpoint-auth-ratelimit-report.md` (2026-08-12) flagged 2 CRITICAL + several HIGH/MEDIUM findings on public endpoints, now internet-reachable via Cloudflare Tunnel. Verified still unfixed while roadmapping: `app/public/encryption.py`'s `encrypt_share` (line 160) has no auth dependency and never calls the `_authorize_owner` helper defined in the same file; `app/internal/download.py`'s `bulk_download_group` (line 71) has no auth or rate limit.
- **Dokploy migration design review predates the Firebase Auth migration.** `plans/reports/spec-review-260812-1611-dokploy-migration-design-review.md` (2026-08-12, 16:14) reviewed a design assuming Supabase JWT auth; the actual Firebase auth migration commit (`da48448`) landed the same day at 21:34. Its Blocker B1 ("keep SUPABASE_URL, it's required for JWT auth") should be re-verified against the current Firebase-based `core/security.py` before being treated as still-accurate. Its storage (B2, MinIO/S3 required) and schema-migration (B3, no bootstrap step for a fresh Dokploy Postgres) blockers still appear to apply as-is.
- **Storage bucket count resolved: two buckets.** `core/thumbnail.py`'s own docstring confirms thumbnails live at `thumbnails/{storage_base}_thumb.jpg` **inside** the `html-files` bucket — matching `docs/DEPLOYMENT.md`/`docs/CONFIGURATION.md` ("exactly two buckets: `html-files`, `shares`"). `docs/deployment-guide.md`, `docs/system-architecture.md`, and `docs/codebase-summary.md` describing a separate third `thumbnails` bucket are stale.
- **Testing-strategy doc conflict is unresolved.** `docs/TESTING.md` claims the suite never hits a live backend; `docs/DEVELOPMENT.md` claims some tests tolerate one. The current `CLAUDE.md` states `tests/test_all_endpoints.py` is ASGI-only/no-DB while the other 9 test files hit real local Postgres/MinIO — which matches neither doc exactly and should be the basis for a single reconciled description.
- No CI pipeline exists (no `.github/workflows/`) and no coverage tooling is configured (no `pytest-cov`, no `.coveragerc`). Test file count is now 10 (up from the docs' claimed ~8, following the Firebase auth work's `test_auth_session.py`/`test_dependencies.py`).
- Two deployment paths currently exist in-repo: `render.yaml` (legacy, assumes cloud Supabase for data+storage too — predates the local-Postgres migration) and `k8s/` (actively developed, local Postgres+MinIO stack; `k8s/migrate-job.yaml` already globs `migrations/*.sql`, so it will pick up the Firebase-uid migration automatically). A third path, Dokploy, was designed and reviewed DONE_WITH_CONCERNS on 2026-08-12 with 3 blockers — no evidence it has been implemented.

## Constraints

- **Tech stack**: Python 3.12+, FastAPI + uvicorn. All DB/Storage calls wrapped in `asyncio.to_thread()` over a synchronous client shim (`core/db.py`) — the single most load-bearing convention in the codebase; don't remove without replacing the bridge everywhere it's used.
- **Auth dependency**: Firebase Auth (JWKS via Google) is required in every deployment target. `FIREBASE_PROJECT_ID` unset makes every login fail with a 401 ("FIREBASE_PROJECT_ID is not configured").
- **Storage dependency**: an S3-compatible backend (MinIO locally, or equivalent) is required for all storage-backed routes — 34 call sites across 18 files depend on it (upload, publish, share content, encryption, previews, versions, file requests, etc.). Cannot be dropped in any deployment migration.
- **No ORM**: dict-based query results via the Supabase-compatible shim; SQL/RPCs preferred for atomic multi-table mutations — established pattern, don't introduce an ORM.
- **Solo dev + Claude workflow**: no team ceremonies, sprints, or PM overhead in this roadmap.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Firebase uid stored as `TEXT` everywhere; no mapping table, no derived UUID | Firebase `sub` is a ~28-char string, not a UUID; avoids a shadow-identity table | ✓ Good (implemented, `migrations/007_firebase_uid_text.sql`) |
| `GET /api/auth/session` provisions on read (idempotent upsert), not a dedicated POST | Conventional `/session`/`/me` pattern; the upsert side-effect is safe and idempotent | ✓ Good (implemented; source doc itself flags method choice as revisitable) |
| `get_current_user` verifies + looks up but never writes; only `/api/auth/session` provisions | Keeps the auth dependency read-only and cheap (one indexed SELECT); provisioning stays explicit | ✓ Good (implemented) |
| Local Postgres + MinIO for data/storage; Supabase retained only for Auth, later superseded by Firebase for Auth too | Incremental migration off Supabase cloud without a big-bang cutover | ✓ Good (data/storage migration shipped `7b7b8c3`; Auth migration followed via `da48448`) |

---
*Last updated: 2026-08-15 after initial roadmap creation (ingest-based)*
