---
phase: 01-security-hardening
reviewed: 2026-08-15T15:41:09Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - app/dashboard/domains.py
  - app/internal/download.py
  - app/public/encryption.py
  - app/public/preview.py
  - app/public/profiles.py
  - app/public/shares.py
  - core/rate_limit.py
  - tests/test_all_endpoints.py
  - tests/test_custom_domains.py
  - tests/test_profiles.py
  - tests/test_rate_limit_boundaries.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 01-security-hardening: Code Review Report

**Reviewed:** 2026-08-15T15:41:09Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the diff range `691e365^..HEAD` (8 commits) that closes the 6 security-audit findings: SEC-01 (missing owner authorization on `encrypt_share`), SEC-02..05 (missing rate-limiting on `reencrypt_share`, bulk-download, public-reads, domain-resolve), and SEC-06 (`NameError` on `true` vs `True` in the public profile route).

All 6 findings are addressed correctly at the point of the individual fix:

- **SEC-01** — `encrypt_share` (`app/public/encryption.py:161-183`) now requires `get_optional_user` and calls the (previously dead-code) `_authorize_owner` helper before proceeding. Verified against the pre-fix commit (`691e365^`): `_authorize_owner` existed in `encryption.py` but was never invoked by `encrypt_share` — this is exactly the vulnerability, and the fix wires it in correctly, matching the same pattern already used by `delete_share`/`set_password`/`burn_share` in `shares.py`.
- **SEC-02..05** — `check_bulk_download_rate_limit`, `check_public_read_rate_limit`, `check_domain_resolve_rate_limit` added to `core/rate_limit.py:97-109` and correctly wired into `reencrypt_share`, `bulk_download_group`, `get_share_content`, `download_share`, `get_share_preview`, and `resolve_custom_domain` — in every case the rate check runs **before** any DB/storage fetch, matching each function's documented ordering.
- **SEC-06** — `true` → `True` in `app/public/profiles.py:71` is correct and verified with a grep sweep of all 7 reviewed source files for the same bare-lowercase-literal mistake (no other occurrences found).

Cross-file tracing turned up one finding that undercuts the effectiveness of SEC-02..05 as shipped: the client-IP extraction all five new rate limiters key off (`get_client_ip` in `app/dependencies.py`) trusts an unauthenticated, client-supplied `X-Forwarded-For`/`X-Real-IP` header with no upstream-proxy validation, and `app/main.py` registers no `TrustedHostMiddleware`/proxy-headers guard. Since every new limiter buckets purely on this string, an attacker can rotate the header value per request and get a fresh rate-limit bucket every time — effectively bypassing all 5 mitigations this phase was meant to deliver. Also flagged: two related test-reliability/quality gaps and one code-duplication debt item. See findings below.

## Critical Issues

### CR-01: All 5 new rate limiters are keyed on a client-spoofable IP, defeating the mitigation

**File:** `app/dependencies.py:175-188` (root cause), consumed by `app/dashboard/domains.py:363-364`, `app/internal/download.py:79-80`, `app/public/encryption.py:269-270`, `app/public/preview.py:295-296`, `app/public/shares.py:154-155,489-490`

**Issue:** `get_client_ip()` returns the first comma-separated value of the client-supplied `X-Forwarded-For` header (or `X-Real-IP`) verbatim, with no check that the request actually passed through a trusted reverse proxy that overwrites/validates that header:

```python
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    ...
```

`app/main.py` registers only `CORSMiddleware` — no `TrustedHostMiddleware`, no proxy-headers allowlist, nothing that strips or re-derives this header before it reaches route code. Every one of this phase's fixes buckets its rate-limit key directly on this value:

- `check_domain_resolve_rate_limit(ip)` — `domains.py:363-364`, explicitly documented as "reachable from the public internet via the Cloudflare Tunnel"
- `check_bulk_download_rate_limit(ip)` — `download.py:79-80`
- `check_password_rate_limit(ip, slug)` in `reencrypt_share` — `encryption.py:269-270`
- `check_public_read_rate_limit(ip)` — `preview.py:295-296`, `shares.py:154-155` and `shares.py:489-490`

An attacker can send a different `X-Forwarded-For` value (or omit it and spoof `X-Real-IP`, or if neither is checked upstream, simply vary a header the app trusts) on every request to get a brand-new rate-limit bucket each time, fully bypassing the 10/min, 60/min, and 5-per-10-min limits this phase set out to add — including the password-brute-force limiter on `reencrypt_share` (SEC-02), which is the one place a bypass has a direct confidentiality impact (unlimited old-password guesses against an encrypted share). This isn't hypothetical: since these endpoints are stated to be reachable directly from the public internet (per the `domains.py` docstring), nothing forces traffic through a proxy that would strip a forged header first.

**Fix:** Either (a) add `TrustedHostMiddleware`/a proxy-aware IP extractor that only trusts `X-Forwarded-For`/`X-Real-IP` when the immediate peer (`request.client.host`) is a known/trusted proxy IP (e.g. Cloudflare's published ranges or an internal LB), falling back to `request.client.host` otherwise; or (b) if fronted unconditionally by Cloudflare, key off `CF-Connecting-IP` (set by Cloudflare's edge, not forgeable past it) instead of the generic forwarded headers, and reject/ignore `X-Forwarded-For` entirely at the origin. Example:

