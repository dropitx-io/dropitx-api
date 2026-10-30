# Phase 1: Security Hardening - Research

**Researched:** 2026-08-15
**Domain:** FastAPI backend hardening — broken access control (CWE-862/CWE-284), missing rate limiting (CWE-770), one-line runtime bug (CWE-457-adjacent NameError)
**Confidence:** HIGH

## Summary

This phase closes six findings from the 2026-08-12 security audit
(`plans/reports/security-audit-260812-1452-public-endpoint-auth-ratelimit-report.md`).
All six fixes are **surgical, in-repo, convention-following changes** — no new
libraries, no schema migrations, no new infrastructure. Every fix has an exact
existing pattern to mirror, already read and verified this session:

- **SEC-01** (`encrypt_share` takeover): `app/public/encryption.py` already
  defines `_authorize_owner(row, user, delete_token)` at line 99 — it is dead
  code, never called. `app/public/shares.py`'s `set_password`/`burn`/`delete`
  call it correctly. The fix is to wire the identical call + `Depends(get_optional_user)`
  into `encrypt_share`, copying the `set_password` shape exactly.
- **SEC-02** (`reencrypt` brute force): `core/rate_limit.py`'s
  `check_password_rate_limit(ip, slug)` already exists and is used by
  `unlock_share`/`download_share`. `reencrypt_share` needs the identical call,
  in the identical position (before `_fetch_share_for_encrypt`, mirroring
  `unlock_share`'s check-before-fetch order) — no new rate-limit function needed.
- **SEC-03** (`bulk_download_group` DoS): needs a new rate-limit function in
  `core/rate_limit.py` following the existing `_check_rpc`-wrapper pattern.
  The audit explicitly names `check_upload_rate_limit`-equivalent (10/60s,
  fail-open) as the target shape.
- **SEC-04** (public read paths): needs one new rate-limit function
  following the existing `check_oembed_rate_limit` shape (60/60s, fail-open).
  All three target routes (`content`, `download`, `preview`) **already accept
  a `request: Request` parameter** — no signature change needed, only a new
  rate-limit call inserted.
- **SEC-05** (`domains/resolve`): no shared-secret/internal-auth infrastructure
  exists anywhere in this codebase (`core/config.py` has no such field, no
  header-check helper exists). Given REQUIREMENTS.md phrases this as
  "shared secret header **OR** a rate limit," and the audit itself says "at
  minimum rate-limit by IP," the minimal-viable fix is a new rate-limit
  function + call, matching the SEC-04 pattern. A shared-secret header is a
  larger change (new `Settings` field + reverse-proxy-side coordination
  outside this repo) and should be a discretionary follow-up, not required
  scope.
- **SEC-06** (`GET /api/u/{username}` 500): confirmed at
  `app/public/profiles.py:72` — `.eq("is_public", true)` uses the bare
  identifier `true`, undefined in Python, raising `NameError` caught by the
  surrounding `except Exception` and converted to a 500. One-character fix:
  `True`. `core/db.py`'s `QueryBuilder.eq()` takes `val: Any` and stores it
  as a raw filter value — a Python `bool` is a valid value here (confirmed
  by reading the method), so `True` requires no further shim changes.

**Primary recommendation:** Treat this phase as six independent, additive
patches to existing files — no refactors, no new modules. Add two or three
new small functions to `core/rate_limit.py` (following the existing
`_check_rpc()` wrapper pattern), wire `_authorize_owner`/rate-limit calls
into the five broken routes, and fix the one-character bug in `profiles.py`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Anonymous callers cannot encrypt or overwrite an existing share — `POST /shares/{slug}/encrypt` requires owner JWT or `delete_token`, mirroring `_authorize_owner` | Pattern 1 — exact call site and code diff, using the already-defined-but-unused `_authorize_owner` in `app/public/encryption.py:99` |
| SEC-02 | Repeated password guesses against `POST /shares/{slug}/reencrypt` are rate-limited (fail-closed), consistent with `/unlock` | Pattern 2 — reuse `check_password_rate_limit` verbatim, in the same check-before-fetch order as `unlock_share` |
| SEC-03 | `GET /api/download/group/{slug}` enforces a per-IP rate limit before downloading files and building a ZIP in memory | Pattern 3 — new `check_bulk_download_rate_limit` function + wiring into `bulk_download_group` |
| SEC-04 | Public read paths (`content`, `download`, `preview`) enforce a lightweight per-IP rate limit distinct from the password-only throttle | Pattern 3 — new `check_public_read_rate_limit` function; all three routes already accept `request: Request`, no signature change needed |
| SEC-05 | `GET /api/dashboard/domains/resolve/{domain}` is protected by an internal-only guard or a rate limit | Pattern 3 — new `check_domain_resolve_rate_limit` function + wiring; shared-secret header path documented as an out-of-scope alternative (no infra exists for it yet) |
| SEC-06 | `GET /api/u/{username}` returns 200 instead of erroring on every call (`true` → `True` bug fix) | Pattern 4 — exact line (`app/public/profiles.py:72`), confirmed root cause via `core/db.py`'s `QueryBuilder.eq()` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Owner authorization on mutating share routes | API/Backend (`app/public/encryption.py`) | — | `_authorize_owner` is a route-layer guard; no DB schema change needed, `user_id`/`delete_token` columns already exist |
| Per-IP/per-key rate limiting | API/Backend (`core/rate_limit.py`) | Database (Postgres `check_rate_limit` RPC + `rate_limits` table) | Counting/windowing logic lives in the Postgres function; the Python layer only supplies key/limit/window and interprets the result |
| Internal-endpoint guard (`domains/resolve`) | API/Backend | — | No reverse-proxy-injected header exists yet in this repo; enforcement has to happen at the route/dependency layer for now |
| `NameError` bug fix (`profiles.py`) | API/Backend | Database (query-shim `QueryBuilder.eq`) | Bug is in the route's filter call, not the shim — shim already accepts arbitrary Python values |

## Standard Stack

No new libraries are required for this phase. Every fix reuses code already
present in the repo.

### Core (existing, reused)
| Component | Location | Purpose | Why Standard (for this repo) |
|-----------|----------|---------|-------------------------------|
| `_authorize_owner(row, user, delete_token)` | `app/public/shares.py:129` (canonical), `app/public/encryption.py:99` (duplicate, unused) | Owner-or-delete-token authorization check | Already the established convention for mutating share routes — `delete_share`, `set_password`, `burn_share` all call it |
| `check_password_rate_limit(ip, slug)` | `core/rate_limit.py:87-89` | 5 attempts / 10 min per IP+slug, fail-closed | Already used by `unlock_share` and the wrong-password branch of `download_share` |
| `_check_rpc(key, max_attempts, window_secs, *, fail_open)` | `core/rate_limit.py:36-79` | Generic Postgres-RPC-backed rate-limit primitive | Every existing `check_*_rate_limit` function is a one-line wrapper around this; new buckets should follow the same shape |
| `get_client_ip(request)` | `app/dependencies.py:175-188` | Extract client IP (X-Forwarded-For → X-Real-IP → `request.client.host`) | Already used everywhere rate limiting is IP-keyed |
| `get_optional_user(request)` | `app/dependencies.py:84-89` | Returns `User \| None` without raising | Used by `delete_share`/`set_password`/`burn_share` to support both JWT-owner and delete-token auth |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Postgres-RPC rate limiting (existing) | In-memory rate limiter (e.g. `slowapi`, a dict-based token bucket) | Would be faster and avoid a DB round-trip, but breaks the fail-open/fail-closed semantics already encoded per-bucket in this codebase, and would only work with a single API process (no shared state across replicas/pods). Not worth introducing for this phase — stick with the existing convention. |
| New `_authorize_owner` call in `encrypt_share` | Require JWT-only (drop `delete_token` support) | Would break the anonymous-share delete-token UX that already works for `delete`/`set-password`/`burn`. Not requested by SEC-01, would be a silent product-decision reversal. |
| Rate limit for `domains/resolve` | Shared-secret header set by reverse proxy | Stronger guarantee, but requires a new `Settings` field and reverse-proxy config changes outside this repo's control (Cloudflare Tunnel config was not found anywhere in this repo — `grep` for "cloudflare"/"tunnel" only matched the Dokploy review doc). Treat as a discretionary stretch goal, not the phase's minimum bar. |

**Installation:** None — no new dependencies. `requirements.txt`/`pyproject.toml`
already contain everything needed (`fastapi`, `asyncpg`, `bcrypt`, `cryptography`).

## Package Legitimacy Audit

**Not applicable.** This phase installs no new external packages — every fix
reuses existing in-repo functions (`_authorize_owner`, `_check_rpc`,
`get_client_ip`, `get_optional_user`) or is a one-character bug fix. No
`npm view` / `pip index` / registry check is needed.

## Architecture Patterns

### System Architecture Diagram

```
                     Cloudflare Tunnel (public internet)
                                  │
                                  ▼
                        FastAPI app (app/main.py)
                        ┌─────────────────────────┐
                        │  no global rate-limit    │
                        │  middleware — CORS only  │
                        └─────────────────────────┘
                                  │
              ┌───────────────────┼──────────────────────┐
              ▼                   ▼                       ▼
     app/public/encryption.py  app/public/shares.py   app/internal/download.py
     app/public/preview.py     app/dashboard/domains.py
              │                   │                       │
              │  [MISSING today]  │  [existing, correct]   │  [MISSING today]
              │  owner check /    │  _authorize_owner()    │  rate limit
              │  rate limit call  │  check_password_       │  call
              │                   │  rate_limit()          │
              ▼                   ▼                       ▼
                        core/rate_limit.py
                     ┌───────────────────────────┐
                     │ check_upload_rate_limit    │  10/60s  fail-open
                     │ check_password_rate_limit  │  5/600s  fail-closed
                     │ check_oembed_rate_limit    │  60/60s  fail-open
                     │ check_analytics_rate_limit │  60/60s  fail-open
                     │ [NEW] check_bulk_download_ │
                     │        rate_limit          │  10/60s  fail-open (SEC-03)
                     │ [NEW] check_public_read_   │
                     │        rate_limit          │  60/60s  fail-open (SEC-04)
                     │ [NEW] check_domain_resolve_│
                     │        rate_limit          │  60/60s  fail-open (SEC-05)
                     └───────────────────────────┘
                                  │
                                  ▼
                     Postgres RPC check_rate_limit(key, max, window)
                     (infra/init/01_schema.sql:436-460, rate_limits table)
                                  │
                                  ▼
                     app/public/profiles.py:72
                     .eq("is_public", true)  →  NameError → 500  (SEC-06)
                     Fix: .eq("is_public", True)
```

### Recommended file-level changes (no new files)
```
app/public/encryption.py   # SEC-01, SEC-02 — wire _authorize_owner + rate limit into encrypt_share/reencrypt_share
app/internal/download.py   # SEC-03 — add Request param, get_client_ip, new rate-limit call
app/public/shares.py       # SEC-04 — add rate-limit call to get_share_content, download_share
app/public/preview.py      # SEC-04 — add rate-limit call to get_share_preview (Request already present)
app/dashboard/domains.py   # SEC-05 — add Request param, get_client_ip, new rate-limit call to resolve_custom_domain
app/public/profiles.py     # SEC-06 — one-line fix: true -> True
core/rate_limit.py         # SEC-03/04/05 — add up to 3 new check_*_rate_limit functions
tests/test_all_endpoints.py           # add auth/rate-limit-guard tests, mirroring existing no-auth tests
tests/test_encryption.py (or new)     # add auth-guard test for encrypt_share
tests/test_one_time_download.py-style # add rate-limit-tolerant tests for reencrypt/bulk-download/domain-resolve
```

### Pattern 1: Owner-or-delete-token authorization (SEC-01)
**What:** Require either `user.id == row["user_id"]` (JWT owner) or a matching
`delete_token` in the request body before mutating a share.
**When to use:** Any route that mutates an existing share by slug.
**Example (verified — mirrors `set_password` in `app/public/shares.py:318-346`):**
```python
# app/public/encryption.py — encrypt_share, fixed
from app.dependencies import User, get_current_user, get_optional_user

@router.post("/shares/{slug}/encrypt", ...)
async def encrypt_share(
    slug: str,
    body: EncryptShareRequest,
    user: User | None = Depends(get_optional_user),
):
    row = await _fetch_share_for_encrypt(slug)

    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    _authorize_owner(row, user, body.delete_token)

    if row.get("encrypted"):
        raise HTTPException(status_code=400, detail="Share is already encrypted...")
    # ...rest unchanged
```
`_authorize_owner` itself needs **no changes** — it is already defined
correctly in this file (`app/public/encryption.py:99-105`), just unused.

### Pattern 2: Password-guess rate limiting, fail-closed, checked before fetch (SEC-02)
**What:** Rate-limit password-guessing endpoints by `ip:slug`, fail closed
(deny on RPC error) so the endpoint is not left unprotected during a DB outage.
**When to use:** Any endpoint that accepts a password/secret guess against a
specific resource.
**Example (verified pattern — mirrors `unlock_share` in `app/public/shares.py:353-368`):**
```python
# app/public/encryption.py — reencrypt_share, fixed
from app.dependencies import get_client_ip
from core.rate_limit import check_password_rate_limit
from fastapi import Request

@router.post("/shares/{slug}/reencrypt", ...)
async def reencrypt_share(
    slug: str,
    request: Request,
    body: ReencryptShareRequest,
):
    ip = get_client_ip(request)
    rate = check_password_rate_limit(ip, slug)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share_for_encrypt(slug)
    # ...rest unchanged (old_password decrypt is already self-gating)
```
**Note:** the rate-limit check happens *before* `_fetch_share_for_encrypt`,
matching `unlock_share`'s order — this is what makes the fail-closed
behavior effective even when the share doesn't exist (prevents slug
enumeration from bypassing the throttle).

