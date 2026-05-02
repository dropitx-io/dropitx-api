# System Architecture

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         Client Layer                             │
│  Frontend (React/Next.js)  │  API Consumers  │  oEmbed Clients  │
└──────────┬──────────────────┼────────────────┼──────────────────┘
           │                  │                │
           ▼                  ▼                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DropItX API (FastAPI)                         │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │   v1/    │  │dashboard/│  │internal/ │  │    public/       │ │
│  │ API Key  │  │   JWT    │  │ JWT/Opt  │  │    None         │ │
│  │ Auth     │  │  Auth    │  │  Auth    │  │    Auth         │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│         │             │              │                │          │
│  ┌──────┴─────────────┴──────────────┴────────────────┴──────┐ │
│  │                  Dependencies Layer                        │ │
│  │  get_current_user │ get_api_key │ get_optional_user │ IP   │ │
│  └──────┬─────────────┬──────────────┬────────────────┬──────┘ │
│         │             │              │                │          │
│  ┌──────┴─────────────┴──────────────┴────────────────┴──────┐ │
│  │                      Core Services                         │ │
│  │  config │ supabase │ security │ extract_text │ nanoid     │ │
│  │            │         │                                          │ │
│  │            │    ┌────┴────┐                                     │ │
│  │            │    │ rate_   │                                     │ │
│  │            │    │ limit   │                                     │ │
│  └────────────┴────┴─────────┘                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌─────────────┐ ┌──────────┐ ┌──────────────┐
│  Supabase   │ │ Supabase │ │  Supabase    │
│  Postgres   │ │ Storage  │ │    Auth      │
│             │ │          │ │              │
│ tables:     │ │ buckets: │ │  JWT issuer  │
│  shares     │ │ html-    │ │  JWKS keys   │
│  api_keys   │ │  files   │ │              │
│  teams      │ │  shares  │ │              │
│  team_*     │ │          │ │              │
└─────────────┘ └──────────┘ └──────────────┘
```

## Request Flow

### JWT-Authenticated Request (e.g., Dashboard)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/dashboard/  │                       │
  │  teams (Bearer JWT)    │                       │
  │───────────────────────>│                       │
  │                        │  Fetch JWKS           │
  │                        │  (cached 10min)       │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │  Verify RS256 sig     │
  │                        │  Extract user_id      │
  │                        │                       │
  │                        │  DB query (admin)     │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │  200 OK + data         │                       │
  │<───────────────────────│                       │
```

### API Key Authenticated Request (e.g., v1 Documents)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/v1/         │                       │
  │  documents (shk_...)   │                       │
  │───────────────────────>│                       │
  │                        │                       │
  │                        │  SHA-256 hash key     │
  │                        │  Lookup api_keys      │
  │                        │  Check revoked_at     │
  │                        │  (team: check member) │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │  Storage upload       │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │  DB insert shares     │
  │                        │──────────────────────>│
  │                        │  (fail: cleanup blob) │
  │                        │<──────────────────────│
  │                        │                       │
  │  201 + document        │                       │
  │<───────────────────────│                       │
```

### Public Upload (Optional Auth)

```
Client                    API                   Supabase
  │                        │                       │
  │  POST /api/upload      │                       │
  │  (multipart file)      │                       │
  │───────────────────────>│                       │
  │                        │                       │
  │                        │  check_upload_rate    │
  │                        │  limit (RPC)          │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │  Storage upload       │
  │                        │──────────────────────>│
  │                        │<──────────────────────│
  │                        │                       │
  │                        │  Extract plain text   │
  │                        │  (regex, no deps)     │
  │                        │                       │
  │                        │  DB insert shares     │
  │                        │──────────────────────>│
  │                        │  (fail: cleanup blob) │
  │                        │<──────────────────────│
  │                        │                       │
  │  200 + {slug, url}     │                       │
  │<───────────────────────│                       │
```

## Auth Architecture

```
┌─────────────────────────────────────────────┐
│              Auth Methods                    │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │   JWT    │  │  API Key │  │ Optional │  │
│  │ (cookie) │  │ (Bearer) │  │   JWT    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │             │             │         │
│  JWKS  │        SHA-256     Try JWT,      │
│  verify│        hash check  fallback None  │
│  RS256 │        DB lookup                  │
└───────┼─────────────┼─────────────┼─────────┘
        │             │             │
        ▼             ▼             ▼
   User(id,email)  ApiKeyAuth   User|None
                  (user_id,    (id,email)
                   key_id,
                   team_id)
```

## Storage Architecture

Two Supabase Storage buckets:

### html-files bucket
Used by upload and publish flows.
- Path pattern: `shares/{slug}.html` or `shares/{slug}.md`
- Public bucket (files served directly via public URL)
- Upsert on republish

### shares bucket
Used by v1 API document endpoints.
- Path pattern: `{user_id}/{slug}`
- Files served via API (not direct public access)

## Deployment Architecture

### Render (Container)
```
Request → Render Load Balancer → uvicorn → app.main:app → Supabase
```
- Persistent process, auto-scaling
- Health check at `/health`
- Environment variables via Render dashboard or `render.yaml`
- Blueprint deployment via `render.yaml`

### Shared Infrastructure
- **Supabase Postgres**: All data (tables, RPCs)
- **Supabase Storage**: File blobs (two buckets)
- **Supabase Auth**: User management, JWT issuance, JWKS

## Rate Limiting Architecture

```
Request → Rate Limit Check (RPC) → Decision
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               Allow           Deny (429)      Error
               Proceed         Retry-After     Fail-open → Allow
                                            Fail-closed → Deny
```

RPC `check_rate_limit(p_key, p_max_attempts, p_window_secs)` returns `{success, remaining, reset_at}`. Key format encodes the context: `upload:{ip}`, `pwd:{ip}:{slug}`, `analytics:{ip}`.
