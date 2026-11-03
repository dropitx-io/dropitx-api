<!-- generated-by: gsd-doc-writer -->

# Deployment

DropItX API is a FastAPI service packaged as a container image ([`Dockerfile`](../Dockerfile)) and deployed to the **vps192 k3s cluster**. Production is served at `https://api.dropitx.site`. The service keeps no state of its own: data lives in Postgres, files live in an S3-compatible object store, and Firebase provides ID-token-based auth separately. A deploy is healthy only when the pod boots **and** its Postgres and object-store dependencies are reachable.

This document is the canonical deployment reference. The older [`docs/deployment-guide.md`](deployment-guide.md) overlaps but is superseded here. For environment variables, see [`docs/CONFIGURATION.md`](CONFIGURATION.md).

## Deployment target

| Target | Config | Runtime |
|--------|--------|---------|
| vps192 k3s cluster | Kubernetes manifests in `phuongddx/vps192-k8s-config`, under `apps/dropitx-api/{base,vps192}` | Python 3.12 (`python:3.12-slim` image) |

This repository does not hold the Kubernetes manifests. It builds the image; the `vps192-k8s-config` repository decides what runs. The `vps192` overlay there carries the `configmap.yaml`, the ingress and middleware manifests, and the `kustomization.yaml` that pins the image tag.

## Container image

The [`Dockerfile`](../Dockerfile) is a multi-stage build: the builder stage installs [`requirements.txt`](../requirements.txt) with `uv`, and the runtime stage is `python:3.12-slim` with `libpq5`. The container listens on port `8000` and starts:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

CI publishes the image as `ghcr.io/dropitx-io/dropitx-api:<sha>`, where `<sha>` is the commit that passed CI on `main`. Tags are immutable commit SHAs.

For a local stack (Postgres and MinIO with the two buckets created), use [`docker-compose.yml`](../docker-compose.yml); see [`docs/GETTING-STARTED.md`](GETTING-STARTED.md).

## Database and storage prerequisites

The service is stateless. Before the first deploy, the configured Postgres must contain the schema and RPCs the app expects, and the object store must contain the buckets. If any are missing, affected routes fail at runtime.

### Postgres

The schema is [`infra/init/*.sql`](../infra/init/), applied in sorted order, once, to an empty Postgres. These scripts are not migrations: re-running them against an existing database is not supported. [`supabase/migrations/`](../supabase/migrations/) and [`migrations/`](../migrations/) are historical and must not be applied.

The app connects with `DATABASE_URL` (see [`core/config.py`](../core/config.py) and [`core/db.py`](../core/db.py)).

### Auth

Create a Firebase project and note its **Project ID** from the Firebase console — set it as `FIREBASE_PROJECT_ID`. JWT verification in [`core/security.py`](../core/security.py) fetches and caches Google's public x509 signing certs for 1 hour (`_CERTS_TTL = 3600`).

### Storage buckets

The object store is reached through `S3_ENDPOINT`, `S3_ACCESS_KEY` and `S3_SECRET_KEY`. Exactly **two** buckets must exist:

| Bucket | Public | Used by | Purpose |
|--------|--------|---------|---------|
| `html-files` | Only `html-files/public/` is anonymously readable | upload, publish, image, file-request, and thumbnail flows | Stores uploaded HTML/image content. Public assets (editor images, thumbnails) are served at `{STORAGE_PUBLIC_URL}/html-files/public/<path>`. |
| `shares` | No | v1 API documents and revisions | Private documents served only through the API. |

Share content is returned through the API, never through a storage URL.

### Required Postgres RPCs

`infra/init/` must define the following RPCs, called through the database shim in [`core/db.py`](../core/db.py):

- `check_rate_limit` — used by [`core/rate_limit.py`](../core/rate_limit.py) for all rate-limit checks.
- `search_shares` — used by search endpoints.
- `create_team_invite`, `accept_team_invite`, `decline_team_invite`, `change_team_member_role`, `remove_team_member` — used by team/invite flows in `app/dashboard/`.
- `record_share_view` — used by share view tracking (`POST /api/analytics/track`); the analytics read functions live beside it in `infra/init/03_analytics.sql`.

If `check_rate_limit` or `search_shares` is missing, requests depending on them will fail.

## Environment setup

