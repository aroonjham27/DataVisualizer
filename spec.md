# Phase 1 Tool Boundary Spec

## Task Summary

Complete Phase 1 of the roadmap by making the backend clean, explicit, and stable for future LLM tool-calling without integrating a live model yet.

## Goals

- Treat `/answer` as the default governed analytics tool.
- Treat restricted SQL as a separate governed capability, not the default analytics path.
- Add explicit routing controls:
  - `compiled_plan_only`
  - `restricted_sql_allowed`
- Add a first-class machine-friendly error contract across service and HTTP surfaces.
- Normalize answer payloads for future model consumption while preserving the current deterministic backend behavior.
- Update roadmap tracking and only mark Phase 1 items complete if this pass truly covers them.

## Non-Goals

- No live LLM integration.
- No OpenRouter or provider wiring.
- No frontend UI rendering.
- No semantic-model redesign.
- No widening of the restricted SQL subset beyond what is already validated.

## Repo Facts Observed

- The repo already has a deterministic planner, SQL compiler, execution harness, answer pipeline, restricted SQL gateway, and stdlib HTTP surface.
- `/answer` currently always uses the compiled-plan lane.
- The repo already has row-aware chart fallback and restricted SQL hardening.
- `DataVisualizer_ROADMAP.md` exists in the repo root and Phase 1 is still unchecked.

## Design Choices For This Pass

- Keep the tool contract additive and explicit rather than replacing the current answer payload wholesale.
- Introduce stable request contracts for routing controls instead of implicit behavior.
- Introduce stable success/error envelopes so a future orchestrator can parse results deterministically.
- Keep compiled-plan execution the default and preferred answer route.
- Keep restricted SQL separate and explicit so future model tooling must opt into it.

## Planned Contract Changes

- `AnswerRequest` gains a routing block with explicit controls.
- Answer responses expose:
  - tool identity
  - routing policy
  - query mode
  - stable query metadata
  - structured warnings
- Backend errors expose:
  - `error_type`
  - `error_code`
  - `message`
  - optional structured details

## Verification Plan

| Requirement | Proof Method |
|---|---|
| `/answer` remains compiled-plan default | Unit and HTTP tests assert routing defaults and `query_mode` |
| Routing flags are explicit and stable | Unit tests for request parsing and route behavior |
| Error payloads are machine-friendly | Unit and HTTP tests assert stable error envelopes |
| Answer payload is normalized for model use | Unit and HTTP tests assert stable top-level fields, routing metadata, warnings, and chart spec |
| Restricted SQL remains separate and governed | Service tests use the explicit restricted SQL lane and assert compiled-plan is still default |
| Phase 1 roadmap tracking is accurate | `DataVisualizer_ROADMAP.md` updated only for truly completed items |
