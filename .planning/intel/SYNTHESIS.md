# Synthesis Summary

Single entry point for downstream consumers (`gsd-roadmapper`). Read this first, then drill into the per-type files as needed.

## Doc counts by type

| Type | Count | Docs |
|---|---|---|
| ADR | 0 | — |
| SPEC | 2 | `docs/API.md`, `docs/2026-08-12-firebase-auth-backend-api-design.md` |
| PRD | 1 | `docs/project-overview-pdr.md` |
| DOC | 14 | `docs/ARCHITECTURE.md`, `docs/system-architecture.md`, `docs/codebase-summary.md`, `docs/CONFIGURATION.md`, `docs/DEPLOYMENT.md`, `docs/deployment-guide.md`, `docs/design-guidelines.md`, `docs/code-standards.md`, `docs/DEVELOPMENT.md`, `docs/GETTING-STARTED.md`, `docs/project-roadmap.md`, `docs/TESTING.md`, `docs/2026-08-12-firebase-google-login-implementation.md`, `docs/plans/2026-05-30-competitor-features.md` |

Total: 17 documents classified and consumed. No `UNKNOWN`-typed or low-confidence documents in this batch.

## Decisions locked

0. No ADR-classified documents in this ingest batch, so `decisions.md` has no LOCKED (or proposed) entries. Note: the Firebase-auth SPEC contains a design-decisions list, but per extraction discipline it is filed under `constraints.md` (SPEC-typed), not `decisions.md` — see that file's header note and `decisions.md` for the routing rationale.

## Requirements extracted

21 requirement entries, all sourced from `docs/project-overview-pdr.md` (the sole PRD): `REQ-product-scope`, `REQ-content-sharing-management`, `REQ-security-privacy`, `REQ-team-collaboration`, `REQ-discovery-analytics`, `REQ-file-management`, `REQ-programmatic-api`, `REQ-user-stories-individual-users`, `REQ-user-stories-team-members`, `REQ-user-stories-team-owners`, `REQ-user-stories-api-consumers`, `REQ-nfr-security`, `REQ-nfr-reliability`, `REQ-nfr-scalability`, `REQ-nfr-privacy`, `REQ-deployment-target`, `REQ-out-of-scope`, `REQ-technical-rationale`, `REQ-constraints-tradeoffs`, `REQ-success-metrics`, `REQ-acceptance-v030`. No competing PRD variants (only one PRD in the batch).

## Constraints

18 constraint entries across the 2 SPECs. `docs/API.md` (11 entries, all `api-contract`/`nfr`, covering router mounts, auth mechanisms, error envelope, rate limits, health, and all four route-group families). `docs/2026-08-12-firebase-auth-backend-api-design.md` (9 entries: 1 context/nfr, 1 schema decisions-list, 1 schema/migration, 1 api-contract session endpoint, 1 api-contract dependency refactor, 1 api-contract error matrix, 1 protocol testing plan, 1 nfr rollout, 1 nfr defaults/out-of-scope). Type breakdown: api-contract 12, schema 2, nfr 3, protocol 1.

## Context topics

14 topic entries in `context.md`, one per DOC-classified source (architecture, system architecture, codebase structure, configuration, deployment ×2, design guidelines, code standards, development workflow, getting started, project roadmap, testing, Firebase Google sign-in frontend plan, competitor feature gap plan — historical).

## Conflicts

**0 blockers, 3 warnings (competing-variants), 1 auto-resolved (info).**

- WARNING: Supabase-JWT-era docs vs. in-progress Firebase Auth SPEC (auth model) — explicitly kept as WARNING rather than auto-resolved-by-precedence, per ingest-workflow guidance, since the migration is legitimately in-progress.
- WARNING: Storage bucket count discrepancy (2 vs 3 buckets, thumbnails bucket disputed) across `DEPLOYMENT.md`/`CONFIGURATION.md` vs `deployment-guide.md`/`system-architecture.md`/`codebase-summary.md`.
- WARNING: Testing-strategy discrepancy (fully-mocked per `TESTING.md` vs Supabase-tolerant per `DEVELOPMENT.md`).
- INFO: `DEPLOYMENT.md` self-declares canonical over `deployment-guide.md` for blueprint-driven deploys (auto-resolved by the source's own text, not by this synthesizer's inference).

Full detail: `.planning/INGEST-CONFLICTS.md`

## Per-type intel files

- `.planning/intel/decisions.md`
- `.planning/intel/requirements.md`
- `.planning/intel/constraints.md`
- `.planning/intel/context.md`