All runtime configuration is environment-variable driven — there is no application config file. The full reference, defaults, and required/optional status live in [`docs/CONFIGURATION.md`](CONFIGURATION.md). In production the values are supplied by the Kubernetes ConfigMap and Secret defined in `vps192-k8s-config` (`apps/dropitx-api`); secret values are not stored in this repository.

The settings declared in [`core/config.py`](../core/config.py) are:

| Variable | Default | Notes |
|----------|---------|-------|
| `FIREBASE_PROJECT_ID` | — (empty) | Firebase project ID used to verify ID tokens. Required for authenticated routes to work. |
| `DATABASE_URL` | local-dev Postgres URL | Production must point at the production Postgres. |
| `S3_ENDPOINT` | `http://localhost:9000` | S3-compatible object store endpoint. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | local-dev values | Object store credentials. Treat as production secrets. |
| `STORAGE_PUBLIC_URL` | `http://localhost:9000` | Browser-facing base URL of the object store, used to build public asset URLs. |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins. The default is local-dev only; production must list the real frontend origins. `*` disables credentials and allows all origins. |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend base URL used to build `/s/`, `/g/`, `/r/`, and `/invite/` links. The default is local-dev only. |

Every default above is a local-development value, so a production pod that leaves one unset silently points at `localhost`.

## Build pipeline and deploy process

Deploys are driven by [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), triggered after the `CI` workflow ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) passes on a push to `main` (or started manually with `workflow_dispatch`).

1. **Build.** The workflow builds the image and pushes `ghcr.io/dropitx-io/dropitx-api:<sha>`.
2. **Promote.** It opens a promotion pull request in `phuongddx/vps192-k8s-config` that bumps `newTag` for this image in `apps/dropitx-api/vps192/kustomization.yaml`.
3. **Validate.** That repository's `validate` run checks the pull request. When it passes, the workflow posts a "merge to deploy" message to Slack.
4. **Merge.** A human merges the promotion PR. This is the approval gate. Merging redeploys every vps192 service, not only this one.
5. **Apply.** `vps192-k8s-config`'s own deploy workflow applies the manifests and posts the rollout result to Slack.

Docs-only pushes to `main` skip CI and therefore skip the deploy.

## Health check endpoints

Use this after every deploy to confirm the service is up (defined in [`app/main.py`](../app/main.py)):

```bash
# Liveness — 200 if the process is alive.
curl https://api.dropitx.site/health
# {"status": "ok"}
```

Interactive API docs (Swagger UI at `/docs`, ReDoc at `/redoc`) are available on the deployed service for verification.

## Rollback procedure

1. Find the image tag the service ran before the bad deploy (the previous `newTag` in the history of `apps/dropitx-api/vps192/kustomization.yaml` in `vps192-k8s-config`).
2. Open a promotion PR in `vps192-k8s-config` that points `newTag` back at that tag, and merge it. `vps192-k8s-config`'s deploy workflow applies it and reports the rollout.
3. Rollback restores the previous image. The schema in `infra/init/` is applied only once, to a new empty database, so a deploy never changes an existing schema and there is nothing to revert in the database.
4. To restore data, restore a database backup into a database; `infra/init/*.sql` cannot be re-run against an existing one.

Because the service is stateless, redeploying the previous image is the primary mechanism; restoring data is a separate, manual database-backup restore.

## Monitoring

- **Logs:** the container writes to stdout/stderr. Read them with `kubectl logs` on this service's pod in the vps192 cluster.
- **Deploy results:** the rollout result of each deploy is posted to Slack by `vps192-k8s-config`'s deploy workflow, and CI or promotion failures are posted by this repository's deploy workflow.
- **No external monitoring SDK is bundled.** The dependency list in [`requirements.txt`](../requirements.txt) contains no Sentry, Datadog, New Relic, or OpenTelemetry client.

## Production checklist

- [ ] Postgres reachable from the cluster; schema applied: `infra/init/*.sql` run in sorted order against an empty Postgres, including the required RPCs.
- [ ] Object-store buckets exist: `html-files` (with `html-files/public/` anonymously readable) and `shares` (private).
- [ ] `FIREBASE_PROJECT_ID`, `DATABASE_URL`, the `S3_*` settings and `STORAGE_PUBLIC_URL` are set in the vps192 ConfigMap/Secret.
- [ ] Production `ALLOWED_ORIGINS` and `FRONTEND_URL` point at the real frontend (not `localhost`).
- [ ] The promotion PR passed `validate` and was merged; the Slack rollout result reports success.
- [ ] `https://api.dropitx.site/health` returns `200`.
