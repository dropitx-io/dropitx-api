# Codebase Concerns

**Analysis Date:** 2026-08-12

> Scope: full-repo scan of `/Users/ddphuong/Projects/next-labs/dropitx/dropitx-api`.
> Cross-references the live security audit at `plans/reports/security-audit-260812-1452-public-endpoint-auth-ratelimit-report.md`.

## Tech Debt

### Hand-rolled PostgREST shim instead of an ORM/query layer
- Issue: `core/db.py` (533 lines) reimplements a supabase-py-compatible fluent API (`QueryBuilder`, `RPCBuilder`, `StorageBucket`, `DatabaseClient`) by string-building SQL over `asyncpg`. Every new query shape that a route needs must be implemented in this shim, not by writing SQL in the route. The `supabase-py` client was replaced but its API was kept, so callsites still read like Supabase calls — misleading given Supabase is gone for data/storage.
- Files: `core/db.py`, `core/supabase.py`
- Impact: large surface for SQL-shape bugs; nested-select JOIN parsing (`_parse_select_columns`) only handles a subset of PostgREST syntax (single FK column guess via `fk_table[:-1] + "_id"`), so any FK that does not follow `{singular}_id` naming silently fails to join.
- Fix approach: either adopt a real async ORM (SQLAlchemy 2.x async / SQLModel) for new code, or freeze the shim API and document its limits. Stop pretending it is "drop-in supabase-py" — rename `core/supabase.py` to `core/db_client.py` and remove the Supabase framing from comments.

### Three-way split schema/migration layout
- Issue: schema lives in three directories with overlapping responsibilities: `infra/init/` (local source of truth for fresh boot), `supabase/migrations/` (legacy Supabase-cloud history), and `migrations/` (later additive patches). `infra/init/01_schema.sql` is a hand-consolidated copy of "15 files total" — there is no automation keeping it in sync with `migrations/00X_*.sql`.
- Files: `infra/init/01_schema.sql`, `infra/init/02_rpc_functions.sql`, `migrations/001_add_encryption_columns.sql` ... `migrations/008_provision_firebase_user.sql`, `supabase/migrations/20260529_base_schema.sql` ... `20260531_fix_schema_mismatches.sql`
- Impact: schema drift between fresh-boot DBs and patched DBs is silent; new migrations added under `migrations/` are not applied to a fresh `docker compose up -d` unless manually folded into `infra/init/01_schema.sql`. Migration files are not numbered in a way that orders reliably against the consolidated schema (`001_*` appears twice, `004_*` three times).
- Fix approach: pick one runner (e.g. `yuniql`, `alembic`, or a tiny in-repo sequential loader) and a single canonical directory; treat `infra/init/` as the immutable bootstrap and `migrations/` as the versioned forward-only log applied on top, with a CI check that the consolidated schema equals the sum of migrations.

### Dependency drift between `requirements.txt` and `pyproject.toml`
- Issue: `requirements.txt` declares `asyncpg`, `boto3`, `qrcode[pil]`, `dnspython` — runtime-critical for `core/db.py` (asyncpg), `core/db.py` StorageBucket (boto3), and `app/public/qrcode.py`. `pyproject.toml`'s `[project].dependencies` omits all four, so `pip install -e .` produces an import-broken runtime.
- Files: `requirements.txt`, `pyproject.toml`
- Impact: anyone installing via the PEP 621 metadata (the path `uv` prefers) gets a non-functional app; `uv.lock` may paper over this in CI but not for downstream consumers.
- Fix approach: make `pyproject.toml` the single source of truth and have `requirements.txt` reference it (or generate it via `pip-compile`). Add the missing four packages to `[project].dependencies`.

