# System Architecture

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Client Layer                             │
│  Frontend (React/Next.js)  │  API Consumers  │  oEmbed Clients  │
└──────────┬──────────────────┼────────────────┼──────────────────┘
           │                  │                │
           ▼                  ▼                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DropItX API (FastAPI v0.3.0)                  │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │   v1/    │  │dashboard/│  │internal/ │  │    public/       │ │
│  │ API Key  │  │   JWT    │  │ JWT/Opt  │  │    None         │ │
│  │ Auth     │  │  Auth    │  │  Auth    │  │    Auth         │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│         │             │              │                │          │
│  ┌──────┴─────────────┴──────────────┴────────────────┴──────┐ │
│  │           Dependencies & Middleware Layer                  │ │
│  │  Auth (JWT, API key) │ IP tracking │ CORS │ Error handlers│ │
│  └──────┬─────────────┬──────────────┬────────────────┬──────┘ │
│         │             │              │                │          │
│  ┌──────┴─────────────┴──────────────┴────────────────┴──────┐ │
│  │                      Core Services                         │ │
│  │  Config  │ Supabase │ Security │ Encryption │ Language    │ │
│  │  Extract │ Nanoid   │ Rate Lim │ Thumbnail  │ Logging     │ │
│  └──────────┴──────────┴──────────┴────────────┴─────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Background Services                           │  │
│  │  Cleanup (expired shares, file requests, burned)         │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐
│  Supabase       │ │ Supabase     │ │  Firebase    │
│  Postgres       │ │ Storage      │ │    Auth      │
│  (data)         │ │ (files)      │ │  (JWT issuer)│
│                 │ │              │ │              │
│ 15+ tables      │ │ 3 buckets:   │ │  Firebase    │
│ 8 RPCs          │ │  html-files  │ │  certs       │
│                 │ │  shares      │ │              │
│                 │ │  thumbnails  │ │              │
└─────────────────┘ └──────────────┘ └──────────────┘
```

## Route Group Architecture

All routes under `/api` prefix, grouped by authentication method:

```
/api/
├── /v1/                          [API Key Auth]
│   ├── /documents                → CRUD (create, list, get, update, delete)
│   ├── /documents/{slug}/revisions → Version history
│   └── /keys                     → API key management
│
├── /dashboard/                   [JWT Auth]
│   ├── /teams                    → Team CRUD, member management
│   ├── /teams/{slug}/members     → Member list, role change, remove
│   ├── /teams/{slug}/invites     → Invite lifecycle (create, list, revoke, bulk, resend)
│   ├── /teams/{slug}/events      → Audit log
│   ├── /teams/{slug}/shares      → Team's shared content
│   ├── /teams/{slug}/domains     → Custom domain management
│   └── /invitations              → User's received invites
│
├── /                             [JWT or None]
│   ├── /upload                   → File upload (HTML/MD, 50MB)
│   ├── /multi-upload             → Batch upload (share groups)
│   ├── /publish                  → Editor publish (custom slugs)
│   ├── /images/upload            → Embedded images (PNG/JPG/GIF, 5MB)
│   ├── /download/...             → Bulk download (ZIP)
│   └── /file-requests/{slug}/...  → Upload to file request
│
├── /shares/                      [No Auth, Optional JWT for delete]
│   ├── /{slug}                   → Get share, delete (owner or token)
│   ├── /{slug}/password          → Set/clear password
│   ├── /{slug}/unlock            → Verify password (rate-limited)
│   ├── /{slug}/encrypt           → Encrypt with password
│   ├── /{slug}/reencrypt         → Re-encrypt with new password
│   ├── /{slug}/versions          → Version history (read-only)
│   ├── /{slug}/comments          → Add/list comments
│   ├── /{slug}/preview           → File preview (images, PDF, text, etc)
│   ├── /{slug}/stars             → Star/unstar (requires JWT)
│   └── /{slug}/qrcode            → Generate QR code (SVG or PNG)
│
├── /encryption/                  [Public]
│   └── /generate-key             → Generate encryption key bundle
│
├── /search                       [Public]
│   └── ?q=...&page=...           → Full-text search
│
├── /explore                      [Public]
│   └── ?tag=...&sort=...         → Gallery (trending, tag-filtered)
│
├── /profiles/{handle}            [Public]
│   └── Get user profile + shares
│
├── /analytics/track              [Public]
│   └── View tracking (always 200)
│
├── /oembed                       [Public]
│   └── oEmbed discovery
│
└── /file-requests/               [Public]
    ├── (Create via /api/file-requests/create, JWT)
    └── {slug}/upload → Public upload endpoint
