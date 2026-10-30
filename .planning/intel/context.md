# Context

Running notes from the 14 DOC-classified documents, keyed by topic. Verbatim/paraphrased content with source attribution; no synthesis or reconciliation performed here (see `INGEST-CONFLICTS.md` for cross-doc tensions).

## Architecture (Supabase-JWT era)
- source: docs/ARCHITECTURE.md
- DropItX API is a FastAPI backend (Python ≥3.12, app v0.3.0), a thin stateless service layer over Supabase (Auth, Postgres, Storage). Layered, router-aggregated style: single FastAPI app mounts four versioned/scope routers (`v1/` API-key, `dashboard/` JWT, `public/` public/optional-JWT, `internal/` optional/required JWT). Consumers: Next.js frontend (`dropitx/`), Python CLI/MCP (`dropitx-cli/`), bundled Node CLI (`cli/`). Deployed to Render via `render.yaml`, `uvicorn app.main:app`. Single async background task runs periodic cleanup for expired content.
- Key abstractions: `Settings` (`core/config.py`); `get_admin_client()`/`get_user_client(token)`/`get_anon_client()` (`core/supabase.py`); `verify_supabase_jwt(token)` (`core/security.py`, RS256/ES256 against cached JWKS, 10-min TTL); `generate_api_key`/`hash_api_key`; `User`/`ApiKeyAuth` dataclasses (`app/dependencies.py`); `check_*_rate_limit` (`core/rate_limit.py`); `ErrorResponse`/`RateLimitError`/`ShareNotFoundError`/`SharePasswordRequired` (`core/exceptions.py`); `RequestTrackingMiddleware`/`SecurityHeadersMiddleware`; `require_team_member` (`app/dashboard/team_helpers.py`); `run_cleanup_loop()` (5-min interval — deletes expired shares, trims revisions >50/share, deactivates expired file requests).
- Directory layout split by **auth surface**, not domain: `app/v1`, `app/dashboard`, `app/public`, `app/internal`, `app/services`; `core/` is HTTP-agnostic; `models/` flat DTO package; two SQL dirs (`migrations/` incremental, `supabase/` base schema + CLI config).
- `<!-- VERIFY -->` marker in source: production Render service URL and Supabase project URL are not in the repo.

## System architecture (Supabase-JWT era, diagrammatic)
- source: docs/system-architecture.md
- Route groups under `/api`: `/v1/` (API Key), `/dashboard/` (JWT), unprefixed upload/publish/images/download/file-requests (JWT or none), `/shares/` (no auth / optional JWT for delete), `/encryption/`, `/search`, `/explore`, `/profiles/{handle}`, `/analytics/track`, `/oembed`, `/file-requests/`.
- Three Supabase client types: `get_user_client(token)` (RLS applies), `get_admin_client()` (bypasses RLS, used in all route handlers, fresh per call, no pooling), `get_anon_client()` (lazy-initialized, reused).
- Storage architecture: three buckets referenced — `html-files` (public, `shares/{slug}.html|.md`, used by `/api/upload` and `/api/publish`), `shares` (private, `{user_id}/{slug}`, used by v1 API documents), `thumbnails` (public, `shares/{slug}.jpg`, generated on-demand, auto-deleted with source). Storage architecture section header text explicitly says "15+ tables / 8 RPCs" and diagrams three buckets including `thumbnails`.
- Rate limiting: predefined limits — upload 10/min/IP (fail-open), publish 10/min/IP (fail-open), password unlock 5/10min/IP+slug (fail-closed), oEmbed 60/min/IP (fail-open), analytics 60/min/IP (fail-open). RPC `check_rate_limit(p_key, p_max_attempts, p_window_secs)` returns `{success, remaining, reset_at}`.
- Scaling: current bottlenecks — Supabase admin client fresh per call (no pooling), JWKS 10-min TTL, single-threaded Postgres full-text search, regex/ngram language detection (CPU-bound). Future improvements noted: connection pooling, Redis cache for JWKS/shares, CDN for static assets, read replicas, sharded storage.

