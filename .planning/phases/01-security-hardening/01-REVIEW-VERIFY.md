---
phase: 01-security-hardening
reviewed: 2026-08-15T23:15:00Z
depth: deep
verification_of: .planning/phases/01-security-hardening/01-REVIEW-FIX.md
source_review: .planning/phases/01-security-hardening/01-REVIEW.md
files_reviewed: 5
files_reviewed_list:
  - app/dependencies.py
  - app/public/_share_auth.py
  - app/public/encryption.py
  - app/public/shares.py
  - tests/test_all_endpoints.py
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: issues_found
---

# Phase 01-security-hardening: Code Review Fix Verification Report

**Reviewed:** 2026-08-15T23:15:00Z
**Depth:** deep
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Independently re-verified all 4 fixes claimed in `01-REVIEW-FIX.md` against the current source
(diff base `eff0ab0`), by reading the modified files directly, grepping for leftover duplicate
code, tracing imports for cycles, and actually executing the affected tests — not just trusting
the fixer's narrative.

**WR-01, WR-02, and WR-03 are verified clean** — each closes the finding it claims to, with no new
issues. **CR-01's code change is correct** for the vulnerability as originally scoped (arbitrary
client-header spoofing), and I ran the two target tests plus the full suite to confirm WR-02's
claims empirically rather than taking them on faith. However, cross-referencing the fix against
`k8s/api.yaml` (present in the working tree) surfaces a residual gap in CR-01's real-world
efficacy that the fix report doesn't mention: **see WR-04 below.**

## Verification Detail

### CR-01: `get_client_ip()` trusts only `CF-Connecting-IP` — CODE FIX VERIFIED, RESIDUAL GAP FOUND

**File:** `app/dependencies.py:175-186`

The current implementation matches the fix report's description exactly (confirmed against commit
`2f9319a`'s diff):

```python
def get_client_ip(request: Request) -> str:
    """Extract client IP, trusting only CF-Connecting-IP (set by Cloudflare's edge)."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"
```

This correctly closes the literal CR-01 vulnerability: the original bug — trusting
`X-Forwarded-For`/`X-Real-IP` unconditionally, letting an attacker rotate rate-limit buckets by
varying either header — is gone. Neither header is read anywhere in the function now. `app/main.py`
still registers only `CORSMiddleware` (confirmed via grep), so this function is the sole point of
control, and all 5 rate limiters consume it transitively as claimed — no call sites needed changes.

