# DropItX API — Product Design Record

## Problem Statement

Sharing HTML/Markdown content online requires either complex CMS setups or generic file-hosting services that lack text-specific features. Developers and teams need a lightweight way to share rendered HTML, markdown documents, and text snippets via public URLs with collaboration features, security, and discovery built in.

## Target Users

1. **Individual developers** — share code snippets, HTML prototypes, markdown notes via public links with optional encryption
2. **Teams** — collaborate on shared documents, manage membership, track analytics, brand with custom domains
3. **Programmatic users** — integrate via API keys for automated content publishing
4. **Enterprise users** — end-to-end encrypted shares, audit logs, fine-grained permissions

## Core Features (All Shipped)

### Content Sharing & Management
- Upload HTML/Markdown files (up to 50 MB)
- Publish editor content with custom slugs
- Auto-generate or set custom slugs
- Password-protect shares (bcrypt)
- One-time download (burn-after-reading)
- Download limits with tracking
- Share expiration (time-based)
- View tracking with analytics
- Multi-file shares (batch upload / share groups)
- Version history (full snapshots, edit tracking)

### Security & Privacy
- **E2E Encryption** — AES-256-GCM with PBKDF2 key derivation, zero-knowledge architecture
- Password protection (bcrypt hashed)
- API key authentication (`shk_` personal, `sht_` team)
- JWT-based team access control
- Role hierarchy (owner > editor > viewer)
- Custom domains with DNS verification
- Public/private share flags

### Team Collaboration
- Create and manage teams with URL slugs
- Invite members by email (bulk up to 50)
- Role-based access control
- Team-level API keys
- Shared document libraries
- Team event audit log
- Team member removal and permission changes

### Discovery & Analytics
- Full-text search across public shares
- Public explore gallery (trending, tag-filtered)
- User profiles (public, with shares)
- View tracking per share
- Star/favorite functionality
- oEmbed support for embeds
- Language detection (auto-tag by language)
- QR codes for shares

### File Management
- File request/upload links (WeTransfer-like)
- Bulk download (ZIP archives)
- File preview (images, PDF, code, markdown, video/audio, text)
- File type detection
- Automatic cleanup of expired uploads

### Programmatic API
- Personal API keys for automation
- Team API keys for collaborative workflows
- Full CRUD on documents
- Version/revision endpoints
- Stateless, rate-limited access

## User Stories (Implemented)

### Individual Users
- Upload an HTML file and get a shareable URL immediately ✅
- Protect my shared content with a password ✅
- Delete my shares using a token (no login) ✅
- Publish editor content with a custom URL ✅
- Encrypt my shares end-to-end with a password ✅
- Set my share to download only once (burn after read) ✅
- Limit downloads to N times ✅
- See who viewed my share (analytics) ✅
- Download my shares with a QR code ✅
- Tag my shares by language/topic ✅

### Team Members
- Create a team and invite collaborators ✅
- View all shares belonging to my team ✅
- Let editors and owners invite new members ✅
- See team activity in an event log ✅
- Use team API keys for automation ✅
- Request that others upload files to me ✅

### Team Owners
- Full control over team settings and membership ✅
- Assign roles (viewer, editor, owner) to members ✅
- Create custom domains for team shares ✅
- Remove members or delete the team ✅
- Verify custom domain ownership via DNS ✅

### API Consumers
- Create API keys from the dashboard ✅
- Full CRUD on documents via API ✅
- Team API keys for shared workflows ✅
- Version history endpoint for tracking changes ✅
- Rate-limited, fair-use access ✅

## Success Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Upload success rate | > 99.5% | Not measured (no monitoring yet) |
| API response time (p95) | < 500ms | Not measured |
| Search relevance | Relevant results for queries | Not measured |
| Uptime | 99.9% | Not measured |
| Test coverage | > 80% | ~25-30% (estimated) |

## Non-Functional Requirements

