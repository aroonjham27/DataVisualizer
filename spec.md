# Semantic Planner Hardening Spec

## Task Summary

Harden the current semantic planner before adding a deterministic plan-to-SQL compiler. This pass should improve planner contracts, drill context, routing safety, and test coverage without generating SQL.

## Goals

- Keep documentation accurate for the current repo state.
- Extend analysis state so drill continuation can carry a selected visual member.
- Add tests for join paths, warning/status behavior, fallback planning, and `AnalysisPlan` serialization round trips.
- Tighten brittle routing, especially avoiding broad routing of every `trend` question to usage planning.
- Keep the planner deterministic, semantic-model-first, and small.

## Non-Goals

- SQL generation or execution
- Frontend visualization UI
- New external frameworks
- Broad natural-language platform scaffolding

## Repo Facts Observed

- `origin/main` and local `main` are in sync.
- The repo contains seed data under `data/`.
- The repo contains the reviewed pilot semantic model at `configs/semantic_models/pilot_pricing_v0.json`.
- The repo contains a minimal Python runtime under `datavisualizer/`.
- The repo contains a standard-library `unittest` suite under `tests/`.
- No package manager, external dependency stack, SQL compiler, or frontend exists yet.

## Design Choices For This Pass

- Continue using Python standard library only.
- Add selected-member drill context to the typed contracts rather than introducing session storage.
- Let drill continuation apply selected-member scope as a semantic filter when provided.
- Tighten routing with a small explicit route table instead of broad keyword checks.
- Preserve fallback behavior as `review_needed` so unsupported questions are safe for review before SQL compilation.

## Risks And Edge Cases

- A visual member selection may reference a field that is already present as a dimension; this should scope the next drill rather than duplicate a dimension.
- Broad words like `trend` can appear in unrelated questions and should not force usage planning.
- Fallback planning is useful for exploration but should not be treated as high-confidence.
- Join path correctness matters now because the next milestone will compile these paths into SQL.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Docs reflect current repo state | Review `spec.md`, `README.md`, and `TESTING.md` as needed |
| Selected visual member can scope drill continuation | Unit test with selected field/value carried into drill state and filters |
| Join paths are stable and semantic-model based | Unit tests asserting expected join edges for cross-entity plans |
| Warning/status behavior is explicit | Unit tests for `review_needed` and `ok` plan cases |
| Fallback behavior is safe | Unit test for unsupported question routing to fallback plan with warning |
| Plan serialization is stable | Unit test for `AnalysisPlan.to_dict()` / `from_dict()` round trip |
| Broad trend routing is tightened | Unit test proving unrelated trend questions do not auto-route to usage |