**Residual gap (not called out in the fix report):** the security value of trusting
`CF-Connecting-IP` rests entirely on the assumption that the app is *only* reachable through
Cloudflare's tunnel — i.e., that no other network path lets a client set that header directly.
That assumption is not enforced anywhere in this codebase (no `TrustedHostMiddleware`, no allowlist
of trusted proxy IPs, no shared-secret validation between `cloudflared` and the app), and it is
directly contradicted by `k8s/api.yaml` (present in the working tree, part of the "newer,
actively-developed deployment path" per this repo's `CLAUDE.md`):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: dropitx-api
  namespace: dropitx
spec:
  type: NodePort
  ports:
    - {port: 8000, targetPort: 8000, nodePort: 30080}
```

A `NodePort` Service exposes the API directly on every cluster node's IP at port 30080 — a network
path with no relationship to the Cloudflare Tunnel. If that port is reachable from outside the
cluster (which depends entirely on cloud-provider/firewall configuration not visible in this repo),
an attacker hitting the API through it can set `CF-Connecting-IP` to any value they like, since the
header is trusted by name only, not verified cryptographically or restricted by source IP. In that
scenario `CF-Connecting-IP` is exactly as spoofable as `X-Forwarded-For` was before the fix — the
mitigation would provide zero actual protection despite the code being "correct."

This is not a new bug introduced by the fix's code (the fix is the right in-app defense *given* the
stated precondition), and it may already be an accepted risk if the NodePort is firewalled off at
the infrastructure layer — that's outside this repo's visibility, so I'm not asserting it's actively
exploited. But it is a gap the fix report should have flagged rather than treating "behind Cloudflare
Tunnel" as a given: the codebase itself provisions a second, un-tunneled ingress path. See WR-04 for
the concrete recommendation.

**Verdict:** Code change verified correct for the scoped vulnerability. Flagging the network
assumption as WR-04 since it materially affects whether the fix delivers real protection.

### WR-01: `encryption-info` and `download-status` now rate-limited, correctly ordered — VERIFIED CLEAN

**Files:** `app/public/encryption.py:129-149` (`get_encryption_info`), `app/public/shares.py:561-597`
(`get_download_status`)

Both routes now take a `Request` parameter and call `check_public_read_rate_limit(get_client_ip(request))`,
raising `HTTPException(429, ...)` with a `Retry-After` header before any DB access:

- `get_encryption_info`: rate check runs, then `await _fetch_share_for_encrypt(slug)` — DB fetch is
  strictly after the 429 short-circuit.
- `get_download_status`: rate check runs, then `client.table("shares").select(...).execute()` — same
  ordering.

Matches the pattern already used by `get_share_content`/`download_share`/`get_share_preview`. Both
gaps from the original WR-01 finding are closed.

**Verdict:** Verified correct.

### WR-02: SEC-01 regression tests now mock `get_admin_client` — VERIFIED CLEAN (ran the tests, not just read the diff)

**File:** `tests/test_all_endpoints.py:262-290`

Both `test_encrypt_share_no_auth` and `test_encrypt_share_empty_delete_token` now carry
`@patch("app.public.encryption.get_admin_client")` and mock the
`.table("shares").select("*").eq("slug", ...).execute()` chain to return `MagicMock(data=[])`, which
makes `_fetch_share_for_encrypt` raise a clean `HTTPException(404)` instead of letting a real
`asyncpg` connection attempt propagate as `OSError`.

I ran this independently rather than trusting the fix report's narrative:

```
$ uv run pytest tests/test_all_endpoints.py -k "test_encrypt_share_no_auth or test_encrypt_share_empty_delete_token" -v
tests/test_all_endpoints.py::TestOptionalAuthEndpoints::test_encrypt_share_no_auth PASSED
tests/test_all_endpoints.py::TestOptionalAuthEndpoints::test_encrypt_share_empty_delete_token PASSED
2 passed, 60 deselected in 0.76s
```

Full-file run (no `docker compose up -d`) shows exactly the 9 pre-existing DB-dependent failures the
fix report claims, none touching the two target tests or anything related to this phase:
`test_health_deep`, `test_share_content_not_found`, `test_share_download_not_found`,
`test_share_preview_not_found`, `test_share_files_not_found`, `test_delete_share_no_auth`,
`test_set_password_no_auth`, `test_burn_share_no_auth`, `test_download_group_not_found` — 9 failed,
53 passed. This matches the claimed baseline; no new failures, no masking (the mock exercises the
real 404 code path rather than skipping the assertion).

**Verdict:** Verified correct — claim reproduced empirically.

### WR-03: `authorize_owner` extracted to `app/public/_share_auth.py` — VERIFIED CLEAN (no circular import, both call sites updated)

**Files:** `app/public/_share_auth.py` (new), `app/public/shares.py`, `app/public/encryption.py`

Grep confirms exactly one definition left in the codebase (`app/public/_share_auth.py:10`,
`def authorize_owner(...)`) — no leftover duplicate in either `shares.py` or `encryption.py`. Both
files import it (`from app.public._share_auth import authorize_owner`) and call it:

- `shares.py` — 3 call sites: `delete_share` (line 309), `set_password` (line 331), `burn_share`
  (line 448).
- `encryption.py` — 1 call site: `encrypt_share` (line 184).

Matches the fix report's claimed call-site counts exactly.

**Circular import check:** `_share_auth.py` imports `User` from `app.dependencies`; `app.dependencies`
imports only from `core.security` and `core.supabase` — no import back to `app.public.*`, so no
cycle. Confirmed by actually importing the chain end-to-end (not just static analysis):

```
$ uv run python -c "import app.public._share_auth; import app.public.shares; import app.public.encryption; print('imports OK')"
imports OK - no circular import
```

**Verdict:** Verified correct.

## Warnings

### WR-04: CR-01's `CF-Connecting-IP` trust is conditional on a network assumption the repo's own k8s manifest contradicts

**File:** `app/dependencies.py:175-186` (root cause, unchanged from CR-01's fix); `k8s/api.yaml` (new
evidence not considered by the original review or the fix)

**Issue:** See the "Residual gap" discussion under CR-01 above. In short: `get_client_ip()` now
trusts `CF-Connecting-IP` on the stated assumption that the app is reachable *only* through the
Cloudflare Tunnel. `k8s/api.yaml` provisions a `type: NodePort` Service exposing the API directly on
port 30080 on every cluster node — a path with no dependency on the tunnel. Nothing in-app
(no `TrustedHostMiddleware`, no source-IP allowlist, no shared secret validated between `cloudflared`
and the origin) enforces that this NodePort is unreachable from the internet; that enforcement, if it
exists, lives entirely in infrastructure/firewall configuration outside this repo. If the NodePort is
in fact publicly reachable, `CF-Connecting-IP` becomes just as forgeable as the header it replaced,
and all 5 rate limiters this phase set out to fix are bypassable again via that path.

This is a plausible-but-unconfirmed risk (I cannot verify from this repo whether the NodePort is
firewalled at the cloud/network layer), not a demonstrated live exploit — flagging per the "document
non-issues briefly, ask when risk is plausible but depends on product intent" principle, since this
depends on infrastructure the codebase doesn't fully describe.

**Fix (pick one, in order of preference):**
1. Change the k8s Service to `type: ClusterIP` and route all external traffic exclusively through an
   in-cluster `cloudflared` (so no node port is ever exposed publicly), or firewall port 30080 at the
   cloud/node level so only Cloudflare's tunnel can reach it.
2. If a NodePort is required for other reasons, add app-level defense-in-depth: validate a shared
   secret header that only `cloudflared` sets (e.g. Cloudflare Access service tokens, or a custom
   header value injected by the tunnel config and checked in `get_client_ip`/a dependency), so
   `CF-Connecting-IP` is only trusted when that secret is also present.
3. At minimum, document in `k8s/api.yaml` or deployment docs that the NodePort must be
   firewalled to reject public traffic, so this isn't an implicit, unverified assumption.

---

_Reviewed: 2026-08-15T23:15:00Z_
_Reviewer: Claude (gsd-code-reviewer, re-verification pass)_
_Depth: deep_