### Hybrid auth migration half-complete; CLAUDE.md contradicts code
- Issue: `core/security.py` now verifies **Firebase** ID tokens (RS256 against Google x509 certs, `verify_firebase_jwt`), and `app/dependencies.py` lookups go to the local `auth.users` stub. But `CLAUDE.md` and `docs/system-architecture.md` still state JWT verification hits cloud Supabase JWKS and that `SUPABASE_URL` must be a real Supabase Auth instance — no longer true. `core/config.py` keeps `supabase_url` for one purpose only: building public storage object URLs in upload/publish/images/preview/thumbnail/oembed.
- Files: `core/security.py`, `core/config.py`, `app/dependencies.py`, `CLAUDE.md`, `docs/system-architecture.md`
- Impact: new contributors onboard onto a wrong mental model; any future change that re-introduces a Supabase call will look consistent with the docs.
- Fix approach: rewrite the auth section of `CLAUDE.md`/`docs/system-architecture.md` to describe Firebase verification; rename `supabase_url` to `public_storage_base_url` (or fold into `s3_endpoint`) once no callsite depends on the Supabase-branded URL form.

### `get_anon_client` / `get_user_client` are no-ops
- Issue: both return `get_admin_client()` unconditionally. There is no RLS, no anon/admin distinction, no per-user client. Authorization is enforced entirely by app-layer `user_id`/role checks.
- Files: `core/db.py:526-533`, `core/supabase.py`
- Impact: a missed `.eq("user_id", ...)` filter in any route is a direct data leak across users — there is no database-level backstop. The API surface encourages `get_user_client(token)` thinking it scopes access; it does not.
- Fix approach: either delete these helpers (force every callsite to use `get_admin_client` and an explicit filter) or implement real RLS / per-request role switching on the Postgres connection.

## Known Bugs

### `GET /u/{username}` always returns 500 (`NameError`)
- Symptoms: every request raises `NameError: name 'true' is not defined` inside the query builder, caught by the surrounding `except Exception` and converted to `HTTPException(500, "Profile lookup failed")`.
- Files: `app/public/profiles.py:71`
- Trigger: any unauthenticated GET to `/api/u/{username}`.
- Workaround: none — the route is fully broken in production.
- Fix: change `.eq("is_public", true)` to `.eq("is_public", True)`. Add a regression test that hits this route with a seeded public profile.