```

## Authentication & Authorization Flow

### JWT-Authenticated Request (e.g., Dashboard)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/dashboard/  │                       │
  │  teams (Bearer JWT)    │                       │
  │───────────────────────>│                       │
  │                        │                       │
  │                        │ 1. Extract JWT header │
  │                        │ 2. Fetch Firebase     │
  │                        │    certs (cached 1hr) │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │ 3. Verify RS256 sig   │
  │                        │    Extract user_id    │
  │                        │                       │
  │                        │ 4. DB query (admin)   │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │  200 OK + {teams: [...]}
  │<───────────────────────│
```

### API Key Authenticated Request (e.g., v1 Documents)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/v1/         │                       │
  │  documents             │                       │
  │  (Authorization: Bearer shk_...) 
  │───────────────────────>│                       │
  │                        │                       │
  │                        │ 1. SHA-256 hash key   │
  │                        │ 2. Lookup api_keys    │
  │                        │ 3. Check revoked_at   │
  │                        │ 4. If team: check     │
  │                        │    membership         │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │ 5. Storage upload     │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │ 6. DB insert shares   │
  │                        │────────────────────── >│
  │                        │ (fail: cleanup blob)  │
  │                        │<──────────────────────│
  │                        │                       │
  │  201 + {slug, url, ...}│
  │<───────────────────────│
```

### Public Upload (Optional Auth)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/upload      │                       │
  │  (multipart file)      │                       │
  │───────────────────────>│                       │
  │                        │                       │
  │                        │ 1. Rate limit check   │
  │                        │    (RPC, fail-open)   │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │ 2. Storage upload     │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │ 3. Extract plain text │
  │                        │ 4. Detect language    │
  │                        │                       │
  │                        │ 5. DB insert shares   │
  │                        │──────────────────────>│
  │                        │ (fail: cleanup blob)  │
  │                        │<──────────────────────│
  │                        │                       │
  │  200 + {slug, url, ...}│
  │<───────────────────────│
```

## Supabase Client Architecture

Three client types (core/supabase.py):

```
┌──────────────────────────────────────────────────┐
│           get_user_client(token)                 │
│  • Per-request, JWT-authenticated                │
│  • RLS applies (data filtered by policy)         │
│  • Use when: user's own data only                │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│           get_admin_client()                     │
│  • Service-role key, bypasses RLS                │
│  • Used in all route handlers                    │
│  • Full database access                          │
│  • Fresh client per call (no pooling)            │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│           get_anon_client()                      │
│  • No authentication context                     │
│  • Use for public operations                     │
│  • Lazy-initialized, reused                      │
└──────────────────────────────────────────────────┘
```

## Storage Architecture

### html-files Bucket
```
html-files/
├── shares/{slug}.html     (upload/publish, public)
├── shares/{slug}.md       (upload/publish, public)
└── [max 50 MB per file]
```
Used by `/api/upload` and `/api/publish`. Public bucket (files served directly via public URL).

### shares Bucket
```
shares/
├── {user_id}/{slug}       (v1 API documents, private)
└── [max 50 MB per file]
```
Used by v1 API document endpoints. Not directly public.

### thumbnails Bucket
```
thumbnails/
├── shares/{slug}.jpg      (generated previews)
└── [cached, auto-deleted if source deleted]
```
Generated on-demand for preview endpoints.

## Data Flow: Multi-Step Operations

### Document Upload with Compensating Transaction
```
1. Rate limit check (RPC)
   ├─ Success? → Continue
   └─ Fail? → Return 429

2. Storage upload (Supabase Storage)
   ├─ Success → Proceed
   └─ Fail → Return 500

3. Extract plain text from HTML/MD
   └─ Proceed (optional)

4. Detect language via n-grams
   └─ Proceed (optional)

5. Database insert (Postgres)
   ├─ Success → Return 200 + {slug, url}
   └─ Fail? → Cleanup storage file (best-effort) → Return 500
```