### Pattern 3: New cost-based rate-limit bucket (SEC-03, SEC-04, SEC-05)
**What:** A one-line wrapper around the existing `_check_rpc` primitive,
following the exact shape of `check_upload_rate_limit`/`check_oembed_rate_limit`.
**When to use:** Any endpoint needing IP-based throttling where availability
is favored over strict security (fail-open).
**Example (new code, following verified existing shape in `core/rate_limit.py:82-94`):**
```python
# core/rate_limit.py — additions

def check_bulk_download_rate_limit(ip: str) -> RateLimitResult:
    """10 bulk-download requests per minute per IP. Fail-open."""
    return _check_rpc(f"bulkdl:{ip}", max_attempts=10, window_secs=60, fail_open=True)


def check_public_read_rate_limit(ip: str) -> RateLimitResult:
    """60 public share reads (content/download/preview) per minute per IP. Fail-open."""
    return _check_rpc(f"read:{ip}", max_attempts=60, window_secs=60, fail_open=True)


def check_domain_resolve_rate_limit(ip: str) -> RateLimitResult:
    """60 domain-resolve lookups per minute per IP. Fail-open."""
    return _check_rpc(f"domresolve:{ip}", max_attempts=60, window_secs=60, fail_open=True)
```
Wiring into `bulk_download_group` (SEC-03, `app/internal/download.py:71`):
```python
from fastapi import Request
from app.dependencies import get_client_ip
from core.rate_limit import check_bulk_download_rate_limit

@router.get("/download/group/{slug}", ...)
async def bulk_download_group(slug: str, request: Request):
    ip = get_client_ip(request)
    rate = check_bulk_download_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429, detail="Too many requests. Try again later.",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )
    group = await _fetch_group(slug)
    # ...rest unchanged
```
Wiring into public reads (SEC-04) — `get_share_content` and `download_share`
in `app/public/shares.py` and `get_share_preview` in `app/public/preview.py`
**already have a `request: Request` parameter** — only the rate-limit call
needs to be inserted near the top of each function body, e.g.:
```python
from core.rate_limit import check_public_read_rate_limit
# inside get_share_content(slug, request):
ip = get_client_ip(request)
rate = check_public_read_rate_limit(ip)
if not rate.success:
    raise HTTPException(status_code=429, detail="Too many requests. Try again later.",
                         headers={"Retry-After": str(max(rate.reset, 1))})
```
`app/public/shares.py` already imports `get_client_ip`; `app/public/preview.py`
already imports `get_client_ip` too (`app/public/preview.py:18`) but not
`core.rate_limit` — that import needs adding.