### Dead ownership check in `app/public/encryption.py`
- Symptoms: `_authorize_owner(row, user, delete_token)` is defined at `app/public/encryption.py:99` and never called. `POST /shares/{slug}/encrypt` (line 160) and `POST /shares/{slug}/reencrypt` (line 253) mutate storage + DB without verifying the caller owns the share or holds the delete token.
- Files: `app/public/encryption.py:99, 160, 253`
- Trigger: `POST /api/shares/{slug}/encrypt` with any slug the caller can learn (via `/explore`, referrer leak, or a shared link) and a chosen password.
- Workaround: none.
- Fix: call `_authorize_owner(row, user, delete_token)` at the top of both handlers (mirror `app/public/shares.py`'s `set_password`/`burn`/`delete`), and add `Depends(get_optional_user)` + a `delete_token` body/query param. **Treat as a live vulnerability, not a style nit** — see the security audit for full impact (anonymous content takeover).

## Security Considerations

### `/api/download/group/{slug}` — unauthenticated, unthrottled, unbounded memory
- Risk: any internet caller triggers downloads of every file in a group from MinIO into API memory, builds a full ZIP in `BytesIO`, then streams. With 500 MB upload caps × up to 20 files/batch, a single request can pin ~10 GB through the process. No auth, no rate limit, no group-size cap, no per-file streaming.
- Files: `app/internal/download.py:70-119`, `_build_zip` at `app/internal/download.py:61`
- Current mitigation: none.
- Recommendations: require JWT or a group `delete_token`; add `check_upload_rate_limit`-equivalent per-IP throttle; cap total group size before building; stream the ZIP via a generator instead of materializing in `BytesIO`. If the endpoint is unused by any frontend flow, delete it.

### Public read endpoints with zero rate limiting
- Risk: `/shares/{slug}/content`, `/shares/{slug}/download`, `/shares/{slug}/preview`, `/shares/{slug}/files`, `/explore*`, `/search`, `/qr/{slug}`, `/u/{username}/shares`, `/api/domains/resolve/{domain}` are all reachable unauthenticated with no per-IP throttle. Bandwidth/cost exhaustion and (for `/qr/{slug}`) CPU-exhaustion are now internet-facing risks once the API is exposed via Cloudflare Tunnel.
- Files: `app/public/shares.py`, `app/public/preview.py`, `app/public/explore.py`, `app/public/qrcode.py`, `app/public/profiles.py`, `app/internal/multi_upload.py:214`, `app/dashboard/domains.py:352`
- Current mitigation: slugs are 10-char nanoid (unguessable), but `/explore` and `/search` enumerate them.
- Recommendations: add a shared "public read" rate-limit tier (reuse the `check_oembed_rate_limit` 60/min-per-IP helper); gate `/api/domains/resolve/{domain}` behind an internal shared-secret header set by the reverse proxy.

### SQL built via f-strings in `core/db.py`
- Risk: table names, column names, ORDER BY columns, and RPC function names are interpolated into SQL with f-strings (`core/db.py:327, 357, 381, 386, 404, 412, 435`). Values are parameterized via asyncpg's `$N` placeholders — those are safe. But any callsite that passes user-controlled input as a *column name* (e.g. `client.table(t).select(user_input)`) is an injection vector.
- Files: `core/db.py` (`QueryBuilder._do_select`, `_do_insert`, `_do_update`, `_do_delete`, `RPCBuilder._run`)
- Current mitigation: every observed callsite passes hard-coded column names; route path params are only ever used as `.eq(...)` values.
- Recommendations: add a whitelist/identifier validator (`^[a-zA-Z_][a-zA-Z0-9_]*$`) at the builder boundary so a future sloppy callsite fails closed instead of leaking.

### Rate-limit RPCs default to fail-open
- Risk: `check_upload_rate_limit`, `check_oembed_rate_limit`, `check_analytics_rate_limit` all return `success=True` on any DB error. Only `check_password_rate_limit` fails closed. If Postgres blips, the entire upload/write path becomes unlimited.
- Files: `core/rate_limit.py:82-100`
- Current mitigation: logs a warning.
- Recommendations: revisit fail-open decisions per route — uploads and analytics writes arguably should fail closed on repeat errors.

### `_update_last_used` fire-and-forget task is un-awaited
- Risk: `asyncio.create_task(_update_last_used(row["id"]))` at `app/dependencies.py:142` creates a task on the current event loop without holding a reference. If the task raises or the loop drops it, Python emits a "Task was destroyed but it is pending!" warning and the update is silently lost. It also runs after the response is returned, so on worker shutdown the update is dropped.
- Files: `app/dependencies.py:142, 157-168`
- Current mitigation: broad `except Exception` inside the helper swallows errors.
- Recommendations: either await it inline (cheap), or keep a module-level `set` of task refs and discard them on completion.

## Performance Bottlenecks

### Sync-over-async DB bridge with a single background event loop
- Problem: every DB call is `await asyncio.to_thread(lambda: client.table(...).execute())`. Inside the thread, `_run_async` submits the coroutine to one global background loop (`_loop`) and blocks the worker thread on `future.result(timeout=30)`. Under load, all DB work funnels through a single event loop with a pool of `max_size=10` connections; the 30 s hard timeout is per call, not per request.
- Files: `core/db.py:37-83`
- Cause: legacy of keeping supabase-py's sync API after moving to asyncpg.
- Improvement path: convert the shim to native async (`async def execute`) and drop the background loop; FastAPI route handlers are already async. This removes a thread hop per query and the 30 s cliff.

### Per-request boto3 client construction
- Problem: `StorageBucket._client()` builds a fresh `boto3.client("s3", ...)` on every storage operation (upload/download/remove). No connection reuse, no `aioboto3`, no client caching.
- Files: `core/db.py:448-458`
- Cause: shim mirrors the old supabase-py call shape.
- Improvement path: cache one `boto3.client` per process (thread-safe) or move to `aioboto3` and integrate with the async shim rewrite above.

### Firebase cert cache is per-process, not shared
- Problem: `_CERTS_CACHE` lives in module globals. Every uvicorn worker refetches `https://www.googleapis.com/robot/v1/metadata/x509/...` every hour, and on every kid miss. The cache also is not refreshed early when Google rotates keys beyond the 1-hour TTL window except via the kid-miss refetch path.
- Files: `core/security.py:25-44`
- Improvement path: acceptable for small worker counts; document the per-worker behavior. For scale, move to a shared cache (Redis) with the `max-age` from the Cache-Control header honored.

## Fragile Areas

### `core/db.py` query builder
- Files: `core/db.py:176-414`
- Why fragile: any route that needs an operator not implemented here (e.g. `or_`, `not_`, `order` with `nullsfirst`, JSON path filters, `HEAD` count-only) silently produces wrong SQL or raises. `_parse_select_columns` heuristic for FK column names (`teams` → `team_id`) breaks on any table whose FK deviates. The `count='exact'` path re-runs WHERE without JOIN, so counts on nested selects are wrong.
- Safe modification: add a focused unit test per new operator/column shape before using it in a route; never pass user input as a column or table name.
- Test coverage: no unit tests for `_parse_select_columns`, `_build_where`, or `_serialize_row`.

### `app/public/encryption.py` end-to-end crypto flow
- Files: `app/public/encryption.py`, `core/encryption.py`
- Why fragile: storage blob is overwritten with ciphertext in-place; if the DB update fails after the storage `update`, the share is left encrypted with no recoverable plaintext (no transaction spans storage + DB). The flow depends on the client holding the key in the URL fragment — lose the URL, lose the content.
- Safe modification: any change here needs a compensating-transaction plan for storage-write-then-db-update (the codebase already uses this pattern for uploads — see `app/internal/upload.py` cleanup); add round-trip integration tests against seeded content.
- Test coverage: `tests/test_encryption.py` (306 lines) covers the crypto primitives but not the storage+DB handoff.

### Rate-limit RPC contract
- Files: `core/rate_limit.py`, `infra/init/02_rpc_functions.sql`
- Why fragile: every limiter depends on a single `check_rate_limit(p_key, p_max_attempts, p_window_secs)` Postgres function existing and returning `{success, remaining, reset_at}`. If the function is dropped, or its signature drifts, every protected route silently fails open (per the `except Exception` branch).
- Safe modification: version the RPC name (`check_rate_limit_v2`) when changing its shape; add a startup probe in `app/main.py` that asserts the RPC exists and fail-fast if not.

## Scaling Limits

### Connection pool ceiling
- Current capacity: `min_size=2, max_size=10` asyncpg pool, single background event loop, single `DatabaseClient` singleton.
- Limit: with ~90 routes many doing 2-4 DB calls per request, 10 connections saturates around ~50-100 concurrent active requests; beyond that requests queue on the loop and start hitting the 30 s `_run_async` timeout.
- Scaling path: raise `max_size` only after measuring Postgres `max_connections`; the real fix is the native-async shim rewrite (see Performance) so connections aren't held across thread hops.

### In-process background cleanup
- Current capacity: `app/services/cleanup.py` runs as an in-process periodic task on each uvicorn worker — every worker independently issues the same delete queries.
- Limit: at N workers, expired-share cleanup runs N times concurrently; redundant work and lock contention.
- Scaling path: externalize to a single cron/worker (k8s `CronJob`) or a Postgres-level `pg_cron` job.

## Dependencies at Risk

### `python-jose` for JWT verification
- Risk: `python-jose` is in maintenance-only mode (last release 2021, CVE history including CVE-2024-33664 for JWT alg confusion). `core/security.py` does manually pin `algorithms=["RS256"]` and asserts the header alg before decode, which mitigates the classic confusion attack, but the library is not receiving security updates.
- Impact: a future advisory affecting jose would not be backported.
- Migration plan: move to `pyca/cryptography`'s JWT support, or `PyJWT` (actively maintained, RS256 support), or `firebase-admin`'s built-in `verify_id_token` (which also handles cert refresh and audience for free).

### `boto3` synchronous calls inside async handlers
- Risk: every storage call blocks a worker thread for the duration of the S3/MinIO round-trip. With large file uploads (up to 500 MB) this pins threads for seconds.
- Impact: thread pool starvation under concurrent uploads.
- Migration plan: `aioboto3` / `aiobotocore`, or move storage I/O fully behind the native-async shim.

## Missing Critical Features

### No global authentication middleware
- Problem: every router must remember to add `Depends(get_current_user)` / `Depends(get_api_key)`. There is no default-deny middleware. New routes that forget the dependency are public-by-accident (this is exactly how `/shares/{slug}/encrypt` ended up unauthenticated).
- Blocks: any new router file is one missed decorator away from a security incident.
- Fix approach: add a default-deny auth middleware with an explicit allowlist of public paths (the health/search/analytics/share-read paths enumerated in the security audit).

### No CI pipeline detected
- Problem: no `.github/workflows/`, no `.gitlab-ci.yml`, no CI config in the repo. Tests only run locally.
- Blocks: regressions like the `true` vs `True` bug ship unchallenged; dependency drift between `requirements.txt` and `pyproject.toml` is invisible; the security audit findings have no automated regression test.
- Fix approach: add a minimal GitHub Actions workflow running `pytest`, a `pip install -e .` smoke (catches the pyproject dependency drift), and the lint/type checks the project already documents.

### No observability stack
- Problem: structured logging exists (`core/logging_config.py`) but there is no error-tracking integration (Sentry, Rollbar) and no metrics (Prometheus/OpenTelemetry). Rate-limit failures log at WARNING and move on.
- Blocks: no way to detect an active abuse pattern against `/download/group/{slug}` or `/encrypt` from inside the app.
- Fix approach: add an error-tracking SDK and emit a counter on every rate-limit fail-open and every `_authorize_owner` failure.

## Test Coverage Gaps

### DB shim has no unit tests
- What's not tested: `_parse_select_columns` (FK-column guessing), `_build_where` (`IN`, `@>`, `IS NULL` branches), `_serialize_row` (UUID/array/decimal handling), the JOIN-building path in `_do_select`, the `count='exact'` re-query.
- Files: `core/db.py`
- Risk: any of these silently breaking surfaces as wrong data in routes that have no DB integration tests either.
- Priority: High.

### No integration test for the auth handshake
- What's not tested: `GET /api/auth/session` → `provision_firebase_user` RPC → `auth.users`/`user_profiles` upsert. The test suite mocks or skips auth entirely.
- Files: `app/auth/session.py`, `migrations/008_provision_firebase_user.sql`, `tests/test_auth_session.py` (only 99 lines, ASGI-only)
- Risk: provisioning regression on a fresh DB (e.g. the RPC not being applied because of the migration-split issue) is not caught.
- Priority: High.

### No regression tests for security audit findings
- What's not tested: `/shares/{slug}/encrypt` rejecting a non-owner; `/api/download/group/{slug}` rate limiting; `/u/{username}` returning 200 on a public profile.
- Files: `tests/`
- Risk: the four issues called out in the audit can reappear without notice.
- Priority: High — add one test per finding as the findings are fixed.

### Public endpoints tested only for response codes, not data
- What's not tested: most of `tests/test_all_endpoints.py` (456 lines) asserts 4xx response codes over ASGI transport with no live DB. It catches missing routes and auth-wiring regressions, but nothing about correctness of the data returned.
- Files: `tests/test_all_endpoints.py`
- Risk: queries that return the wrong rows (e.g. a missing `.eq("user_id", ...)` filter) pass the suite.
- Priority: Medium.

---

*Concerns audit: 2026-08-12*
