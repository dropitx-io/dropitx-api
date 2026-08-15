# Requirements

Extracted from the sole PRD-classified document: `docs/project-overview-pdr.md` ("DropItX API — Product Design Record"). One requirement entry per section of that document, mirroring its own structure.

## REQ-product-scope
- source: docs/project-overview-pdr.md
- description: Problem statement — sharing HTML/Markdown content online requires either complex CMS setups or generic file-hosting services lacking text-specific features; developers and teams need a lightweight way to share rendered HTML, markdown documents, and text snippets via public URLs with collaboration, security, and discovery built in. Target users: (1) individual developers — code snippets, HTML prototypes, markdown notes, optional encryption; (2) teams — shared documents, membership management, analytics, custom-domain branding; (3) programmatic users — API-key-driven automated publishing; (4) enterprise users — E2E encrypted shares, audit logs, fine-grained permissions.
- acceptance: (absent — scope/context section, no checklist)
- scope: individual developers, teams, programmatic users, enterprise users

## REQ-content-sharing-management
- source: docs/project-overview-pdr.md
- description: Upload HTML/Markdown files (up to 50 MB); publish editor content with custom slugs; auto-generate or set custom slugs; password-protect shares (bcrypt); one-time download (burn-after-reading); download limits with tracking; share expiration (time-based); view tracking with analytics; multi-file shares (batch upload / share groups); version history (full snapshots, edit tracking).
- acceptance: Marked shipped (✅ in doc) under "Core Features (All Shipped)"; corresponds to master checklist items "Core sharing (upload, delete, password)" and "Version history (snapshots, rollback)" in Acceptance Criteria (For v0.3.0).
- scope: content sharing, individual developers, teams

## REQ-security-privacy
- source: docs/project-overview-pdr.md
- description: E2E encryption — AES-256-GCM with PBKDF2 key derivation, zero-knowledge architecture; password protection (bcrypt hashed); API key authentication (`shk_` personal, `sht_` team); JWT-based team access control; role hierarchy (owner > editor > viewer); custom domains with DNS verification; public/private share flags.
- acceptance: Marked shipped; corresponds to master checklist item "E2E encryption (AES, PBKDF2)".
- scope: security, e2e encryption, enterprise users

## REQ-team-collaboration
- source: docs/project-overview-pdr.md
- description: Create and manage teams with URL slugs; invite members by email (bulk up to 50); role-based access control; team-level API keys; shared document libraries; team event audit log; team member removal and permission changes.
- acceptance: Marked shipped; corresponds to master checklist item "Team collaboration (CRUD, invites, roles)".
- scope: team collaboration, teams

## REQ-discovery-analytics
- source: docs/project-overview-pdr.md
- description: Full-text search across public shares; public explore gallery (trending, tag-filtered); user profiles (public, with shares); view tracking per share; star/favorite functionality; oEmbed support for embeds; language detection (auto-tag by language); QR codes for shares.
- acceptance: Marked shipped; corresponds to master checklist item "Discovery (search, explore, profiles)".
- scope: discovery and analytics

## REQ-file-management
- source: docs/project-overview-pdr.md
- description: File request/upload links (WeTransfer-like); bulk download (ZIP archives); file preview (images, PDF, code, markdown, video/audio, text); file type detection; automatic cleanup of expired uploads.
- acceptance: Marked shipped; corresponds to master checklist item "File management (multi-upload, preview, requests)".
- scope: file management

## REQ-programmatic-api
- source: docs/project-overview-pdr.md
- description: Personal API keys for automation; team API keys for collaborative workflows; full CRUD on documents; version/revision endpoints; stateless, rate-limited access.
- acceptance: Marked shipped; corresponds to master checklist items "API authentication (JWT, API keys)" and "OpenAPI docs (/docs, /redoc)".
- scope: API keys, programmatic users

## REQ-user-stories-individual-users
- source: docs/project-overview-pdr.md
- description: Upload an HTML file and get a shareable URL immediately; protect shared content with a password; delete shares using a token (no login); publish editor content with a custom URL; encrypt shares end-to-end with a password; set share to download only once (burn after read); limit downloads to N times; see who viewed a share (analytics); download shares with a QR code; tag shares by language/topic.
- acceptance: All items marked ✅ (Implemented) in doc.
- scope: individual developers

## REQ-user-stories-team-members
- source: docs/project-overview-pdr.md
- description: Create a team and invite collaborators; view all shares belonging to my team; let editors and owners invite new members; see team activity in an event log; use team API keys for automation; request that others upload files to me.
- acceptance: All items marked ✅ (Implemented) in doc.
- scope: teams

## REQ-user-stories-team-owners
- source: docs/project-overview-pdr.md
- description: Full control over team settings and membership; assign roles (viewer, editor, owner) to members; create custom domains for team shares; remove members or delete the team; verify custom domain ownership via DNS.
- acceptance: All items marked ✅ (Implemented) in doc.
- scope: teams, team owners

## REQ-user-stories-api-consumers
- source: docs/project-overview-pdr.md
- description: Create API keys from the dashboard; full CRUD on documents via API; team API keys for shared workflows; version history endpoint for tracking changes; rate-limited, fair-use access.
- acceptance: All items marked ✅ (Implemented) in doc.
- scope: programmatic users