Wiring into `domains/resolve` (SEC-05, `app/dashboard/domains.py:352-353`):
```python
from fastapi import Request
from app.dependencies import get_client_ip
from core.rate_limit import check_domain_resolve_rate_limit

@router.get("/domains/resolve/{domain}", tags=["Custom Domains"], include_in_schema=False)
async def resolve_custom_domain(domain: str, request: Request):
    ip = get_client_ip(request)
    rate = check_domain_resolve_rate_limit(ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Too many requests.",
                             headers={"Retry-After": str(max(rate.reset, 1))})
    # ...rest unchanged
```

### Pattern 4: `.eq()` filter value must be a real Python value, not a bare identifier (SEC-06)
**What:** `core/db.py`'s `QueryBuilder.eq(col, val)` stores `val` as-is in a
filter tuple; it is later bound as a parameterized SQL value — any Python
value works, including `bool`.
**Verified:** `core/db.py:212-213`:
```
def eq(self, col: str, val: Any) -> "QueryBuilder":
    self._filters.append((col, "=", val)); return self
```
**The fix (`app/public/profiles.py:72`):**
```python
# before (bare `true` — undefined name, raises NameError)
.eq("is_public", true)
# after
.eq("is_public", True)
```
No other code changes needed — the shim already accepts `True`/`False` as
ordinary Python values (there is no special-casing that would reject a bool).

