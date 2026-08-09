<!-- generated-by: gsd-doc-writer -->

# Deployment

DropItX API is a FastAPI service deployed to **Render** from the [`render.yaml`](../render.yaml) blueprint. It has no local database or filesystem state of its own — all data, files, and auth live in a Supabase project (Postgres + Storage + JWT). A deploy is healthy only when the Render web service boots **and** its Supabase dependencies are reachable.

This document is the canonical deployment reference. The older [`docs/deployment-guide.md`](deployment-guide.md) overlaps but is superseded here for blueprint-driven deploys. For environment variables, see [`docs/CONFIGURATION.md`](CONFIGURATION.md).

## Deployment target

| Target | Config | Runtime |
|--------|--------|---------|
| Render Web Service | [`render.yaml`](../render.yaml) (blueprint) | Python 3.12.0 |

Render is the only deployment target defined in the repository. The service runs as a single `web` instance on Render's `free` plan; there is no container image, Dockerfile, `docker-compose.yml`, `vercel.json`, `fly.toml`, or `serverless.yml` in this repo.

<!-- VERIFY: the production Render service URL, dashboard service ID, and Render account/owner are not in the repository — confirm them in the Render dashboard. -->

## render.yaml structure

The blueprint ([`render.yaml`](../render.yaml)) defines exactly one service:

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

