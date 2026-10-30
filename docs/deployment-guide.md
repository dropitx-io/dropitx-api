# Deployment Guide

## Prerequisites

- **Supabase project** with Auth, Postgres, and Storage enabled
- **Database migrations** applied (tables, RPCs, indexes)
- **Storage buckets** created: `html-files`, `shares`, `thumbnails`
- **Python 3.12+** locally (for development and testing)
- **Git repository** (for Render deployment)

## Supabase Setup

### 1. Create Storage Buckets

In Supabase dashboard, go to **Storage** → **Buckets** and create:

| Bucket | Public | Purpose |
|--------|--------|---------|
| `html-files` | Yes | Upload and publish flows (public access) |
| `shares` | No | v1 API documents (private, served via API) |
| `thumbnails` | Yes | Generated previews (auto-deleted if source deleted) |

### 2. Apply Database Migrations

Use Supabase CLI to apply migrations:

```bash
# Install Supabase CLI
npm install -g supabase

# Link to your project
supabase link --project-ref <your-project-ref>

# Apply migrations
supabase db push

# Or manually:
# Copy supabase/migrations/*.sql contents into Supabase SQL editor
```

Migrations create:
- **Tables**: shares, api_keys, teams, team_members, team_invitations, team_events, team_shares, share_views, share_revisions, share_comments, share_groups, custom_domains, file_requests, profiles, etc.
- **RPCs**: check_rate_limit, search_shares, create_team_invite, accept_team_invite, decline_team_invite, change_team_member_role, remove_team_member, record_share_view, check_download_limit
- **Indexes**: On slug, user_id, team_id, created_at for performance

### 3. Configure Auth Settings