## Codebase structure (Supabase-JWT era)
- source: docs/codebase-summary.md
- FastAPI app, v0.3.0, ~3,800 LOC across 50+ source files. Directory tree matches ARCHITECTURE.md's auth-surface split. Data model: 14 core tables listed (shares, api_keys, teams, team_members, team_invitations, team_events, team_shares, share_views, share_revisions, share_comments, share_groups, custom_domains, file_requests, profiles) and 9 Postgres RPCs (check_rate_limit, search_shares, create_team_invite, accept_team_invite, decline_team_invite, change_team_member_role, remove_team_member, increment_share_views, check_download_limit).
- Storage Buckets table lists **three** buckets: `html-files` (`shares/{slug}.html` or `.md` — upload & publish), `shares` (`{user_id}/{slug}` — v1 API document storage), `thumbnails` (`shares/{slug}.jpg` — generated previews).
- Testing: ~8 test files, ~25-30% estimated coverage; missing coverage on most route handlers, core modules (security, extract_text, rate_limit), error paths.
- `supabase/migrations/` (canonical, CLI-ordered: base schema, competitor features, file requests, schema fixes) vs `migrations/` (feature-specific fragments: encryption columns, share files, comments, revisions, custom domains, explore gallery, download-count RPC) — noted as "alternate location."

## Configuration (Supabase-JWT era)
- source: docs/CONFIGURATION.md
- All runtime config via env vars, Pydantic `BaseSettings` in `core/config.py`; no YAML/TOML app config. Required (startup fails if missing): `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`. Optional (defaults): `ALLOWED_ORIGINS` (`http://localhost:3000`), `FRONTEND_URL` (`http://localhost:3000`), `ENV` (`production`), `LOG_LEVEL` (`INFO`). Render-injected: `PYTHON_VERSION` (`3.12.0`), `PORT`.
- CORS: `ALLOWED_ORIGINS` comma-separated; `*` disables credentials and allows all origins; otherwise `allow_credentials=True`.
- Logging: `ENV=production` → JSON lines; else human-readable. Noisy loggers (`httpx`, `httpcore`, `uvicorn.access`, `uvicorn.error`) forced to `WARNING`.
- JWT verification (`core/security.py::verify_supabase_jwt`) fetches/caches JWKS from `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` for 10 minutes; supports RS256 and ES256; no env var controls this directly (derived from `SUPABASE_URL`).
- Rate limits are **not** env-driven — hardcoded constants in `core/rate_limit.py`: upload 10/60s open, password-unlock 5/600s closed, oEmbed 60/60s open, analytics 60/60s open.
- "Required Supabase resources" section lists exactly **two** storage buckets: `html-files`, `shares` (no `thumbnails` bucket mentioned) — see conflicts report re: bucket-count discrepancy.
- `<!-- VERIFY -->` markers: production values for `SUPABASE_URL`/`ALLOWED_ORIGINS`/`FRONTEND_URL`, and bucket/RPC/RLS details, live only in the Supabase dashboard, not the repo.