### Team Invite + Event Log
```
1. Verify user has editor+ role in team
   ├─ Yes → Proceed
   └─ No → Return 403

2. Create invite via RPC (atomic)
   ├─ Success → Proceed
   └─ Fail → Return 500

3. Log event (async, best-effort)
   └─ Fire-and-forget
```

## Rate Limiting Architecture

```
Request → Rate Limit Check (RPC) → Decision
                                    │
                ┌───────────────────┼───────────────┐
                ▼                   ▼               ▼
            Allow              Deny (429)      Error (500)
            Proceed            Retry-After     Fail-open?
                                                  ├─ Yes → Allow
                                                  └─ No → Deny
```

RPC `check_rate_limit(p_key, p_max_attempts, p_window_secs)` returns:
```json
{
  "success": true/false,
  "remaining": 5,
  "reset_at": "2026-07-17T22:30:00Z"
}
```

Key formats encode context: `upload:{ip}`, `pwd:{ip}:{slug}`, `analytics:{ip}`, etc.

Predefined limits:
- Upload: 10/min/IP (fail-open)
- Publish: 10/min/IP (fail-open)
- Password unlock: 5/10min/IP+slug (fail-closed)
- oEmbed: 60/min/IP (fail-open)
- Analytics: 60/min/IP (fail-open)

## Deployment Architecture

### Render (Container)
```
Request
  ↓
Render Load Balancer
  ↓
Render Container Instance (uvicorn)
  ↓
app.main:app (FastAPI)
  ↓
[Routes → Supabase]
  ↓
Response
```

- **Runtime**: Python 3.12+ (uvicorn)
- **Port**: $PORT (set by Render, default 8000)
- **Health Check**: `/health` (liveness probe)
- **Config**: `.env` file or Render dashboard env vars
- **Scaling**: Auto-scaling based on CPU/memory
- **Persistence**: Stateless (all state in Supabase)

## Async/Threading Strategy

All Supabase Python client calls are synchronous. FastAPI runs in async context:

```python
# Pattern: asyncio.to_thread() for Supabase calls
response = await asyncio.to_thread(
    lambda: client.table("shares").select("*").execute()
)
```

Benefits:
- Single-threaded event loop in main thread
- Worker threads for blocking I/O
- Scales to hundreds of concurrent requests
- No async Supabase client needed

## Error Handling Architecture

```
Route Handler
  ↓
Try:
  ├─ Dependency injection (auth, validation)
  ├─ Business logic
  ├─ DB/Storage operations
  └─ Response serialization
  ↓
Catch: [Exception Type]
  ├─ HTTPException → 400/401/403/404/409/429
  │  (specific status + detail)
  │
  ├─ ShareNotFoundError → 404 (not_found)
  ├─ SharePasswordRequired → 403 (password_required)
  ├─ RateLimitError → 429 (rate_limit_exceeded)
  │
  └─ Exception → 500 (internal_error)
     (log, never expose details to client)
  ↓
Response:
{
  "error": "error_code",
  "detail": "Human-readable message",
  "request_id": "uuid"
}
```

All errors return consistent envelope with `request_id` for tracing.

## Background Services

### Cleanup Service
Runs on app startup via `asyncio.create_task()`. Hourly loop:

```python
async def cleanup_loop():
    while True:
        await asyncio.sleep(3600)  # 1 hour
        
        # 1. Delete expired shares (expires_at < now)
        # 2. Delete burned shares (download_count >= max_downloads)
        # 3. Delete expired file requests
        # 4. Delete orphaned temporary files
        # 5. Vacuum old analytics records (optional)
```

Non-critical; failures logged but don't impact requests.

## Scaling Considerations

### Current Bottlenecks
1. **Supabase Admin Client**: Fresh per call (no pooling)
2. **Firebase Cert Caching**: 1hr TTL (`_CERTS_TTL`), 1 fetch per cold start or after expiry, plus an early refetch on a `kid` cache-miss
3. **Search**: Full-text search via RPC (single-threaded Postgres)
4. **Language Detection**: Regex-based ngram matching (CPU-bound)

### Future Scaling Improvements
- Connection pooling for Supabase client
- Redis cache for Firebase certs + frequently accessed shares
- CDN for static assets (thumbnails, files)
- Read replicas for analytics queries
- Sharded storage buckets for large-scale uploads
