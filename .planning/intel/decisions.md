# Decisions

No ADR-classified documents were present in this ingest batch (0 of 17 classified docs = ADR). Consequently there are no LOCKED or proposed architectural decisions to record here.

Note: `docs/2026-08-12-firebase-auth-backend-api-design.md` contains a section literally titled "## Decisions (locked during brainstorming)" and is marked `Status: Design (awaiting spec sign-off)` — but it was classified `SPEC` (not `ADR`) by the upstream classifier because its dominant content is an API contract / schema-migration spec, not a Context/Decision/Consequences ADR, and its status is not `Accepted`. Per extraction discipline, this synthesizer respects the classifier's `type` field rather than re-deriving it — that content is extracted into `constraints.md` under "Firebase Auth Backend — Design Decisions (non-ADR, unlocked)" instead of here. If the team wants these treated as a locked ADR, re-tag the doc as `ADR` with `locked: true` via `--manifest` and re-run ingest.
