# Deployment Guide

## Prerequisites

- Supabase project with Auth, Postgres, and Storage configured
- Database migrations applied (RPCs, tables, buckets)
- Storage buckets created: `html-files` and `shares`

## Environment Variables

Set these in your deployment platform's environment settings:

| Variable | Description | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anon/public key | `eyJ...` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role key | `eyJ...` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | `https://dropitx.com,https://app.dropitx.com` |
| `FRONTEND_URL` | Frontend base URL (invite links) | `https://dropitx.com` |

## Render Deployment

### Setup via Blueprint

The `render.yaml` blueprint is pre-configured:

```yaml
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
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ALLOWED_ORIGINS
        sync: false
      - key: FRONTEND_URL
        sync: false
```

### Manual Setup

1. Create a new **Web Service** on Render
2. Connect your Git repository
3. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Python Version**: `3.12.0` (in environment variables)

### Environment Variables

Add in Render dashboard under **Environment**. All variables in `render.yaml` are declared with `sync: false` — set values in the Render dashboard, not in the YAML.

### Deploy

```bash
# Blueprint deploy (first time)
render blueprint apply

# Or push to connected branch
git push origin main
```

### Health Check

Render uses `/health` endpoint (returns `{"status": "ok"}`) for health monitoring. This endpoint is defined in `app/main.py`.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Build fails | Check `requirements.txt` for compatible versions |
| Start timeout | Increase timeout in Render settings or optimize imports |
| 502 Bad Gateway | Check that `uvicorn` starts and binds to `$PORT` |
| Supabase connection refused | Verify `SUPABASE_URL` is correct and accessible from Render |
| Memory limit exceeded | Optimize large file handling, consider paid plan |

## General Troubleshooting

### Verifying Deployment

```bash
# Health check
curl https://your-domain/health

# API docs
# Open https://your-domain/docs in browser

# JWT verification
# Check Supabase Auth URL is accessible:
curl https://your-supabase.supabase.co/auth/v1/.well-known/jwks.json
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| 401 on all endpoints | Missing/invalid `SUPABASE_SERVICE_ROLE_KEY` | Regenerate key in Supabase dashboard |
| CORS errors | `ALLOWED_ORIGINS` mismatch | Ensure frontend URL is listed exactly |
| Storage upload fails | Bucket doesn't exist or wrong name | Create `html-files` and `shares` buckets |
| Rate limit always fails | `check_rate_limit` RPC missing | Apply database migrations |
| Search returns empty | `search_shares` RPC missing | Apply database migrations |