## Deployment — canonical Render reference (Supabase-JWT era)
- source: docs/DEPLOYMENT.md
- Self-declared as "the canonical deployment reference," stating `docs/deployment-guide.md` "overlaps but is superseded here for blueprint-driven deploys." See conflicts report (INFO, auto-resolved by explicit in-doc statement).
- Render is the *only* deployment target defined in the repo at time of writing — no Dockerfile/docker-compose/vercel.json/fly.toml/serverless.yml referenced by this doc. (Note: this workspace now also has `k8s/` manifests and a `docker-compose.yml`-based local stack, per the top-level project CLAUDE.md — this DOC predates or does not reflect that.)
- `render.yaml` defines exactly one `web` service, `python` runtime, `plan: free`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `PYTHON_VERSION=3.12.0`, five `sync: false` env vars (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`).
- Storage prerequisites: "Exactly **two** buckets must exist": `html-files` (public) and `shares` (private, thumbnails stored as objects *inside* `html-files` under `thumbnails/<base>_thumb.jpg`, not a separate bucket). This directly conflicts with `deployment-guide.md`, `system-architecture.md`, and `codebase-summary.md`, which describe a separate third `thumbnails` bucket — see conflicts report.
- Required Postgres RPCs: `check_rate_limit`, `search_shares`, `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member`, `increment_share_views`.
- RLS: three client types, `get_admin_client()` bypasses RLS (used by most routes); RLS policies defined across migration files.
- Health checks: `/health` (liveness) and `/health/deep` (pings `shares` table, reports `status: "degraded"` on failure — treat as failed deploy even if process is up).
- Rollback: Render dashboard rollback restores code; a bad deploy triggered by a Supabase migration is **not** undone by code rollback — schema must be reverted manually; `supabase db reset` deletes data (non-production only).
- Monitoring: Render Logs tab, JSON lines in production via `core/logging_config.py`; no external monitoring SDK bundled (no Sentry/Datadog/New Relic/OpenTelemetry in `requirements.txt`).

## Deployment guide — step-by-step (Supabase-JWT era, older doc)
- source: docs/deployment-guide.md
- Prerequisites: Supabase project (Auth+Postgres+Storage), migrations applied, storage buckets `html-files`, `shares`, **`thumbnails`** (three buckets — conflicts with DEPLOYMENT.md's "exactly two"), Python 3.12+, Git repo.
- Same required/optional env vars as CONFIGURATION.md/DEPLOYMENT.md.
- Local dev steps: venv, `pip install -r requirements.txt`, `pip install -e ".[dev]"`, copy `.env.example`, `uvicorn app.main:app --reload --port 8000`.
- Render deployment: Blueprint (recommended) or manual Web Service setup; same `render.yaml` shown as DEPLOYMENT.md.
- Scaling table: current limits (50 MB/upload, same rate limits as elsewhere, ~10 DB connections / 1 GB storage on Supabase free tier) and an upgrade path table (free tier → Render standard + Supabase team → Render pro + Supabase enterprise + CDN at 10k+ req/min).
- Troubleshooting section: build failures, 502s, auth failures (401 causes: JWT signature mismatch, key not found, revoked), storage upload failures (bucket not found/permission denied/quota exceeded), rate-limit-not-working (missing RPC), search-returns-empty (missing RPC), CORS errors, high memory usage.

## Design guidelines
- source: docs/design-guidelines.md
- API design: resources as nouns, HTTP verbs map to CRUD, sub-resources via path, actions as POST (`/shares/{slug}/set-password`, `/unlock`, `/analytics/track`). Errors as FastAPI `HTTPException` `{"detail": "..."}`; status codes 400/401/403/404/409/410/422/429/500 enumerated with meanings.
- Naming: kebab-case URL paths, plural nouns for collections, snake_case query params and body fields, PascalCase Pydantic model names / snake_case fields, snake_case DB columns (`{table}_id` FK convention, `created_at`/`updated_at`/`expires_at`), RPC params prefixed `p_`.
- Security: JWT via JWKS (not shared secret) with audience = Supabase URL; API keys raw-once + SHA-256 hash storage; `secrets` module for token generation; resource ownership verified server-side; team role hierarchy numeric (owner 3 > editor 2 > viewer 1); team key validation checks current membership; optional-auth endpoints treat anonymous users as read-only.
- Data protection: bcrypt 12 rounds for passwords; SHA-256 for API keys; delete tokens single-use 32-char hex; service-role key never exposed.
- Rate limiting table (same limits as elsewhere) with rationale column (fail-open = availability > security; fail-closed = security > availability).
- Storage design: bucket strategy — `html-files` (public, upload/publish) vs `shares` (API-mediated, v1 documents); file path conventions; compensating-transaction pattern (upload → DB insert → on DB failure, remove uploaded file, log cleanup failures, never mask original error).
- Dependencies: minimize external deps — regex-based text extraction (not BeautifulSoup/lxml), `python-jose` (not PyJWT) for JWT, `httpx` only for JWKS fetch, no ORM. No state in API beyond the 10-min JWKS cache; no sessions; all data externalized to Supabase; deployable on stateless serverless platforms.

## Code standards
- source: docs/code-standards.md
- File naming: kebab-case, descriptive, single responsibility, <200 LOC per file.
- Python conventions: 3.12+ syntax (`|` union types), `from __future__ import annotations` at top of every module, type all signatures, `logging` module never `print`, f-strings only.
- Import order: stdlib → third-party → local (`core.*`, `app.*`, `models.*`), blank line between groups.
- FastAPI patterns: routes grouped by auth type in subdirectories with a `router.py` re-export; `Depends(get_current_user)`/`get_optional_user`/`get_api_key`; inline Pydantic DTOs for simple cases, shared `models/` for cross-route; `HTTPException` with specific codes; catch `Exception` broadly at route level, log via `logger.error`, re-raise as 500 with generic message; every Supabase call wrapped in `asyncio.to_thread(lambda: ...)`; fire-and-forget via `asyncio.create_task()` for non-critical updates; compensating-transaction pattern for storage+DB failures.
- Database patterns: `get_admin_client()` in route handlers (bypasses RLS), `get_user_client(token)` only when RLS should apply, never store/log service-role key; RPCs for atomic/complex operations.
- Security standards: JWT verified against Supabase JWKS (RS256, audience = Supabase URL); API keys SHA-256 hashed; passwords bcrypt 12 rounds; team roles numeric hierarchy; rate limiting fail-closed for password unlock, fail-open for analytics/upload.
- Logging: module-level logger per file; error/warning/debug level conventions; never log secrets/tokens/passwords/service-role key.

## Development workflow (Supabase-JWT era)
- source: docs/DEVELOPMENT.md
- Local setup: Python 3.12+, Supabase project (Auth+Postgres+Storage), venv, `pip install -r requirements.txt` + `pip install -e ".[dev]"` (or `uv sync`), `.env` from `.env.example`, three required vars.
- Dev server: `uvicorn app.main:app --reload` on `http://127.0.0.1:8000`; `--reload` does not pick up `.env` changes (manual restart needed).
- Commands table: dev server, production-style start, `pytest` variants, dependency install commands. No `Makefile`, no `[project.scripts]`.
- Testing section (**note — differs from `TESTING.md`, see conflicts report**): "Most endpoint tests do **not** require a live Supabase connection" via `ASGITransport`; "Tests that touch Supabase-typed paths assert against the realistic status set (e.g. `assert resp.status_code in (200, 500)`) rather than mocking the client, so the suite passes whether or not Supabase is reachable." Pure-logic tests (`test_encryption.py`) are fully deterministic. No shared `tests/helpers` or `conftest.py` today.
- Code style: enforced by convention only — no Ruff/Black/isort/Flake8/Mypy/Pyright/`.editorconfig`/lint-format-typecheck scripts exist. `python -m compileall app core models` + `pytest` as the effective local gate.
- Project layout: same auth-surface split as ARCHITECTURE.md; four surfaces mapped to four prefixes table.
- Async/sync bridge described as "the single most load-bearing convention in the codebase."
- No branch-naming convention, `CONTRIBUTING.md`, or PR template checked in; no CI workflow (no `.github/workflows/`).

## Getting started (Supabase-JWT era)
- source: docs/GETTING-STARTED.md
- Prerequisites: Python 3.12+, pip, a Supabase project with Auth/Postgres/Storage, two storage buckets (`html-files`, `shares`), the RPC list, and Supabase project URL/anon key/service-role key. Explicitly: "No Node.js, Docker, or Redis is required for local development."
- Install → configure `.env` → `uvicorn app.main:app --reload` → verify `/health` and `/health/deep` → run `pytest` → first API call examples (public `/api/search`, authenticated `/api/v1/documents` via API key).
- Common setup issues: missing env vars, wrong Python version, CORS errors (frontend origin not in `ALLOWED_ORIGINS`), `/health/deep` degraded (bad Supabase URL/key or missing buckets/RPCs), missing pytest (need `pip install -e ".[dev]"`).

## Project roadmap
- source: docs/project-roadmap.md
- Current status: Alpha v0.3.0, "all core features implemented and deployed," current focus is test coverage and reliability hardening.
- Shipped phases 1–9 (Foundation, Core Sharing, Authentication, Team Collaboration, Content Features, Discovery & Analytics, File Requests, Programmatic API, Deployment) — all marked complete with itemized checklists.
- Known gaps/tech debt: thin test coverage (~8 files, <30% estimated); basic error handling (no per-endpoint structured error codes); dual CLI situation (`dropitx-api/cli/` npm JS vs `dropitx-cli/` sibling Python repo — "decision needed: keep both or consolidate?"); no connection pooling for admin Supabase client; inline Pydantic models causing duplication; implicit route registration via side-effect import in `app/dashboard/team_invites.py`.
- Next priorities: short term — test coverage, CI/CD pipeline, error documentation; medium term — structured request/response logging, Sentry/uptime monitoring, performance/caching, documentation; long term — admin dashboard, billing integration, webhooks, API v2.
- Version history: 0.3.0 (2026-07-01, all core features + thin coverage), 0.2.0 (2026-05-31, competitor features), 0.1.0 (2026-05-02, foundation + core sharing/auth/teams).

## Testing (claims fully-mocked suite — see conflicts report)
- source: docs/TESTING.md
- States the suite "exercises the FastAPI app and its core logic **without ever hitting a live Supabase backend**. Supabase clients, configuration, and auth dependencies are mocked so the suite runs offline and fast." No `.env` required because `core.config.settings` is mocked.
- Tooling: pytest ≥8.0, pytest-asyncio ≥0.24, httpx ≥0.28.0, Python ≥3.12; `asyncio_mode = "auto"`, `testpaths = ["tests"]`; no project-level `conftest.py`.
- Two test patterns: (1) HTTP-level via `ASGITransport`/`AsyncClient` (also Starlette `TestClient` in `test_file_requests.py`) for route existence/validation/response shape; (2) pure unit tests (`test_encryption.py`) with no I/O.
- Mocking strategy: (a) patch `get_admin_client`/`get_user_client`/`get_anon_client` at the call site with `MagicMock` query-builder chains; (b) mock `core.config.settings` via autouse fixture with fake Supabase config; (c) override `get_current_user` via `app.dependency_overrides` rather than forging JWTs.
- No coverage tooling configured (no `pytest-cov`, no `.coveragerc`); no CI pipeline runs the suite (no `.github/workflows/` in this repo — the sibling `dropitx-cli/` repo's CI does not test this API).

## Firebase Google Sign-In — frontend implementation plan (in-progress migration)
- source: docs/2026-08-12-firebase-google-login-implementation.md
- cross_ref: docs/2026-08-12-firebase-auth-backend-api-design.md (sibling backend design doc)
- Flow: user clicks "Sign in with Google" → Firebase Web SDK (`signInWithPopup` + `GoogleAuthProvider`) → Google OAuth consent → Firebase issues ID token (JWT, ~1hr TTL) → frontend tracks state via `onAuthStateChanged` → every API call to `https://api.dropitx.site` includes `Authorization: Bearer <firebase_id_token>` → backend verifies via `verify_firebase_jwt` (`aud=dropitx-io`, `iss=https://securetoken.google.com/dropitx-io`, RS256).
- Phase 1 (Firebase Console, user-performed): enable Google provider in project `dropitx-io`, add authorized domains (`localhost`, `dropitx.site`, `www.dropitx.site`), copy web app config values → `NEXT_PUBLIC_FIREBASE_*` env vars.
- Phase 2 (Frontend code): `npm install firebase`; `lib/firebase.ts` (client SDK init); `lib/auth.ts` (`signInWithGoogle` popup-with-redirect-fallback, `handleRedirectResult`, `signOut`); `lib/api.ts` (`authenticatedFetch` wrapper attaching `Authorization: Bearer <idToken>`); `components/AuthProvider.tsx` (React context, `onAuthStateChanged`); login button component; replace all existing Supabase auth calls (`supabase.auth.signInWithPassword`/`signOut`/`getUser`/`getSession`) with Firebase equivalents; token refresh handled automatically by Firebase SDK's `getIdToken()`.
- Phase 3 (env vars): `NEXT_PUBLIC_FIREBASE_API_KEY/AUTH_DOMAIN/PROJECT_ID/STORAGE_BUCKET/MESSAGING_SENDER_ID/APP_ID`, `NEXT_PUBLIC_API_URL=https://api.dropitx.site`.
- Key decisions (doc's own, non-ADR — no `locked` field, DOC-classified): popup primary with redirect fallback (Safari/mobile, per Firebase docs recommendation); Bearer token in Authorization header per call, not session cookies (SPA calling an external-domain API); no Firebase Admin SDK on the frontend (backend already verifies).
- Verification steps and gotchas: Safari ITP breaks popup (redirect fallback handles it); ID tokens expire ~1hr, `getIdToken()` auto-refreshes (don't cache yourself); must enable Google provider in Console first or get `auth/operation-not-allowed`; authorized domains must include the frontend domain or redirect fails; use `window.location.href` (not `router.push()`) after login so middleware/SSR sees new auth state.

## Competitor feature gap plan (shipped — historical)
- source: docs/plans/2026-05-30-competitor-features.md
- Task-by-task backend+frontend implementation plan to close feature gaps with WeTransfer/SendAnywhere-style competitors: multi-file upload, general file type support, download limits, custom expiration, QR codes, bulk zip download, comments, version history. Per `project-roadmap.md`, this plan corresponds to the now-shipped "Phase 5 — Content Features" and related items (0.2.0, 2026-05-31). Classified DOC (task-list execution plan with concrete file paths/schema/endpoint detail) rather than SPEC, per the upstream classifier's notes (no dominant endpoint-contract/schema-table structure).