### Anti-Patterns to Avoid
- **Adding a new ad-hoc rate-limit implementation:** every existing bucket is
  a thin wrapper around `_check_rpc`. Do not write a new Postgres query, a new
  in-memory counter, or a new middleware — extend `core/rate_limit.py` the
  same way the existing five functions do.
- **Changing `_authorize_owner`'s signature or duplicating it a third time:**
  it already exists, correctly, in both `shares.py` and `encryption.py`.
  Consolidating it into a shared module is out of scope for this phase (would
  be a refactor, not a fix) — just call the existing local copy in
  `encryption.py`.
- **Silently adding an ownership check to `reencrypt_share`:** REQUIREMENTS.md's
  SEC-02 only asks for rate limiting on `reencrypt`, not an ownership check
  (unlike SEC-01 for `encrypt`). The audit report separately flags the missing
  ownership check on `reencrypt` as a secondary observation, not as SEC-02's
  scope. See Open Questions — confirm with the user/planner before expanding
  scope beyond the stated requirement.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-IP/per-key rate limiting | A new middleware, in-memory counter, or Redis-backed limiter | `core.rate_limit._check_rpc()` + a new one-line wrapper function | Every existing bucket already works this way; introducing a second rate-limiting mechanism would create inconsistent behavior across routes and complicate the (already-flagged) fail-open/fail-closed semantics |