## REQ-nfr-security
- source: docs/project-overview-pdr.md
- description: Authentication — JWT via Supabase JWKS (RS256), API key SHA-256 hashing. Authorization — role-based (owner/editor/viewer), resource ownership checks. Encryption — AES-256-GCM for E2E, bcrypt for passwords, TLS in transit. Rate Limiting — per-IP, per-endpoint, configurable fail-open/fail-closed. No logging of secrets — JWT, API keys, service-role keys never logged.
- acceptance: (absent — NFR statement, not itemized in the v0.3.0 checklist)
- scope: security (non-functional)

## REQ-nfr-reliability
- source: docs/project-overview-pdr.md
- description: Compensating transactions — storage cleanup on DB failure. Fail-open analytics — always track views, even if rate limit fails. Health checks — liveness + deep (database connectivity). Background cleanup — expired shares/requests auto-deleted.
- acceptance: (absent — NFR statement, not itemized in the v0.3.0 checklist)
- scope: reliability (non-functional)

## REQ-nfr-scalability
- source: docs/project-overview-pdr.md
- description: Stateless — no server-side sessions. Externalized storage — Supabase Postgres + Storage. Container deployment — Render with auto-scaling. Async I/O — asyncio.to_thread for Supabase sync client. Rate limiting via RPC — distributed, Postgres-backed.
- acceptance: (absent — NFR statement, not itemized in the v0.3.0 checklist)
- scope: scalability (non-functional)

## REQ-nfr-privacy
- source: docs/project-overview-pdr.md
- description: Password-protected shares — bcrypt verification. Private documents — not returned in search. User data isolation — RLS on Supabase (where applicable). Optional encryption — user-controlled, server never sees plaintext.
- acceptance: (absent — NFR statement, not itemized in the v0.3.0 checklist)
- scope: privacy (non-functional)

## REQ-deployment-target
- source: docs/project-overview-pdr.md
- description: Platform — Render (container, auto-scaling); Database — Supabase Postgres; Storage — Supabase Storage (two buckets); Auth — Supabase Auth (JWT issuance, JWKS); Language — Python 3.12+; Framework — FastAPI with uvicorn; Configuration — `.env` based (Pydantic settings).
- acceptance: Corresponds to master checklist item "Deployment (Render blueprint, health checks)".
- scope: deployment
- note: This describes the Supabase-Auth-era deployment target as stated in the PRD. See CONFLICTS report — the in-progress Firebase Auth migration (SPEC `docs/2026-08-12-firebase-auth-backend-api-design.md`) changes the Auth line item; this PRD has not been updated to reflect that migration.

## REQ-out-of-scope
- source: docs/project-overview-pdr.md
- description: Rich text editing (frontend concern); email delivery (invite links constructed, delivery external); user registration (Supabase Auth on frontend); real-time collaboration (eventual consistency only); billing/subscription management (not yet implemented); admin dashboard (internal tooling only).
- acceptance: (absent — explicitly out of scope, no acceptance criteria)
- scope: out of scope

## REQ-technical-rationale
- source: docs/project-overview-pdr.md
- description: Why Supabase — Postgres RLS, built-in Auth (JWT/JWKS), Storage+DB in one service, simple scaling, fast iteration. Why FastAPI — async-native, automatic OpenAPI docs, type-hint validation, DI (testing friendly), performance competitive with Go/Node. Why Postgres RPC — atomic multi-table mutations, distributed rate limiting, ranked full-text search, fewer client-server roundtrips. Why No ORM — Supabase client uses dict-based results, SQL clearer for complex queries, simpler debugging, no N+1 problems. Why E2E Encryption — zero-knowledge architecture, PBKDF2 + AES-256-GCM industry standard, user controls the key, GDPR data minimization.
- acceptance: (absent — rationale narrative, not an acceptance-bearing requirement)
- scope: technical rationale

## REQ-constraints-tradeoffs
- source: docs/project-overview-pdr.md
- description: Sync Supabase client → threads needed for async (mitigation: asyncio.to_thread, acceptable at current load). No connection pooling → fresh admin client per call (mitigation: acceptable latency <200ms typical). Thin test coverage → regression risk (mitigation: manual QA, CI/CD testing before release). Dual CLI implementation → confusion for users (mitigation: document which is canonical — TBD). Inline Pydantic models → code duplication (mitigation: extract shared DTOs as patterns emerge).
- acceptance: (absent — constraint/trade-off table, not an acceptance-bearing requirement)
- scope: constraints and trade-offs

## REQ-success-metrics
- source: docs/project-overview-pdr.md
- description: Upload success rate target >99.5% (not measured, no monitoring yet). API response time (p95) target <500ms (not measured). Search relevance target "relevant results for queries" (not measured). Uptime target 99.9% (not measured). Test coverage target >80% (actual ~25-30%, estimated).
- acceptance: (absent — metrics table describes targets/status, not pass/fail acceptance criteria)
- scope: success metrics

## REQ-acceptance-v030
- source: docs/project-overview-pdr.md
- description: Master "Acceptance Criteria (For v0.3.0)" checklist from the PRD.
- acceptance: [x] Core sharing (upload, delete, password); [x] Team collaboration (CRUD, invites, roles); [x] API authentication (JWT, API keys); [x] E2E encryption (AES, PBKDF2); [x] Version history (snapshots, rollback); [x] Discovery (search, explore, profiles); [x] File management (multi-upload, preview, requests); [x] Analytics (tracking, QR codes, language); [x] Deployment (Render blueprint, health checks); [x] OpenAPI docs (/docs, /redoc); [x] Structured error responses (consistent JSON envelope with error codes); [ ] Test coverage > 80% (priority for next sprint, unchecked/incomplete).
- scope: v0.3.0 release acceptance
