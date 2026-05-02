# DropItX API — Product Design Record

## Problem Statement

Sharing HTML/Markdown content online requires either complex CMS setups or generic file-hosting services that lack text-specific features. Developers and teams need a lightweight way to share rendered HTML, markdown documents, and text snippets via public URLs with collaboration features built in.

## Target Users

1. **Individual developers** — share code snippets, HTML prototypes, markdown notes via public links
2. **Teams** — collaborate on shared documents, manage team membership, track views
3. **Programmatic users** — integrate via API keys for automated content publishing

## Core Features

### Content Sharing
- Upload HTML/Markdown files (up to 50 MB)
- Publish content from an editor (up to 10 MB)
- Auto-generate or set custom slugs for share URLs
- Password-protect shares (bcrypt hashed)
- Set share expiry
- View tracking with analytics

### Team Collaboration
- Create/manage teams with URL slugs
- Invite members by email (bulk invites up to 50)
- Role-based access: owner, editor, viewer
- Team-level API keys
- Shared document libraries per team
- Team event log

### Programmatic Access
- Personal API keys (`shk_` prefix)
- Team API keys (`sht_` prefix)
- Full document CRUD via API
- API key revocation (soft-delete)

### Discovery
- Full-text search across public shares
- oEmbed support for embeds
- Rate limiting on all public endpoints

## User Stories

### As an individual user
- I want to upload an HTML file and get a shareable URL immediately
- I want to protect my shared content with a password
- I want to delete my shares using a token (no login required)
- I want to publish content from my editor and get a custom URL

### As a team member
- I want to create a team and invite collaborators via email
- I want to view all shares belonging to my team
- I want editors and owners to be able to invite new members
- I want to see who recently joined or what changed (event log)

### As a team owner
- I want full control over team settings and membership
- I want to assign roles (viewer, editor) to members
- I want to create team API keys for automated workflows
- I want to remove members or delete the team entirely

### As an API consumer
- I want to create a personal API key from the dashboard
- I want full CRUD on documents via the API
- I want to use team API keys for shared team documents

## Success Metrics

| Metric | Target |
|--------|--------|
| Upload success rate | > 99.5% |
| API response time (p95) | < 500ms |
| Search result relevance | Relevant results for common queries |
| Team invite acceptance | Track conversion from invite to join |
| Uptime | 99.9% |

## Non-Functional Requirements

- **Security**: JWT verification via JWKS, bcrypt password hashing, SHA-256 API key storage, rate limiting on sensitive endpoints
- **Reliability**: Compensating transactions for storage/DB consistency, fail-open rate limiting for non-critical paths
- **Scalability**: Stateless API, externalized auth/storage to Supabase, deployed on Render (container)
- **Privacy**: Password-protected shares, private documents not returned in search

## Out of Scope

- Rich text editing (frontend concern)
- Email delivery (invite links are constructed, delivery is external)
- User registration (handled by Supabase Auth on frontend)
- File preview/rendering (served directly from Supabase Storage public URLs)
- Billing/subscription management