- **Runtime:** `python` (Render-managed Python environment).
- **Plan:** `free`. Upgrade in the Render dashboard as load grows — this is a dashboard-only setting, not in the blueprint.
- **Build command:** `pip install -r requirements.txt` (the pinned dependency list in [`requirements.txt`](../requirements.txt)). A reproducible lockfile (`uv.lock`) exists but is not used by the Render build.
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. `$PORT` is injected by Render. The ASGI app object is `app.main:app`.
- **Python version:** `PYTHON_VERSION="3.12.0"`. `pyproject.toml` requires `>=3.12`, so 3.12.0 is the minimum compatible pin.
- **`sync: false` env vars:** Render holds these as encrypted environment variables in its dashboard rather than deriving them from the blueprint. They must be set manually on first deploy (see [Environment setup](#environment-setup)).

## Database and storage prerequisites

The Render service is stateless. Before the first deploy, the configured Supabase project must already contain the schema, RPCs, and storage buckets the app expects. If any are missing, `/health/deep` will report `degraded` and affected routes will fail at runtime.

<!-- VERIFY: the production Supabase project reference/ID and region are not in the repository — confirm against the deployed Supabase project dashboard. -->

### Supabase project setup

1. Create a Supabase project with **Auth**, **Postgres**, and **Storage** enabled.
2. Apply migrations. The repo ships two migration sets:
   - [`supabase/migrations/`](../supabase/migrations/) — the canonical, Supabase-CLI-ordered set (base schema, competitor features, file requests, schema fixes). Apply with `supabase db push` after `supabase link --project-ref <project-ref>`.
   - [`migrations/`](../migrations/) — feature-specific SQL files (encryption columns, share files, comments, revisions, custom domains, explore gallery, download-count RPC). If running manually, apply these against the same database.
3. Note the project's **JWKS URL**: `https://<project>.supabase.co/auth/v1/.well-known/jwks.json`. JWT verification in [`core/security.py`](../core/security.py) fetches and caches this for 10 minutes (`_JWKS_TTL = 600`).

### Storage buckets

Exactly **two** buckets must exist:

| Bucket | Public | Used by | Purpose |
|--------|--------|---------|---------|
| `html-files` | Yes | upload, publish, image, file-request, and thumbnail flows | Stores uploaded HTML/image content. Served at `<SUPABASE_URL>/storage/v1/object/public/html-files/<path>`. Thumbnails are stored as objects under `thumbnails/<base>_thumb.jpg` **inside this same bucket**, not as a separate bucket. |
| `shares` | No | v1 API documents and revisions | Private documents served only through the API. |

`html-files` must be public for direct object URLs to resolve. `shares` stays private; contents are returned via the API rather than via public URLs.

### Required Postgres RPCs

Migrations must define the following RPCs, called from Python via the Supabase admin client:

- `check_rate_limit` — used by [`core/rate_limit.py`](../core/rate_limit.py) for all rate-limit checks.
- `search_shares` — used by search endpoints.
- `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member` — used by team/invite flows in `app/dashboard/`.
- `increment_share_views` — used by share view tracking.

If `check_rate_limit` or `search_shares` is missing, requests depending on them will fail.

### Row-Level Security (RLS)

Supabase enforces RLS. The app uses three client types (see [`core/supabase.py`](../core/supabase.py)):

- `get_user_client(token)` — anon key + per-request JWT; **RLS applies** (user-scoped access).
- `get_anon_client()` — anon key, no user context; RLS applies for public reads.
- `get_admin_client()` — service-role key; **bypasses RLS**. Most routes use this.

RLS policies are defined in the migration files (e.g. `001_create_share_files.sql`, `002_create_share_comments.sql`, `004_custom_domains.sql`, `004_explore_gallery.sql` under [`migrations/`](../migrations/), plus the `supabase/migrations/*.sql` set). Apply all migrations so the policies match what the code expects.

## Environment setup

All runtime configuration is environment-variable driven — there is no application config file. The full reference, defaults, and required/optional status live in [`docs/CONFIGURATION.md`](CONFIGURATION.md). For deployment, the variables declared in `render.yaml` are the ones Render manages.

### Required for first deploy (set in Render dashboard)

These three are **required at startup** — Pydantic `BaseSettings` in [`core/config.py`](../core/config.py) raises `ValidationError` if any is missing, and the app will not boot:

| Variable | Notes |
|----------|-------|
| `SUPABASE_URL` | `https://<project>.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anon/public key. |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key (bypasses RLS). Treat as a production secret. |

### Set alongside the required vars

| Variable | Notes |
|----------|-------|
| `ALLOWED_ORIGINS` | Comma-separated CORS origins. Default `http://localhost:3000` is local-dev only; production must list the real frontend origins. `*` disables credentials and allows all origins. |
| `FRONTEND_URL` | Frontend base URL used to build `/s/`, `/g/`, `/r/`, and `/invite/` links. Default `http://localhost:3000` is local-dev only. |

### Optional (have safe defaults)

| Variable | Default | Notes |
|----------|---------|-------|
| `PYTHON_VERSION` | `3.12.0` | Pinned in `render.yaml`. |
| `ENV` | `production` | Controls log format. `production` → JSON lines (recommended for Render). |
| `LOG_LEVEL` | `INFO` | Root log level. |
| `PORT` | Render-injected | Bound via `--port $PORT`. |

<!-- VERIFY: production values for SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, ALLOWED_ORIGINS, and FRONTEND_URL are stored only in the Render dashboard as encrypted env vars (`sync: false`). Verify them there before/at deploy. -->

## Build pipeline and deploy process

Render drives both build and deploy. There is no GitHub Actions workflow or other CI/CD pipeline in this repository that performs deploys.

### First deploy (Blueprint)

1. Push the repository to GitHub.
2. In Render, go to **New +** → **Blueprint**, select the repo, and let Render detect [`render.yaml`](../render.yaml).
3. Fill in the five `sync: false` environment variables (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`) in the Render dashboard.
4. Create the service. Render runs `pip install -r requirements.txt`, then starts `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

### Subsequent deploys (auto-deploy)

Render auto-deploys on `git push` to the tracked branch (main by default). Each push triggers a fresh build and a rolling restart. A manual redeploy is available from the service's **Deployments** tab in the Render dashboard.

<!-- VERIFY: the connected branch, deploy-hook URL, and any PR-previews setting are Render dashboard configuration, not in the repository. -->

## Health check endpoints

Use these after every deploy to confirm the service and its Supabase dependency are healthy (defined in [`app/main.py`](../app/main.py)):

```bash
# Liveness — always 200 if the process is alive. Does not touch Supabase.
curl https://<render-service-url>/health
# {"status": "ok", "service": "dropitx-api"}

# Readiness — pings the Supabase `shares` table via the admin client and reports latency.
curl https://<render-service-url>/health/deep
# {"status": "ok", "checks": {"database": {"status": "ok", "latency_ms": 123.4}}, "service": "dropitx-api"}
```

`/health/deep` returns `status: "degraded"` if the database query fails; treat that as a failed deploy even if the process is up. Point Render's health check at `/health` for liveness, and gate release sign-off on `/health/deep` returning `ok`.

<!-- VERIFY: the actual `<render-service-url>` (e.g. `https://dropitx-api.onrender.com` or a custom domain) is not in the repository — confirm in the Render dashboard. -->

Interactive API docs (Swagger UI at `/docs`, ReDoc at `/redoc`) are available on the deployed service for verification.

## Rollback procedure

1. In the Render dashboard, open the service → **Deployments** tab.
2. Select the most recent known-good deployment and click **Rollback**. Render redeploys that commit's build and restarts the service.
3. If the bad deploy shipped a code change only (no migration), rollback restores service immediately.
4. If the bad deploy was triggered by a **Supabase migration**, rolling back the code does not undo the schema change. Revert the migration manually against Supabase before/after rolling back the Render deploy. `supabase db reset` deletes data — use it only on non-production projects or when data loss is acceptable.

Because the service is stateless, Render rollback is the primary mechanism; database rollback is a separate, manual step against Supabase.

## Monitoring

- **Logs:** Render's **Logs** tab streams stdout/stderr in real time. In production (`ENV=production`, the default), logs are emitted as one JSON object per line by [`core/logging_config.py`](../core/logging_config.py), including `timestamp`, `level`, `logger`, `message`, `request_id`, and request-scoped extras (`status_code`, `method`, `path`, `duration_ms`, `client_ip`). Set `ENV=development` only if you want human-readable terminal logs.
- **Request tracing:** `RequestTrackingMiddleware` ([`core/middleware.py`](../core/middleware.py)) attaches a `request_id` to every request and propagates it into log records for correlation.
- **No external monitoring SDK is bundled.** The dependency list in [`requirements.txt`](../requirements.txt) contains no Sentry, Datadog, New Relic, or OpenTelemetry client. Observability currently relies on Render logs plus the `/health/deep` probe.

<!-- VERIFY: any external log forwarding, uptime monitor, or alerting integration is configured outside the repository (Render dashboard or third-party). Confirm there before relying on it. -->

## Production checklist

- [ ] Supabase project created; Auth, Postgres, and Storage enabled.
- [ ] All migrations applied (`supabase/migrations/` and `migrations/`), including the required RPCs.
- [ ] Storage buckets exist: `html-files` (public), `shares` (private).
- [ ] Render Blueprint created from `render.yaml`.
- [ ] Five `sync: false` env vars set in Render dashboard (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`).
- [ ] `PYTHON_VERSION=3.12.0` confirmed.
- [ ] `/health` returns `200` and `/health/deep` returns `status: "ok"` against production Supabase.
- [ ] Production `ALLOWED_ORIGINS` and `FRONTEND_URL` point at the real frontend (not `localhost`).
- [ ] Logs streaming to Render's Logs tab in JSON format.