In the Firebase console:
- Note the **Project ID** and set it as `FIREBASE_PROJECT_ID` — JWT verification in `core/security.py` validates ID tokens (RS256 against Google's public x509 certs) for this project
- Verify **Authorized Domains** include your frontend domain

## Environment Variables

### Required (All Platforms)

| Variable | Description | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Supabase project URL | `https://xxxxx.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anon/public key | `eyJ...` (32+ chars) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role key (secret!) | `eyJ...` (32+ chars) |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | `https://dropitx.com,https://app.dropitx.com` |
| `FRONTEND_URL` | Frontend base URL (for invite links) | `https://dropitx.com` |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENV` | `production` | Set to `dev` for readable logs |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PYTHON_VERSION` | `3.12.0` | Python runtime version |

### Sensitive Information

⚠️ **NEVER commit `.env` or `SUPABASE_SERVICE_ROLE_KEY` to Git.**

Use `.env.example` as a template:
```bash
cp .env.example .env
# Edit .env with real values
# Add .env to .gitignore (should already be there)
```

## Local Development

### Setup

```bash
# Clone repo
git clone https://github.com/org/dropitx-api.git
cd dropitx-api

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"  # With test deps

# Create .env file
cp .env.example .env
# Edit .env with your Supabase credentials
```

### Run Dev Server

```bash
# With auto-reload
uvicorn app.main:app --reload --port 8000

# Open http://localhost:8000/docs for interactive API docs
```

### Run Tests

```bash
# All tests
pytest

# Single test file
pytest tests/test_encryption.py -v

# Single test
pytest -k "test_encrypt_share" -v

# With coverage
pytest --cov=app --cov=core
```

## Render Deployment

### Option 1: Blueprint (Recommended)

1. Go to [render.com/account/integrations/github](https://render.com/account/integrations/github)
2. Click **"New +"** → **"Blueprint"**
3. Enter this repo URL: `https://github.com/org/dropitx-api`
4. Render auto-detects `render.yaml`
5. Set environment variables in dashboard
6. Click **"Create"**

Render auto-deploys on `git push` to main branch.

### Option 2: Manual Setup

1. **Create Web Service**
   - Go to [render.com/dashboard](https://render.com/dashboard)
   - Click **"New +"** → **"Web Service"**
   - Connect your Git repository

2. **Configure**
   - **Name**: `dropitx-api`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Python Version**: `3.12.0` (set as env var)
   - **Plan**: Free or Paid (depending on needs)

3. **Environment Variables**
   - Add all required variables from the table above
   - Set `PYTHON_VERSION=3.12.0`
   - Set `ENV=production` (recommended)

4. **Deploy**
   - Click **"Create Web Service"**
   - Wait for build (2-5 minutes)

### Configuration Details

```yaml
# render.yaml (auto-detected by Render)
services:
  - type: web
    name: dropitx-api
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.0"
      - key: SUPABASE_URL
        sync: false  # Set in Render dashboard
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ALLOWED_ORIGINS
        sync: false
      - key: FRONTEND_URL
        sync: false
```

## Monitoring & Health

### Health Endpoints

```bash
# Liveness check (always 200 if process alive)
curl https://your-domain/health
# {"status": "ok", "service": "dropitx-api"}

# Deep health check (includes database ping)
curl https://your-domain/health/deep
# {"status": "ok", "checks": {"database": {"status": "ok", "latency_ms": 123}}}
```

### Logs

**Render Dashboard**:
- Go to your service → **"Logs"** tab
- Real-time streaming + searchable history
- JSON format in production, readable in dev

**Format**:
```json
{
  "timestamp": "2026-07-17T22:30:45.123Z",
  "level": "INFO",
  "logger": "app.v1.documents",
  "message": "Document created",
  "request_id": "uuid-here"
}
```

### API Docs

OpenAPI docs auto-generated:
- **Swagger UI**: `https://your-domain/docs`
- **ReDoc**: `https://your-domain/redoc`

All endpoints, request/response schemas, auth methods, rate limits documented.

## Scaling Considerations

### Current Limits

- **File Size**: 50 MB per upload
- **Rate Limits**:
  - Upload: 10/min/IP (fail-open)
  - Password unlock: 5/10min/IP+slug (fail-closed)
  - Analytics: 60/min/IP (fail-open)
- **Database Connections**: ~10 (Supabase free tier)
- **Storage**: 1 GB (Supabase free tier)

### Upgrade Path

| Load | Recommendation |
|------|-----------------|
| < 100 req/min | Render free + Supabase free |
| 100-1k req/min | Render starter + Supabase pro |
| 1k-10k req/min | Render standard + Supabase team |
| 10k+ req/min | Render pro + Supabase enterprise + CDN |

## Troubleshooting

### Build Fails

```
ERROR: pip's dependency resolver does not currently take into account all the packages
```

**Solution**: Update `requirements.txt` to compatible versions, or use Python 3.12 explicitly.

### 502 Bad Gateway

1. Check logs: `curl https://your-domain/health`
2. Verify `uvicorn` starts: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. Check Firebase auth connectivity (certs are fetched automatically by `core/security.py` — no manual verification step is needed; if one is desired, check Google's public cert endpoint):
   ```bash
   curl "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
   ```

### Auth Failures (401)

| Error | Cause | Fix |
|-------|-------|-----|
| "Invalid token" | JWT signature mismatch | Verify `FIREBASE_PROJECT_ID` matches the token's `aud`/`iss` claims |
| "key not found" | API key doesn't exist | Regenerate key, check hash |
| "revoked" | API key soft-deleted | Create new key |

### Storage Upload Fails (500)

| Error | Cause | Fix |
|-------|-------|-----|
| "Bucket not found" | Bucket doesn't exist | Create `html-files`, `shares`, `thumbnails` |
| "Permission denied" | Bucket is private | Make `html-files` + `thumbnails` public |
| "Quota exceeded" | Storage limit hit | Delete old files or upgrade plan |

### Rate Limit Not Working

- **Cause**: `check_rate_limit` RPC missing
- **Fix**: Apply database migrations via Supabase CLI

```bash
supabase db push
```

### Search Returns Empty

- **Cause**: `search_shares` RPC missing
- **Fix**: Apply database migrations

### CORS Errors

```
Access to XMLHttpRequest blocked by CORS
```

**Cause**: Frontend domain not in `ALLOWED_ORIGINS`

**Fix**: Update `ALLOWED_ORIGINS` env var:
```bash
ALLOWED_ORIGINS=https://dropitx.com,https://app.dropitx.com,http://localhost:3000
```

### High Memory Usage

- **Cause**: Large file uploads, language detection
- **Fix**: 
  - Increase Render plan memory
  - Add caching layer (Redis)
  - Optimize language detection (ngram-based, not ML)

## Rollback

### Render Rollback

1. Go to service → **"Deployments"** tab
2. Find previous successful deployment
3. Click **"Rollback"**
4. Confirm

### Database Rollback

```bash
# If migrations caused issues
supabase db reset  # ⚠️ Deletes all data
supabase db push   # Re-apply migrations
```

## Production Checklist

- [ ] Environment variables set (Supabase credentials, CORS origins)
- [ ] Storage buckets created and configured
- [ ] Database migrations applied
- [ ] Health endpoint responds 200
- [ ] API docs accessible (`/docs`)
- [ ] Sample request succeeds (e.g., `/health/deep`)
- [ ] Error handling tested (invalid auth, rate limits)
- [ ] Logs streaming to Render dashboard
- [ ] Backups configured (Supabase auto-backup)
- [ ] HTTPS enforced (Render automatic)
- [ ] Team has access to Render dashboard