```python
_TRUSTED_PROXY_HEADER = "cf-connecting-ip"  # set by Cloudflare edge, not client-controlled

def get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get(_TRUSTED_PROXY_HEADER)
    if cf_ip:
        return cf_ip.strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"
```

## Warnings

### WR-01: "Public-reads" rate-limiting is incomplete — two public DB-hitting endpoints were left out

**File:** `app/public/encryption.py:132-148` (`get_encryption_info`), `app/public/shares.py:569-593` (`get_download_status`)

**Issue:** SEC-04's stated scope was "missing rate-limiting on ... public-reads," and the fix applied `check_public_read_rate_limit` to `get_share_content`, `download_share`, and `get_share_preview`. Two other unauthenticated, slug-keyed GET endpoints that also hit Postgres on every call were left unrated: `GET /shares/{slug}/encryption-info` and `GET /shares/{slug}/download-status`. Neither is behind any rate limit, so both remain available for unlimited per-slug enumeration/DB-hammering even after this phase.

**Fix:** Apply `check_public_read_rate_limit(get_client_ip(request))` to both routes for consistency with the rest of the public-read surface (both already take/can take a `Request` parameter with minimal signature change).

### WR-02: New SEC-01 regression tests can raise instead of asserting cleanly without a live DB

**File:** `tests/test_all_endpoints.py:260-273` (`test_encrypt_share_no_auth`, `test_encrypt_share_empty_delete_token`)

**Issue:** Both new tests assert `resp.status_code in (401, 404, 500)`, but ran against this module (no `docker compose up -d`) they raise an unhandled `OSError` instead of getting any response back:

```
FAILED tests/test_all_endpoints.py::TestOptionalAuthEndpoints::test_encrypt_share_no_auth
FAILED tests/test_all_endpoints.py::TestOptionalAuthEndpoints::test_encrypt_share_empty_delete_token
...
OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5432)
```

Root cause: `_fetch_share_for_encrypt` (`encryption.py:85-97`, unchanged by this phase) is called *before* the new auth check and has no `try/except` around its DB call, so a DB-connect failure propagates as a raw exception; `httpx.AsyncClient`+`ASGITransport` (used by this test file) has `raise_server_exceptions=True` by default, so it re-raises rather than turning it into an HTTP 500. This is a pre-existing pattern — several older tests in the same file (`test_share_content_not_found`, `test_delete_share_no_auth`, etc., none touched by this phase) fail identically without a DB, confirmed by running the pre-fix version of `download.py`'s equivalent (`test_download_group_not_found`) unchanged. It is **not a regression** introduced by this phase, but the two new tests inherited a known-broken-without-DB pattern instead of following `tests/test_profiles.py`'s approach in the same phase (mock `get_admin_client` so the test is genuinely DB-independent, matching the file's own docstring claim: "Tests endpoint existence and basic response codes WITHOUT a live Supabase connection").

**Fix:** Either mock `app.public.encryption.get_admin_client` in these two tests (as `tests/test_profiles.py` and the new `TestResolveCustomDomain` test in `tests/test_custom_domains.py` do), or explicitly gate the test file's non-DB claim and require `docker compose up -d` like `tests/test_rate_limit_boundaries.py` does.

### WR-03: `_authorize_owner` is duplicated verbatim across two modules, and is now live code in both

**File:** `app/public/shares.py:129-135`, `app/public/encryption.py:100-106`

**Issue:** Both files define an identical `_authorize_owner(row, user, delete_token)` helper. Before this phase, `encryption.py`'s copy was dead code (never called) — the SEC-01 fix makes it live by wiring it into `encrypt_share`. Two independent copies of an authorization-critical helper is a latent risk: a future edit to one (e.g. tightening the owner check) can silently miss the other.

**Fix:** Move `_authorize_owner` into a shared module (e.g. `app/public/_share_auth.py` or alongside `core/security.py`) and import it from both `shares.py` and `encryption.py`.

## Info

### IN-01: `ReencryptShareRequest.delete_token` is accepted but never used

**File:** `app/public/encryption.py:53` (field), `app/public/encryption.py:263-354` (`reencrypt_share` body)

**Issue:** `ReencryptShareRequest` declares a `delete_token: str | None = None` field, but `reencrypt_share` never reads `body.delete_token` — only `old_password`/`new_password` gate the operation (correctly, since decrypting with the old password is itself proof of authority in this zero-knowledge design). The unused field misleadingly suggests `delete_token` is an alternative auth path for this endpoint the way it is for `encrypt_share`/`delete_share`/`set_password`/`burn_share`.

**Fix:** Drop the field from `ReencryptShareRequest`, or document in the docstring why it's accepted-but-ignored if kept for client-payload-shape symmetry with `EncryptShareRequest`.

### IN-02: Redundant `get_client_ip` recomputation in `download_share`

**File:** `app/public/shares.py:489-513`

**Issue:** `ip = get_client_ip(request)` is computed once at the top of `download_share` for the new `check_public_read_rate_limit` call, then recomputed identically a few lines later inside the wrong-password branch before calling `check_password_rate_limit`. Harmless (same value both times) but unnecessary duplication introduced adjacent to this phase's new rate-limit block.

**Fix:** Reuse the `ip` already bound at the top of the function; drop the second `ip = get_client_ip(request)` reassignment at line ~512.

---

_Reviewed: 2026-08-15T15:41:09Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
