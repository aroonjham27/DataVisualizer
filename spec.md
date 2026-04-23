# Semantic Query Planner Spec

## Task Summary

Build the semantic query planner layer for `DataVisualizer`. The planner must convert a user question into a structured analysis plan grounded in the existing semantic model, and it must support drill continuation using current analysis state.

## Goals

- Define typed models for an `AnalysisPlan`.
- Load and use the existing semantic model as the governing contract.
- Resolve a user question into:
  - primary entity
  - measure
  - dimensions
  - time dimension
  - time grain
  - filters
  - join path
  - drill hierarchy
  - chart intent
  - warnings
- Support conversational drill continuation such as "go one level deeper".
- Add a minimal backend API surface for planning.
- Add the lightest justified test harness for this milestone.

## Non-Goals

- SQL generation or execution
- Frontend visualization UI
- Broad agent orchestration
- Warehouse or semantic-model redesign
- Introducing external frameworks or dependencies unless they are clearly required

## Repo Facts Observed

- The repo contains reviewed seed data in `data/`.
- The repo contains a bootstrap semantic model at `configs/semantic_models/pilot_pricing_v0.json`.
- The repo does not currently contain committed Python runtime code, a package manager config, or a test harness.
- Repository docs currently describe the repo as lacking runtime/build/test tooling.

## Design Choices For This Milestone

- Use Python standard library only unless a clear blocker appears.
- Create a small `src/` package for planner code.
- Use `unittest` for tests to avoid adding dependency management prematurely.
- Expose a minimal HTTP JSON API with stdlib server support rather than introducing a web framework.
- Keep planner behavior deterministic and rule-based against the semantic metadata rather than generative.

## Semantic Planning Scope

The planner should support the pilot semantic model well enough to plan questions around:

- win/loss and opportunity performance
- product and quote composition
- competitor analysis
- contract structure
- usage trends

It should use warnings instead of silently guessing when:

- multiple measures look plausible
- a question references an ambiguous metric
- a drill continuation has no valid next level
- the semantic model does not clearly support the requested concept

## Proposed Deliverables

- planner package under `src/`
- typed planner contracts
- semantic model loader utilities
- planner logic
- minimal backend planning API
- tests and golden question fixtures
- repo doc updates for running and testing, if new runtime/test workflows are introduced

## Risks And Edge Cases

- The semantic model contains multiple fact tables, so question routing may be ambiguous.
- Conversational follow-up like "go deeper" depends on previously chosen drill hierarchy and current drill level.
- Some concepts in the dataset are sparse or context-sensitive, especially quote values, usage metrics, and competitive price positioning.
- The pilot seed only contains closed opportunities, so plan behavior should not imply open-pipeline support.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Typed planner models exist and serialize cleanly | Unit tests for model creation and API payloads |
| Planner resolves pilot golden questions into expected analysis-plan structure | Golden question tests with expected entity, measure, dimensions, and joins |
| Drill continuation works from prior analysis state | Unit tests covering "go one level deeper" and invalid drill cases |
| Planner behavior stays semantic-model-first | Tests and code review confirming planner reads metadata rather than hard-coded raw table assumptions |
| Minimal API surface works | API tests against the request handler or application entry point |
| Documentation reflects any newly added runtime/test workflow | Review updated repo docs |
