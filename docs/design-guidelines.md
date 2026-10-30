# Design Guidelines

## API Design Principles

### RESTful Conventions

- **Resources as nouns**: `/documents`, `/teams`, `/keys`, `/shares`
- **HTTP methods map to operations**: POST=create, GET=read, PATCH=update, DELETE=delete
- **Sub-resources via path**: `/teams/{slug}/members`, `/teams/{slug}/invites`
- **Actions as POST**: `/shares/{slug}/set-password`, `/shares/{slug}/unlock`, `/analytics/track`

### Response Format

- Use `dict` or Pydantic `response_model` for structured responses
- List endpoints return arrays
- Detail endpoints return single objects
- Mutation endpoints return the created/updated object
- Delete endpoints return `204 No Content` or `{"detail": "message"}`

### Error Format

All errors use FastAPI `HTTPException`:
```json
{"detail": "Human-readable error message"}
```

Status codes:
- `400` — Bad request (invalid input, missing fields)
- `401` — Unauthorized (missing/invalid token/key)
- `403` — Forbidden (insufficient permissions)
- `404` — Not found
- `409` — Conflict (duplicate slug, duplicate invite)
- `410` — Gone (already revoked/deleted)
- `422` — Unprocessable entity (validation failure)
- `429` — Rate limited (include `Retry-After` header)
- `500` — Internal server error

### Rate Limiting Response

On rate limit exceeded:
```json
{"detail": "Too many attempts. Try again later."}
```

Include `Retry-After` header with Unix timestamp of reset.

## Naming Conventions

### URL Paths
- Kebab-case: `/team-members`, `change-team-member-role`
- Plural nouns for collections: `/teams`, `/documents`, `/keys`
- Identifiers in path: `/teams/{slug}`, `/documents/{slug}`

### Query Parameters
- snake_case: `page`, `limit`, `team_id`
- Pagination: `page` (1-based), `limit`, `offset`

### Request Body Fields
- snake_case: `user_id`, `team_id`, `delete_token`, `share_id`
- Use full words, not abbreviations (exception: `id`, `url`, `ip`)

### Pydantic Models
- Class names: PascalCase (`DocumentCreate`, `TeamMember`, `ShareResponse`)
- Field names: snake_case (`file_size`, `storage_path`, `created_at`)
- Group in `models/` directory when shared across routes

### Database Columns
- snake_case throughout
- Foreign keys: `{table}_id` (e.g., `team_id`, `user_id`, `share_id`)
- Timestamps: `created_at`, `updated_at` (ISO 8601 strings from Postgres)
- Timestamps with nullable expiry: `expires_at`

### RPC Parameters
- Prefixed with `p_` to distinguish from column names: `p_key`, `p_max_attempts`, `p_team_id`

## Security Guidelines

### Authentication
- Always verify auth before accessing data — never trust client-side checks
- JWT verification uses Firebase's rotating x509 certs (not shared secret), audience set to FIREBASE_PROJECT_ID
- API keys returned raw only once on creation; store only SHA-256 hash
- Tokens generated with `secrets` module (cryptographically secure)

### Authorization
- Resource ownership verified server-side before mutation
- Team role hierarchy enforced numerically: owner(3) > editor(2) > viewer(1)
- Team key validation checks current membership (not just key existence)
- Optional auth endpoints: treat unauthenticated users as read-only

### Data Protection
- Passwords: bcrypt with 12 rounds, never log or expose hashes
- API keys: SHA-256 hashed before storage, raw key never persisted
- Delete tokens: single-use, 32-char hex, tied to share
- Service-role key: never exposed in logs, responses, or client-side code

### Input Validation
- All user input validated via Pydantic models with `Field()` constraints
- File types checked via MIME type with extension fallback
- Content size limits enforced at application level (not relying on proxy alone)
- Slug pattern validation: `^[a-z0-9-]+$` for team slugs

### Rate Limiting Strategy

| Endpoint | Limit | Window | Fail Mode | Rationale |
|----------|-------|--------|-----------|-----------|
| Upload | 10 | 1 min | Open | Non-critical, user convenience |
| Password unlock | 5 | 10 min | Closed | Security-sensitive, prevent brute force |
| oEmbed | 60 | 1 min | Open | External embeds, availability matters |
| Analytics | 60 | 1 min | Open | Tracking, never block user |

Fail-open: allows request on rate limit check failure (availability > security)
Fail-closed: blocks request on rate limit check failure (security > availability)

## Storage Design

### Bucket Strategy
- Separate buckets for different workflows to isolate concerns
- `html-files`: Public access, used by upload and publish flows
- `shares`: API-mediated access, used by v1 document endpoints

### File Path Conventions
- Upload/publish: `shares/{slug}.html` or `shares/{slug}.md`
- v1 documents: `{user_id}/{slug}` (namespaced by owner)

### Compensating Transactions
When storing requires both a file upload and DB insert:
1. Upload file to storage first
2. Insert DB record
3. If DB insert fails: attempt to remove uploaded file
4. Always log cleanup failures; never let cleanup errors mask the original error

## Dependencies

### Minimize External Dependencies
- Text extraction uses regex, not BeautifulSoup or lxml (reduces cold start time)
- JWT verification uses python-jose (lightweight), not PyJWT
- HTTP client: httpx (only for Firebase cert fetch, not for general HTTP)
- No ORM: direct Supabase client queries

### No State in API
- No in-memory caches (except the Firebase cert cache, 1hr TTL)
- No sessions or server-side state
- All data externalized to Supabase
- Deployable on stateless serverless platforms
