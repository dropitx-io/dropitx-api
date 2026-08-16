# Project Roadmap

## Current Status: Alpha (v0.3.0)

**All core features are implemented and deployed.** The API is production-ready for file sharing, team collaboration, and programmatic access. Current focus is on test coverage and reliability hardening.

## Shipped Features

### Phase 1 — Foundation (Complete)
- [x] FastAPI project scaffolding
- [x] Supabase client factory (user/admin/anon)
- [x] Pydantic settings from `.env`
- [x] CORS middleware
- [x] Health check endpoints (`/health`, `/health/deep`)
- [x] Structured error responses
- [x] Request tracking and logging

### Phase 2 — Core Sharing (Complete)
- [x] File upload (HTML/MD, up to 50 MB)
- [x] Editor publish (custom slugs, rate-limited)
- [x] Plain text extraction (HTML and Markdown)
- [x] Slug and delete token generation
- [x] Storage with compensating transactions
- [x] Share password protection (bcrypt)
- [x] Share deletion (JWT owner or delete token)
- [x] One-time download flag (max_downloads)
- [x] Download count tracking

### Phase 3 — Authentication (Complete)
- [x] JWT verification (Firebase ID token, RS256)
- [x] API key generation (`shk_`/`sht_` prefixes)
- [x] API key validation and revocation
- [x] API key management (CRUD)
- [x] Per-key usage tracking (`last_used_at`)

### Phase 4 — Team Collaboration (Complete)
- [x] Team CRUD (create, get, update, delete)
- [x] Team member management
- [x] Role hierarchy (owner > editor > viewer)
- [x] Team invites (create, list, revoke, bulk, resend)
- [x] Team events audit log
- [x] Team shares listing
- [x] Team API keys

### Phase 5 — Content Features (Complete)
- [x] E2E encryption (AES-256-GCM, PBKDF2, zero-knowledge)
- [x] Burn-after-reading (one-time download)
- [x] Version history / revisions (full content snapshots)
- [x] Comments on shares
- [x] QR codes for shares
- [x] Language detection
- [x] Multi-file shares (share groups)
- [x] Custom domains for teams (with DNS verification)
- [x] File preview (images, PDF, code, markdown, media, text)

### Phase 6 — Discovery & Analytics (Complete)
- [x] Full-text search (Postgres RPC)
- [x] Public explore gallery (trending, filtered by tag)
- [x] User profiles (public, with shares)
- [x] View tracking
- [x] oEmbed discovery
- [x] Star/favorite shares
- [x] Rate limiting (configurable fail-open/fail-closed)

### Phase 7 — File Requests (Complete)
- [x] Create file request/upload links (inspired by WeTransfer)
- [x] Public upload to request link
- [x] List uploaded files
- [x] Download received files
- [x] Automatic cleanup of expired requests

### Phase 8 — Programmatic API (Complete)
- [x] Document CRUD via API key
- [x] Team document support
- [x] Version history endpoints
- [x] Revision snapshot retrieval

### Phase 9 — Deployment (Complete)
- [x] Render deployment blueprint
- [x] Interactive API docs (`/docs`, `/redoc`)
- [x] Environment variable configuration
- [x] Background cleanup service

## Known Gaps & Tech Debt

### Testing
- **Status**: ~8 test files, thin coverage (estimated <30%)
- **What's missing**: Integration tests for most routes, mocked Supabase client
- **Impact**: Risk of regressions; manual QA required before releases

### Error Handling
- **Status**: Basic HTTPException + global handler, logs are JSON in prod
- **What's missing**: Structured error codes per endpoint, error documentation in OpenAPI
- **Impact**: Clients can't reliably handle errors beyond status code

### Dual CLI Situation
- **Status**: Two independent CLI implementations coexist
  - `dropitx-api/cli/` — npm package (JS/Commander-based)
  - `dropitx-cli/` sibling repo — Python, separate codebase
- **Decision needed**: Keep both or consolidate? Current state creates confusion about which is canonical.
- **Impact**: Maintenance burden, unclear to users which to use

### Connection Pooling
- **Status**: Admin Supabase client created fresh per call
- **Impact**: Inefficient for high-frequency requests; not yet a bottleneck at current scale
- **Fix**: Consider Supabase Python client pooling or refactor to reuse client instance

### Inline Models
- **Status**: Some route files define Pydantic models inline instead of shared `models/`
- **Impact**: Duplication; cross-route reference harder
- **Fix**: Extract common DTOs to `models/` as patterns emerge

### Route Registration
- **Status**: `app/dashboard/team_invites.py` registers routes on `teams.py` router via side-effect import
- **Impact**: Implicit coupling; harder to trace route registration
- **Fix**: Explicit router aggregation in `dashboard/router.py`

## Next Priorities

### Short Term (Next Sprint)
1. **Test Coverage** — Unit + integration tests for core modules
   - `core/security.py` — JWT, API key, password verification
   - `core/encryption.py` — encryption/decryption, key derivation
   - `app/v1/documents.py` — document CRUD
   - `app/dashboard/teams.py` — team operations

2. **CI/CD Pipeline** — GitHub Actions for automated testing

3. **Error Documentation** — OpenAPI schema with error codes

### Medium Term (This Quarter)
1. **Structured Logging** — Request/response logging for audit trail
2. **Monitoring & Alerts** — Sentry integration, uptime monitoring
3. **Performance Optimization** — Query profiling, caching layer
4. **Documentation** — API endpoint walkthroughs, deployment runbooks

### Long Term (Next Quarter)
1. **Admin Dashboard** — Usage analytics, user management (internal only)
2. **Billing Integration** — Plan enforcement, quota management
3. **Webhooks** — Share events (created, viewed, deleted, commented)
4. **API Versioning** — v2 planning for breaking changes

## Version History

| Version | Date | Status | Notes |
|---------|------|--------|-------|
| 0.3.0 | 2026-07-01 | Alpha | All core features shipped; thin test coverage |
| 0.2.0 | 2026-05-31 | Alpha | Competitor features (encryption, burn, comments, versions) |
| 0.1.0 | 2026-05-02 | Alpha | Foundation + core sharing, auth, teams |
