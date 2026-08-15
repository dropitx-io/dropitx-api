---
phase: 2
slug: firebase-auth-migration-completion
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-15
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥ 8.0 + pytest-asyncio ≥ 0.24 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`testpaths = ["tests"]`, no `conftest.py`) |
| **Quick run command** | `pytest tests/test_auth_session.py tests/test_dependencies.py -v` (mocked, no docker, ~3s) |
| **Full suite command** | `docker compose up -d && pytest` (251 tests; 5 pre-existing unrelated failures per STATE.md) |
| **Estimated runtime** | ~3s quick / ~60-90s full |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_auth_session.py tests/test_dependencies.py -v`
- **After every plan wave:** `docker compose up -d && pytest` (full suite — must show exactly the 5 pre-existing documented failures, no more, no fewer)
- **Before `/gsd-verify-work`:** Full suite green (modulo the 5 documented failures), **plus** a manual/scripted live-HTTP run of the AUTH-02/AUTH-03 flow against real Postgres — no existing test covers the full round-trip yet
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | AUTH-02 | Identity confusion (Spoofing/EoP) | `provision_firebase_user` RPC executes without ambiguous-column error against real Postgres; idempotent upsert confirmed live | integration (live DB) | `pytest tests/test_auth_session_live.py -x` | ❌ W0 — new file, blocking fix | ⬜ pending |
| 02-01-02 | 01 | 1 | AUTH-02, AUTH-03 | Identity confusion | Full `401 user_not_provisioned → GET /api/auth/session → 200 → protected route 200` flow verified live | integration (live DB) | `pytest tests/test_auth_session_live.py -x` | ❌ W0 — same new file as above | ⬜ pending |
| 02-02-01 | 02 | 1 | AUTH-01 | — | Protected route resolves user via TEXT `auth.users` (regression check, already passing mocked) | unit (mocked) | `pytest tests/test_dependencies.py::test_current_user_provisioned -x` | ✅ exists | ⬜ pending |
| 02-02-02 | 02 | 1 | AUTH-04 | — | `FIREBASE_PROJECT_ID` present in both env example files | manual/grep | `grep -l FIREBASE_PROJECT_ID .env.example .env.local.example` | ❌ W0 — file edit, not app behavior | ⬜ pending |
| 02-02-03 | 02 | 1 | AUTH-05 | — | Zero remaining `verify_supabase_jwt`/"Supabase JWKS" references in docs/README/CLAUDE.md | manual/grep | `grep -rn "verify_supabase_jwt\|Supabase JWKS" docs/ README.md CLAUDE.md` (must return empty) | ❌ W0 — doc content, not app behavior | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Fix `provision_firebase_user` in `infra/init/02_rpc_functions.sql` + a new migration (`009_fix_provision_firebase_user.sql`) — **blocking**, not just a test gap; AUTH-02 cannot pass without it regardless of test coverage
- [ ] New `tests/test_auth_session_live.py` — live-Postgres integration test exercising the full `401 → session → 200 → protected route 200` flow, per RESEARCH.md's Code Examples section
- [ ] `.env.example` + `.env.local.example` — add `FIREBASE_PROJECT_ID` placeholder

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Documentation accurately describes Firebase (not Supabase JWT/JWKS) as the live auth mechanism | AUTH-05 | Doc content correctness isn't a runtime behavior — no automated assertion beyond absence-of-stale-terms grep | Run `grep -rn "verify_supabase_jwt\|Supabase JWKS" docs/ README.md CLAUDE.md` after the doc pass; expect zero matches |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
