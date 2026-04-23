# Phase 2 Chat Orchestration Spec

## Task Summary

Complete Phase 2 of the roadmap by adding the first live LLM orchestration layer on top of the existing governed analytics tools.

## Goals

- Add a mockable LLM client interface.
- Add a real env-configured, provider-agnostic HTTP adapter that works with the current OpenRouter setup.
- Add a fake LLM client for deterministic tests.
- Register the governed analytics tools with explicit schemas:
  - default compiled-plan `/answer`
  - governed restricted-SQL capability
- Add a chat orchestrator service that:
  - accepts chat messages
  - maintains conversation state
  - decides which governed tool to call
  - executes tool calls deterministically
  - returns a structured assistant response payload
- Add a chat API endpoint without replacing existing governed tool endpoints.
- Add env-gated live-model smoke coverage for:
  - a normal analytics question
  - a drill follow-up
  - a case where restricted SQL is allowed but compiled-plan should still win

## Non-Goals

- No frontend chat UI.
- No provider lock-in.
- No secret values in the repo.
- No broad semantic-model redesign.
- No widening of the restricted SQL subset beyond the existing governed validation.

## Repo Facts Observed

- The repo already has explicit tool contracts, stable envelopes, routing controls, and a separate restricted-SQL capability.
- Environment variables currently available include:
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_BASE_URL`
  - `OPENROUTER_MODEL`
  - `ANTHROPIC_MODEL`
  - `MAX_ITERATIONS`
  - `TIMEOUT_SECONDS`
- Existing backend contracts are already machine-friendly enough to be exposed directly as tools.

## Design Choices For This Pass

- Keep orchestration separate from the governed analytics backend.
- Use an OpenAI-style tool-calling envelope at the provider boundary, while keeping the transport adapter generic.
- Register restricted SQL only when the routing policy allows it.
- Keep compiled-plan as the default tool lane even when restricted SQL is available.
- Use deterministic follow-up handling helpers around existing analysis state for:
  - `go deeper`
  - `just enterprise`
  - `top 5`
  - `show as table`
- Keep most orchestration tests on the fake client; gate live smoke tests behind environment checks.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Provider adapter reads env config safely | Unit tests for env parsing and graceful missing-credential behavior |
| Tool schemas are explicit and stable | Unit tests on tool registration payloads |
| Compiled-plan remains default | Unit tests and fake-client orchestration tests |
| Restricted SQL stays secondary | Unit tests where restricted SQL is allowed but not chosen for normal analytics |
| Conversation state supports follow-ups | Orchestrator tests for `go deeper`, `just enterprise`, `top 5`, and `show as table` |
| Chat endpoint works end-to-end | HTTP tests for `/chat` |
| Live model path exists but is optional | Env-gated smoke tests using the real adapter |
