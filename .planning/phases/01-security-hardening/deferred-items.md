# Deferred Items — Phase 01 Plan 01

Out-of-scope discoveries logged per executor scope-boundary rule (not fixed here).

## test_health_deep returns 404 instead of 200

- **File:** tests/test_all_endpoints.py::TestHealth::test_health_deep
- **Observed:** `GET /health/deep` returns 404, not 200 (docstring says "may fail... that's OK" but 404 suggests route mismatch/removal, not a DB-down 200-with-degraded-status response).
- **Scope:** Unrelated to SEC-01/SEC-02/SEC-06 — no file this plan touches (app/public/encryption.py, app/public/profiles.py) affects this route.
- **Status:** Not fixed. Pre-existing before this plan's changes (confirmed no health-related files modified).

## tests/test_public_api_validation.py — 4 pre-existing failures (full suite, live DB)

- **Tests:** `TestShareComments::test_422_without_fields`, `test_422_missing_author_name`, `test_422_empty_fields`, `TestSetPassword::test_401_without_auth_and_no_delete_token`
- **Observed:** Comments validation only reports `content` field errors, not `author_name`; `set_password` returns 404 instead of 401 for a nonexistent slug + no auth (because `set_password` fetches the share row before the auth guard, so a live-but-empty DB 404s first).
- **Scope:** Both concern `app/public/shares.py` (comments handler, `set_password`) — a file this plan never modifies. `tests/test_public_api_validation.py` is byte-identical to its pre-plan state (verified via `git show` against the phase-start commit).
- **Status:** Not fixed. Out of scope for SEC-01/SEC-02/SEC-06.
