# Phase 2 Deferred Items

Out-of-scope discoveries logged during plan execution (per executor scope-boundary rule). Not fixed here.

| # | Found during | Item | Why deferred |
|---|--------------|------|--------------|
| 1 | 02-04 Task 2 | `docs/API.md` line 28 cites `get_api_key` at `app/dependencies.py:70`; the function is actually at line 96 (confirmed via grep). | API-key auth line-number staleness, not an auth-mechanism (Supabase/Firebase JWT) claim — outside 02-04's named scope. The plan corrected only the adjacent `get_current_user`/`get_optional_user` refs (`:56`/`:84`). Safe to fix in any later docs pass. |
