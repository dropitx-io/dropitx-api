---
phase: 1
slug: security-hardening
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-15
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥ 8.0 + pytest-asyncio ≥ 0.24 (`[tool.pytest.ini_options]` in `pyproject.toml`, `asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`testpaths = ["tests"]`) |
| **Quick run command** | `pytest tests/test_all_endpoints.py -v` (ASGI transport, no live DB needed) |
| **Full suite command** | `pytest` (some files need `docker compose up -d` first per `CLAUDE.md`) |
| **Estimated runtime** | ~10s quick / ~60-90s full |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_all_endpoints.py -v`
- **After every plan wave:** Run `pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | SEC-01 | BOLA (Tampering/EoP) | `POST /shares/{slug}/encrypt` requires owner JWT or valid `delete_token`; non-owner gets 401/403 | integration (ASGI, no DB) | `pytest tests/test_all_endpoints.py -k encrypt_share_no_auth -x` | ❌ W0 — mirror `test_set_password_no_auth` (line 239-243) | ⬜ pending |
| 01-01-02 | 01 | 1 | SEC-02 | Credential brute-force | `POST /shares/{slug}/reencrypt` rate-limited fail-closed, 429 after threshold | integration (ASGI, DB-tolerant) | `pytest tests/test_one_time_download.py -k reencrypt -x` | ❌ W0 — mirror tolerant `(404, 500, 429)` pattern, `tests/test_one_time_download.py:136-137` | ⬜ pending |
| 01-01-03 | 01 | 1 | SEC-03 | Unbounded resource consumption (DoS) | `GET /api/download/group/{slug}` per-IP rate-limited before ZIP build | integration (ASGI, DB-tolerant) | `pytest tests/test_all_endpoints.py -k download_group -x` | ⚠️ W0 partial — `test_download_group_not_found` exists (404-only); needs rate-limit companion | ⬜ pending |
| 01-01-04 | 01 | 1 | SEC-04 | Unbounded resource consumption (DoS) | `content`/`download`/`preview` reject bursts per IP (429) | integration (ASGI, DB-tolerant) | `pytest tests/test_all_endpoints.py -k "content or download or preview" -x` | ❌ W0 — new tests | ⬜ pending |
| 01-01-05 | 01 | 1 | SEC-05 | Internal-endpoint exposure (info disclosure) | `domains/resolve/{domain}` rejects excessive requests / no longer freely callable | integration (ASGI, DB-tolerant) | `pytest tests/test_custom_domains.py -k resolve -x` | ❌ W0 — new test | ⬜ pending |
| 01-01-06 | 01 | 1 | SEC-06 | Unhandled exception (self-DoS) | `GET /api/u/{username}` returns 200/404, never 500 | integration (ASGI, DB-tolerant) | `pytest tests/test_all_endpoints.py -k public_profile -x` | ❌ W0 — no existing test file touches `app/public/profiles.py` |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_all_endpoints.py` — add `test_encrypt_share_no_auth` (SEC-01), mirroring `test_set_password_no_auth` (line 239-243)
- [ ] `tests/test_all_endpoints.py` (or new `tests/test_profiles.py`) — add coverage for `GET /api/u/{username}` (SEC-06); no existing test file touches `app/public/profiles.py` at all — largest single test gap in the phase
- [ ] New or existing test module — rate-limit-tolerant tests for `reencrypt` (SEC-02), `download/group/{slug}` (SEC-03), `content`/`download`/`preview` (SEC-04), `domains/resolve` (SEC-05), following the existing `assert resp.status_code in (404, 500, 429)`-style tolerant pattern from `tests/test_one_time_download.py:136-137`
- [ ] No framework install needed — pytest/pytest-asyncio already configured

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
