# Project Roadmap

## Current Status: Alpha

Core functionality is implemented and deployable. The API supports file sharing, team collaboration, and programmatic access.

## Completed Features

### Phase 1 — Foundation (Complete)
- [x] FastAPI project scaffolding
- [x] Supabase client factory (user/admin/anon)
- [x] Pydantic settings from `.env`
- [x] CORS middleware configuration
- [x] Health check endpoint (`/health`)

### Phase 2 — Core Sharing (Complete)
- [x] File upload endpoint (HTML/MD, up to 50 MB)
- [x] Editor publish endpoint (authenticated, custom slugs)
- [x] Plain text extraction from HTML and Markdown
- [x] Slug and delete token generation
- [x] Storage upload with compensating transactions
- [x] Share password protection (bcrypt)
- [x] Share deletion (JWT owner or delete token)

### Phase 3 — Authentication (Complete)
- [x] JWT verification via Supabase JWKS
- [x] `get_current_user` dependency (required JWT)
- [x] `get_optional_user` dependency (optional JWT)
- [x] API key generation (`shk_`/`sht_` prefixes)
- [x] API key validation (hash lookup, revocation check)
- [x] API key management (create, list, revoke)

### Phase 4 — Team Collaboration (Complete)
- [x] Team CRUD (create, get, update, delete)
- [x] Team member management (list, role change, remove)
- [x] Role hierarchy (owner > editor > viewer)
- [x] Team invites (create, list, revoke, bulk, resend)
- [x] Invite accept/decline via RPC
- [x] Team events log
- [x] Team shares listing

### Phase 5 — Discovery & Analytics (Complete)
- [x] Full-text search via Postgres RPC
- [x] View tracking (always 200, fail-open)
- [x] oEmbed discovery endpoint
- [x] Rate limiting (Postgres RPC, fail-open/fail-closed)

### Phase 6 — Programmatic API (Complete)
- [x] Document CRUD via API key auth
- [x] Team document support via `team_shares`
- [x] Team API keys with membership verification

### Phase 7 — Deployment (Complete)
- [x] Vercel deployment configuration
- [x] Render deployment blueprint (`render.yaml`)
- [x] Interactive API docs (`/docs`, `/redoc`)

## In Progress

- [ ] Test suite expansion (current coverage TBD)

## Upcoming — Short Term

### Phase 8 — Testing & Quality
- [ ] Unit tests for core modules (security, extract_text, nanoid, rate_limit)
- [ ] Integration tests for route handlers
- [ ] Mock Supabase client for test isolation
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Pre-commit hooks (linting, formatting)

### Phase 9 — Reliability
- [ ] Structured error responses (error codes, not just messages)
- [ ] Request/response logging middleware
- [ ] Health check with dependency status (Supabase connectivity)
- [ ] Retry logic for transient Supabase failures

## Upcoming — Medium Term

### Phase 10 — Features
- [ ] Webhook support for share events (created, viewed, deleted)
- [ ] Share analytics dashboard endpoint (aggregated stats)
- [ ] Custom domain support for share URLs
- [ ] Share versioning / history
- [ ] Batch operations (bulk delete, bulk update)

### Phase 11 — Scale
- [ ] Caching layer for frequently accessed shares
- [ ] CDN integration for storage files
- [ ] Request throttling per API key (not just IP)
- [ ] Pagination cursor support (in addition to offset)

### Phase 12 — Platform
- [ ] Usage quotas per user/team
- [ ] Plan enforcement (free vs pro limits)
- [ ] Team billing integration
- [ ] Admin dashboard endpoints

## Milestones

| Milestone | Target | Status |
|-----------|--------|--------|
| M1: Upload + share | Core sharing working | Done |
| M2: Auth + teams | Full team collaboration | Done |
| M3: API + deploy | Programmatic access, production deploy | Done |
| M4: Test coverage | 80%+ code coverage | Upcoming |
| M5: Production hardening | Error handling, logging, monitoring | Upcoming |

## Tech Debt

- Some route handlers define inline Pydantic models instead of shared DTOs
- `team_invites.py` registers routes on `teams.py` router via side-effect import — implicit coupling
- Admin client created fresh each call (no connection pooling)
- No structured error response format
- Analytics endpoint returns always-200 without distinguishing between tracked/not-tracked in response status
