# Deployment Guide

## Prerequisites

- **Supabase project** with Auth, Postgres, and Storage enabled
- **Database migrations** applied (tables, RPCs, indexes)
- **Storage buckets** created: `html-files`, `shares`, `thumbnails`
- **Python 3.12+** locally (for development and testing)
- **Docker** (to build or run the container image locally; production builds use the repository `Dockerfile`)

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

## Deployment (vps192 k3s)

Production runs at `https://api.dropitx.site` on the vps192 k3s cluster. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full reference; in short:

1. CI passes on a push to `main`.
2. [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) builds the image `ghcr.io/dropitx-io/dropitx-api:<sha>` and pushes it.
3. The workflow opens a promotion PR in `phuongddx/vps192-k8s-config`, bumping the image tag in `apps/dropitx-api/vps192/kustomization.yaml`.
4. That repository's `validate` run checks the PR, then Slack asks for the merge.
5. A human merges the promotion PR. `vps192-k8s-config`'s own deploy workflow applies the manifests and posts the rollout result to Slack.

The manifests (`apps/dropitx-api/{base,vps192}`) and the production environment variables live in `vps192-k8s-config`, not in this repository.

## Monitoring & Health

### Health Endpoints

```bash
# Liveness check (200 if process alive)
curl https://api.dropitx.site/health
# {"status": "ok"}
```

### Logs

The container writes to stdout/stderr. Read them with `kubectl logs` on this service's pod in the vps192 cluster.

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

### Sizing

Compute resources are set in the manifests in `phuongddx/vps192-k8s-config` (`apps/dropitx-api`).

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
  - Raise the pod memory limit in `vps192-k8s-config`
  - Add caching layer (Redis)
  - Optimize language detection (ngram-based, not ML)

## Rollback

### Application Rollback

1. Find the previous image tag in the history of `apps/dropitx-api/vps192/kustomization.yaml` in `phuongddx/vps192-k8s-config`
2. Open a promotion PR there that points `newTag` back at that tag
3. Merge it; that repository's deploy workflow applies it and posts the rollout result to Slack

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
- [ ] Sample request succeeds against `https://api.dropitx.site`
- [ ] Error handling tested (invalid auth, rate limits)
- [ ] Backups configured (Supabase auto-backup)
- [ ] `https://api.dropitx.site` serves over HTTPS
- [ ] Team can merge promotion PRs in `vps192-k8s-config`
