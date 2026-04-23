# Phase 3 Chat UI Spec

## Task Summary

Complete Phase 3 of the roadmap by adding the first user-facing chat interface on top of the governed `/chat` backend contract.

## Goals

- Build a minimal single-page UI with:
  - chat thread
  - input box
  - send action
  - loading and error states
- Render assistant responses directly from the existing `/chat` contract.
- Render answer content with:
  - assistant message text
  - chart from the backend `chart_spec`
  - tabular result view
  - warnings and ambiguity notices
  - lightweight metadata when helpful
- Support drill interactions from the rendered chart.
- Keep `/chat` as the only user-facing UI API path.
- Keep the implementation minimal, inspectable, and aligned to the current backend contracts.

## Non-Goals

- No auth or user accounts.
- No broad design-system work.
- No mobile-first polish pass.
- No deployment setup.
- No widening of the restricted SQL surface.
- No replacement of `/answer` or `/restricted-sql`.

## Repo Facts Observed

- The repo already has a Python HTTP server under `datavisualizer.api`.
- There is no committed frontend framework, package manager, or asset build pipeline.
- `/chat` already returns a stable structured response with:
  - assistant message text
  - executed tool name
  - tool result
  - conversation state
  - tool trace
- The answer tool already emits renderer-agnostic chart specs for:
  - `line`
  - `bar`
  - `grouped_bar`
  - `table`

## Design Choices For This Pass

- Use plain HTML, CSS, and browser JavaScript instead of adding a framework or build step.
- Serve the SPA from the existing Python HTTP server to keep the vertical slice simple.
- Treat `/chat` as the UI contract and preserve `/answer` and `/restricted-sql` as governed backend tools underneath it.
- Render charts with inline SVG so no frontend dependency is required.
- Always show the result table, even when a chart renders, so the governed data is directly inspectable.
- Use chart point interaction to send `selected_member` drill payloads back through `/chat`.
- Add lightweight Python tests for static asset serving plus shared contract-level chart/drill helpers where that improves confidence.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Root UI shell is served by the current server | HTTP tests for `GET /` |
| Static assets are served without a build pipeline | HTTP tests for `GET /static/...` |
| Core chat states render from the contract | UI shell and integration tests around `/chat` responses |
| Chart contract can be rendered deterministically | Contract helper tests for chart view-model creation |
| Selected-member drill payload generation is stable | Contract helper tests for drill selection derivation |
| UI stays aligned to `/chat` | Integration tests keep `/chat` as the top-level user path |