| Owner-or-token authorization | A new decorator or FastAPI dependency class | The existing `_authorize_owner(row, user, delete_token)` function, called directly in the route body | Already proven correct in three routes (`delete`, `set-password`, `burn`); a new abstraction adds risk without benefit for a security-fix phase |
| Internal-only endpoint protection | A bespoke IP-allowlist or mTLS setup | Rate limiting (matches REQUIREMENTS.md's stated "OR a rate limit" acceptance bar) | No shared-secret infrastructure exists yet in this repo; building one is a larger, cross-cutting change better suited to a dedicated follow-up, not a minimal security patch |

**Key insight:** Every fix in this phase is a "wire up what already exists"
change, not a "design something new" change. The audit itself points at each
existing pattern to copy. Resist the urge to refactor `_authorize_owner` into
a shared module, introduce a rate-limiting decorator, or build a general
internal-auth mechanism — all three would expand this phase's blast radius
well beyond "make 6 specific, already-diagnosed bugs stop being exploitable."

## Common Pitfalls

### Pitfall 1: Rate-limit check ordering changes fail-closed behavior
**What goes wrong:** If the rate-limit check is placed *after* `_fetch_share`/
`_fetch_share_for_encrypt`/`_fetch_group`, an attacker who targets a
nonexistent slug never triggers the throttle (the 404 short-circuits first),
so the rate limit only protects real, existing resources.
**Why it happens:** It's natural to write "fetch row, then check things about
it" — but rate limiting is about protecting the *endpoint*, not the resource.
**How to avoid:** Check the rate limit **first**, exactly where `unlock_share`
does it (`app/public/shares.py:359-367`, before `_fetch_share`).
**Warning signs:** A rate-limit test against an unknown slug never returns 429.

### Pitfall 2: Fail-open vs fail-closed must match the security profile of the bucket, not be copy-pasted blindly
**What goes wrong:** Copying `check_upload_rate_limit`'s fail-open pattern for
a password-guessing bucket (or vice versa) either allows unlimited guessing
during a DB outage, or turns a minor cost-control measure into a hard outage
dependency.
**Why it happens:** The five existing buckets split cleanly: password-guessing
buckets are fail-closed (`check_password_rate_limit`); cost/abuse buckets are
fail-open (`upload`, `oembed`, `analytics`). It's easy to miss this split when
adding new buckets.
**How to avoid:** SEC-02 (password guessing) reuses the existing fail-closed
`check_password_rate_limit` directly — no new function needed. SEC-03/04/05
are all cost/DoS/low-value-leak concerns, not credential-guessing, so
fail-open (matching `check_upload_rate_limit`/`check_oembed_rate_limit`) is
the right default, consistent with existing convention. `[ASSUMED]` — this
fail-open choice for SEC-03/04/05 is a design recommendation based on
convention-matching, not dictated verbatim by REQUIREMENTS.md; confirm with
the user if a stricter (fail-closed) posture is actually wanted for the
bulk-download DoS vector given its higher resource cost per request.

### Pitfall 3: `get_optional_user` swallows *all* `HTTPException`s from `get_current_user`, including 500s
**What goes wrong:** `get_optional_user` (`app/dependencies.py:84-89`) catches
`HTTPException` broadly — including `get_current_user`'s `raise HTTPException(500, ...)`
on a DB lookup failure (line 70-72). If the DB is briefly down, an owner's
valid JWT would be silently treated as "no user" instead of surfacing a 500,
which for `encrypt_share`/`reencrypt_share` would incorrectly fall through to
"authentication required" (401) instead of the real 500 error.
**Why it happens:** Pre-existing behavior in `get_optional_user`, unrelated
to this phase, but directly relevant since SEC-01 newly depends on it.
**How to avoid:** This is existing, accepted behavior already relied upon by
`delete_share`/`set_password`/`burn_share` — do not attempt to fix it as part
of this phase (out of scope; would change shared dependency behavior for
every route that already uses `get_optional_user`). Just be aware test
assertions for encrypt_share's auth guard should tolerate a 401 in this edge
case, matching the existing tests for `set_password_no_auth` etc.
**Warning signs:** A test expects a crisp 500 for a DB-down scenario when
`get_optional_user` is in the dependency chain and instead gets 401.

### Pitfall 4: `preview.py` and `domains.py` don't import `core.rate_limit` or `Request`/`get_client_ip` yet
**What goes wrong:** Forgetting to add the necessary imports causes an
`ImportError`/`NameError` at request time (exactly the class of bug SEC-06 is
fixing) rather than at collection/lint time, since these are inside function
bodies referencing module-level names.
**Why it happens:** `preview.py` imports `get_client_ip` already but not
`core.rate_limit`; `domains.py` imports neither `Request` nor `get_client_ip`
nor `core.rate_limit` today (verified by reading both files' import blocks).
**How to avoid:** Explicitly add `from core.rate_limit import check_public_read_rate_limit`
to `preview.py`, and `from fastapi import Request`, `from app.dependencies import get_client_ip`,
`from core.rate_limit import check_domain_resolve_rate_limit` to `domains.py`.
**Warning signs:** `NameError: name 'Request' is not defined` at runtime on
the first request to `/api/dashboard/domains/resolve/{domain}` — silently
caught by no exception handler in that function today, would surface as a
raw 500.

### Pitfall 5: The `models/domain.py`-adjacent test suite already asserts the exact route path for `domains/resolve`
**What goes wrong:** `tests/test_custom_domains.py:141` (`TestDomainRoutesExist`)
asserts `"/api/dashboard/domains/resolve/{domain}"` is a registered path.
Adding a `request: Request` parameter to `resolve_custom_domain` does not
change the route path or method, so this existing test keeps passing — but
it's worth being aware this file already has assertions coupled to this exact
function, in case the planner considers renaming the route.
**How to avoid:** Don't rename/move the route; only add the parameter and the
rate-limit call inside the function body.

## Code Examples

See the four patterns above (Owner-or-token authorization, password-guess
rate limiting, new cost-based rate-limit bucket, `.eq()` boolean fix) — all
code is sourced from files read in this repo this session:
- `app/public/encryption.py` (read in full, lines 1-335)
- `app/public/shares.py` (read in full, lines 1-638)
- `app/public/preview.py` (read in full, lines 1-382)
- `app/public/profiles.py` (read in full, lines 1-189)
- `app/internal/download.py` (read in full, lines 1-120)
- `app/dashboard/domains.py` (lines 340-379 read)
- `core/rate_limit.py` (read in full, lines 1-101)
- `core/db.py` (lines 1-100, 176-260 read)
- `app/dependencies.py` (read in full, lines 1-201)
- `core/config.py` (read in full, lines 1-34)

## State of the Art

Not applicable in the usual "ecosystem changed" sense — this is a bugfix
phase against the team's own pre-existing conventions, not a library upgrade.
The one relevant "before/after" is architectural, not chronological:

| Old Assumption | Current Reality | When Changed | Impact |
|--------------|------------------|--------------|--------|
| These endpoints are only reachable from the known frontend/internal network | Reachable from the public internet via Cloudflare Tunnel | Noted in STATE.md/PROJECT.md as of this roadmap (2026-08-15) | Endpoints written assuming implicit trust (no auth/rate-limit) are now internet-facing attack surface — this is the entire premise of the phase |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SEC-03/04/05's new rate-limit buckets should be fail-open (matching `check_upload_rate_limit`/`check_oembed_rate_limit`), not fail-closed like `check_password_rate_limit` | Pitfall 2, Pattern 3 | If the user actually wants fail-closed for the bulk-download DoS vector (given its ~10GB/request cost), a fail-open implementation would still allow the DoS during a Postgres outage — the exact scenario a fail-closed choice would prevent. Low-to-medium risk: matches existing codebase convention, but the audit doesn't dictate this explicitly. |
| A2 | The exact numeric rate limits chosen for the 3 new buckets (bulk-download 10/60s, public-read 60/60s, domain-resolve 60/60s) are reasonable defaults | Pattern 3 | These are directly modeled on existing sibling buckets (`check_upload_rate_limit`, `check_oembed_rate_limit`) per the audit's own recommendation language ("check_upload_rate_limit-equivalent", "reuse... 60/min-per-IP helper"), so risk is low, but the domain-resolve number (60/60s) is not explicitly stated anywhere in the audit — it's inferred by matching the oEmbed-style shape since domain-resolve is similarly a low-value-leak/probe-surface concern, not a brute-force target. |
| A3 | `reencrypt_share` should NOT gain an ownership/`_authorize_owner` check as part of this phase, only rate limiting | Anti-Patterns, Pitfall notes | If the user intended SEC-02 to also close the "missing ownership check on reencrypt" secondary finding from the audit, scoping it out here under-delivers. Medium risk — flagged explicitly as an Open Question below for the planner/user to confirm before finalizing SEC-02's task list. |
| A4 | A shared-secret header guard for `domains/resolve` (SEC-05's other acceptable option) is out of scope for this phase; rate limiting alone satisfies SEC-05 | Standard Stack (Alternatives Considered), Don't Hand-Roll | If Cloudflare Tunnel / reverse-proxy config elsewhere (not in this repo) already expects a header-based guard, deferring it could leave a gap the user was expecting closed. Low risk — REQUIREMENTS.md phrases SEC-05 as an "OR", and no header-check infra exists in this repo to build on. |

## Open Questions

1. **Should `reencrypt_share` also get an ownership check, not just rate limiting?**
   - What we know: REQUIREMENTS.md's SEC-02 text and the phase's Success
     Criteria #2 both describe only rate limiting for `reencrypt`. The audit
     report's Critical Finding #1 separately notes `reencrypt` "is also
     missing the explicit owner/delete-token check" as a secondary
     observation under the `encrypt` finding, not as its own line item.
   - What's unclear: whether the roadmap author intended SEC-02 to be
     rate-limiting-only (since `old_password` is already self-gating) or
     whether an ownership check should be bundled in for defense-in-depth.
   - Recommendation: Plan SEC-02 as rate-limiting-only (matching the literal
     requirement text) but flag as a one-line addition to also add
     `_authorize_owner` if the user wants tighter scope — low cost either way
     since the helper and pattern already exist.

2. **Is `GET /api/download/group/{slug}` still an active, used feature?**
   - What we know: The audit's own "Unresolved Questions" section raises this
     exact question — "Is `/api/download/group/{slug}` actually used by any
     current frontend flow, or is it dead/future functionality?"
   - What's unclear: No answer was found in this repo (dropitx-api); would
     require checking the frontend `dropitx/` repo's usage of this endpoint,
     which is out of scope for this research pass.
   - Recommendation: Proceed with adding the rate limit (SEC-03's literal
     requirement) regardless of the answer — it's the safe default whether or
     not the route is actively used, and doesn't block on cross-repo
     verification.

3. **Should the numeric rate limits (10/60s, 60/60s) be tunable via
   `core/config.py` `Settings` rather than hardcoded, matching how existing
   buckets are hardcoded?**
   - What we know: All five existing `check_*_rate_limit` functions hardcode
     their `max_attempts`/`window_secs` values directly in the function body
     — there is no existing precedent for making these configurable via
     `Settings`.
   - What's unclear: Whether this phase should introduce configurability as a
     bonus, or strictly match the existing hardcoded-constant convention.
   - Recommendation: Match the existing convention (hardcoded) for
     consistency and minimal diff — introducing configurability here would be
     scope creep beyond "fix these 6 findings."

## Environment Availability

Skipped — this phase requires no new external tools, services, runtimes, or
CLIs. All fixes touch existing Python modules and reuse the already-running
local Postgres RPC (`check_rate_limit`). No new environment dependency is
introduced.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ≥ 8.0 + pytest-asyncio ≥ 0.24 (`[tool.pytest.ini_options]` in `pyproject.toml`, `asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| Quick run command | `pytest tests/test_all_endpoints.py -v` (ASGI transport, no live DB required per file's own docstring) |
| Full suite command | `pytest` (some files require `docker compose up -d` first per `CLAUDE.md`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | `POST /shares/{slug}/encrypt` rejects anonymous callers (401) without owner JWT/delete_token | integration (ASGI, no DB) | `pytest tests/test_all_endpoints.py -k encrypt_share_no_auth -x` | ❌ Wave 0 — new test, mirror `test_set_password_no_auth` |
| SEC-02 | `POST /shares/{slug}/reencrypt` returns 429 after repeated attempts | integration (ASGI, DB-tolerant) | `pytest tests/test_one_time_download.py -k reencrypt -x` (or a new test module) | ❌ Wave 0 — new test, mirror `test_unlock_not_found`'s `(404, 500, 429)`-tolerant pattern |
| SEC-03 | `GET /api/download/group/{slug}` returns 429 under repeated requests | integration (ASGI, DB-tolerant) | `pytest tests/test_all_endpoints.py -k download_group -x` | ⚠️ Wave 0 partial — `test_download_group_not_found` exists (404-only); needs a companion rate-limit test |
| SEC-04 | `content`/`download`/`preview` reject bursts per IP with 429 | integration (ASGI, DB-tolerant) | `pytest tests/test_all_endpoints.py -k "content or download or preview" -x` | ❌ Wave 0 — new tests |
| SEC-05 | `domains/resolve/{domain}` rejects excessive requests, no longer freely callable | integration (ASGI, DB-tolerant) | `pytest tests/test_custom_domains.py -k resolve -x` | ❌ Wave 0 — new test |
| SEC-06 | `GET /api/u/{username}` returns 200/404, never 500 for a `NameError` | integration (ASGI, DB-tolerant) | new: `pytest tests/test_all_endpoints.py -k public_profile -x` | ❌ Wave 0 — no existing test file for `profiles.py` routes at all |

### Sampling Rate
- **Per task commit:** `pytest tests/test_all_endpoints.py -v` (fast, no DB needed)
- **Per wave merge:** `pytest` (full suite; requires `docker compose up -d` for DB-backed files per `CLAUDE.md`)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_all_endpoints.py` — add `test_encrypt_share_no_auth` (SEC-01), mirroring `test_set_password_no_auth` (line 239-243)
- [ ] `tests/test_all_endpoints.py` (or new `tests/test_profiles.py`) — add coverage for `GET /api/u/{username}` (SEC-06); **no existing test file touches `app/public/profiles.py` at all** — this is the largest single test gap in the phase
- [ ] A new or existing test module — rate-limit-tolerant tests for `reencrypt` (SEC-02), `download/group/{slug}` (SEC-03), `content`/`download`/`preview` (SEC-04), `domains/resolve` (SEC-05), following the existing `assert resp.status_code in (404, 500, 429)`-style tolerant pattern from `tests/test_one_time_download.py:136-137`
- [ ] No framework install needed — pytest/pytest-asyncio already configured

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V4 Access Control | yes | Object-level/function-level authorization check before mutation — `_authorize_owner(row, user, delete_token)`, already the established pattern in this codebase (SEC-01) |
| V11 Business Logic / Anti-Automation | yes | Per-IP and per-IP+resource rate limiting via the existing Postgres-RPC-backed `check_*_rate_limit` functions (SEC-02, SEC-03, SEC-04, SEC-05) |
| V2 Authentication | no (unchanged) | This phase does not touch the JWT/Firebase auth mechanism itself — that's Phase 2's scope (AUTH-01..05) |
| V5 Input Validation | no (unchanged) | Existing Pydantic models (`EncryptShareRequest`, etc.) already validate inputs; this phase doesn't add new user-supplied fields |
| V6 Cryptography | no (unchanged) | AES-256-GCM + PBKDF2 encryption logic in `core/encryption.py` is out of scope — only the *authorization* wrapping around `encrypt_share`/`reencrypt_share` is being fixed, not the crypto itself |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Broken Object-Level Authorization (BOLA) — mutate another user's resource by guessing/knowing its identifier (slug) | Tampering / Elevation of Privilege | Owner-or-delete-token check before any mutation (`_authorize_owner`) — SEC-01 |
| Unbounded resource consumption — build an arbitrarily large in-memory artifact (ZIP) per unauthenticated request | Denial of Service | Per-IP rate limiting before the expensive operation begins (SEC-03) |
| Credential/secret brute-forcing against a per-resource secret (password) | Information Disclosure / Elevation of Privilege | Fail-closed per-IP+resource rate limiting (`check_password_rate_limit`, already used by `unlock_share`; SEC-02 reuses it as-is) |
| Information leakage via an internal-only endpoint reachable from the public internet due to changed network topology (Cloudflare Tunnel) | Information Disclosure | Rate limiting as a minimum bar (per REQUIREMENTS.md's stated "OR"); shared-secret header as a stronger option deferred as a discretionary follow-up (SEC-05) |
| Unhandled exception in a public-by-design endpoint causing 100% failure rate | Denial of Service (self-inflicted) | Fix the root-cause bug (`true` → `True`) rather than broadening the `except Exception` handler (SEC-06) |

## Sources

### Primary (HIGH confidence — all files read directly this session)
- `plans/reports/security-audit-260812-1452-public-endpoint-auth-ratelimit-report.md` — source audit, read in full
- `app/public/encryption.py`, `app/public/shares.py`, `app/public/preview.py`, `app/public/profiles.py`, `app/internal/download.py` — read in full
- `app/dashboard/domains.py:340-379`, `app/dependencies.py` (full), `core/rate_limit.py` (full), `core/db.py:1-100,176-260`, `core/config.py` (full) — read directly
- `infra/init/01_schema.sql:420-460` — `check_rate_limit` RPC definition, read directly
- `tests/test_all_endpoints.py` (relevant sections), `tests/test_one_time_download.py:100-150`, `tests/test_custom_domains.py` (full), `tests/test_encryption.py` (full), `tests/test_dependencies.py` (grep-confirmed patterns) — read directly
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/PROJECT.md`, `.planning/config.json` — read in full

### Secondary (MEDIUM confidence)
- None — this phase required no external documentation lookups; every claim is grounded in files read this session.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all reused code read directly this session
- Architecture: HIGH — every file touched by this phase was read in full or in the relevant section
- Pitfalls: HIGH — derived from direct comparison of the broken routes against the correctly-implemented sibling routes in the same files

**Research date:** 2026-08-15
**Valid until:** No expiry driver — this is a static in-repo bugfix phase, not tied to an external library's release cadence. Re-verify only if `app/public/encryption.py`, `app/public/shares.py`, `core/rate_limit.py`, `app/dashboard/domains.py`, or `app/public/profiles.py` change before this phase is executed.