### Security
- **Authentication**: JWT via Firebase ID tokens (RS256, verified against Google's certs), API key SHA-256 hashing
- **Authorization**: Role-based (owner/editor/viewer), resource ownership checks
- **Encryption**: AES-256-GCM for E2E, bcrypt for passwords, TLS in transit
- **Rate Limiting**: Per-IP, per-endpoint, configurable fail-open/fail-closed
- **No Logging of Secrets**: JWT, API keys, service-role keys never logged

### Reliability
- **Compensating Transactions**: Storage cleanup on DB failure
- **Fail-Open Analytics**: Always track views, even if rate limit fails
- **Health Checks**: Liveness + deep (database connectivity)
- **Background Cleanup**: Expired shares/requests auto-deleted

### Scalability
- **Stateless**: No server-side sessions
- **Externalized Storage**: Supabase Postgres + Storage
- **Container Deployment**: Render with auto-scaling
- **Async I/O**: asyncio.to_thread for Supabase sync client
- **Rate Limiting via RPC**: Distributed, Postgres-backed

### Privacy
- **Password-Protected Shares**: Bcrypt verification
- **Private Documents**: Not returned in search
- **User Data Isolation**: RLS on Supabase (where applicable)
- **Optional Encryption**: User-controlled, server never sees plaintext

## Deployment

- **Platform**: Render (container, auto-scaling)
- **Database**: Supabase Postgres
- **Storage**: Supabase Storage (two buckets)
- **Auth**: Firebase (JWT issuance, Google-certs verification)
- **Language**: Python 3.12+
- **Framework**: FastAPI with uvicorn
- **Configuration**: `.env` based (Pydantic settings)

## Out of Scope

- Rich text editing (frontend concern)
- Email delivery (invite links constructed, delivery external)
- User registration (Firebase Auth on frontend)
- Real-time collaboration (eventual consistency only)
- Billing/subscription management (not yet implemented)
- Admin dashboard (internal tooling only)

## Technical Decisions

### Why Supabase?
- Postgres RLS for fine-grained access control
- Built-in Auth (JWT, Firebase)
- Storage + Database in one service
- Simple scaling model
- Fast iteration (migrations, APIs auto-generated)

### Why FastAPI?
- Async-native (asyncio)
- Automatic OpenAPI documentation
- Type hints for request/response validation
- Dependency injection (testing friendly)
- Performance competitive with Go/Node

### Why Postgres RPC?
- Atomic multi-table mutations
- Distributed rate limiting
- Search with ranking (full-text search)
- Reduces client-server roundtrips

### Why No ORM?
- Supabase Python client uses dict-based results
- SQL is clearer for complex queries
- Simpler to debug Postgres behavior
- No N+1 query problems

### Why E2E Encryption?
- Zero-knowledge architecture — server never sees plaintext
- PBKDF2 + AES-256-GCM industry standard
- User controls the key (password)
- GDPR compliant (data minimization)

## Constraints & Trade-offs

| Constraint | Impact | Mitigation |
|-----------|--------|-----------|
| Sync Supabase client | Threads needed for async | asyncio.to_thread, scales OK at current load |
| No connection pooling | Fresh admin client per call | Acceptable latency (<200ms typical) |
| Thin test coverage | Regression risk | Manual QA, CI/CD testing before release |
| Dual CLI implementation | Confusion for users | Document which is canonical (TBD) |
| Inline Pydantic models | Code duplication | Extract shared DTOs as patterns emerge |

## Acceptance Criteria (For v0.3.0)

- [x] Core sharing (upload, delete, password)
- [x] Team collaboration (CRUD, invites, roles)
- [x] API authentication (JWT, API keys)
- [x] E2E encryption (AES, PBKDF2)
- [x] Version history (snapshots, rollback)
- [x] Discovery (search, explore, profiles)
- [x] File management (multi-upload, preview, requests)
- [x] Analytics (tracking, QR codes, language)
- [x] Deployment (Render blueprint, health checks)
- [x] OpenAPI docs (`/docs`, `/redoc`)
- [x] Structured error responses (consistent JSON envelope with error codes)
- [ ] Test coverage > 80% (priority for next sprint)
