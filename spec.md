# Phase 4 Explainability And Inspection Spec

## Task Summary

Complete Phase 4 of the roadmap by adding a compact, per-response inspection surface to the existing chat UI.

## Goals

- Add a collapsible "What did the system do?" inspector to each governed assistant response.
- Keep `/chat` as the only user-facing UI API path.
- Preserve `/answer` and `/restricted-sql` as governed backend tools underneath chat.
- Show the analysis plan used when an answer result includes one.
- Show query mode, routing policy, executed SQL, applied filters, involved entities, row limit, truncation status, and chart selection.
- Explain table fallbacks when chart generation falls back because of empty, sparse, over-wide, too-many-category, or unsupported visual shapes.
- Make warnings easier to scan by grouping plan warnings, chart warnings, routing notes, fallback explanations, and query/execution notes.
- Keep the implementation minimal and inspectable with plain HTML, CSS, browser JavaScript, and small Python contract helpers.

## Non-Goals

- No auth or user accounts.
- No new frontend framework or build pipeline.
- No deployment setup.
- No broad semantic-model redesign.
- No widening of the restricted SQL surface.
- No unrestricted query or raw client-side query path.
- No separate Phase 4 inspector endpoint.

## Repo Facts Observed

- `/chat` already returns assistant text, executed tool name, tool result, conversation state, and trace.
- Tool results already include stable envelopes and backend-controlled data.
- The answer payload already includes `plan`, `routing`, `query_mode`, `query_metadata`, `sql`, `limit`, `warnings`, and `chart_spec`.
- The restricted SQL payload already includes `query_mode`, `query_metadata`, `sql`, `limit`, `warnings`, columns, and rows.
- Chart fallback reasons already flow through `chart_spec.warnings` and answer `warnings` with source `chart`.
- The UI already renders assistant text, warnings, chart, table, metadata, and active filters from `/chat`.

## Design Choices For This Pass

- Derive the inspector from the existing tool result payload rather than adding a parallel backend contract.
- Add `build_inspector_view_model` to `datavisualizer.ui_contract` so the inspection shape is testable in Python.
- Mirror that shaping in the browser UI for direct `/chat` rendering.
- Use native `<details>` for the collapsible inspector.
- Keep SQL visible but collapsed by default.
- Show business-readable text first, while preserving machine-readable fields such as warning `code`, warning `source`, query mode, and entity names.
- Treat chart fallback explanations as chart warnings plus table chart type, not as a separate invented status.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Inspector derives from existing answer payload | UI contract tests around `build_inspector_view_model` |
| Inspector shows filters and SQL | Contract tests and static asset assertions |
| Warning categories are separated | Contract tests for warning groups |
| Chart fallback explanations are visible | Contract tests using table fallback warnings and UI asset assertions |
| `/chat` remains the top-level UI path | Existing HTTP UI/chat integration tests |
| Existing governed backend paths remain stable | Full `unittest` discovery |
