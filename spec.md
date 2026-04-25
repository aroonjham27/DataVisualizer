# Phase 4.6 Result-Aware Visualization Follow-Ups Spec

## Task Summary

Fix chat state handling so visualization-only follow-ups reuse the prior governed result instead of starting a new analytics query.

## Goals

- Preserve the last successful governed result in conversation state.
- Detect follow-ups such as "plot the above", "visualize it", "can you graph that?", "show this as a bar chart", "show this as a heatmap", "make it a grouped bar", "show as line chart", and "show as table".
- Treat visualization-only follow-ups as render requests when a prior governed result exists.
- Reuse prior columns, rows, SQL, query mode, warnings, limit metadata, query metadata, chart spec, and plan when available.
- Generate a new chart spec deterministically from the existing result.
- Do not re-query through `/answer` or restricted SQL unless the user asks a new analytics question.
- Keep assistant prose consistent with the governed payload.
- Include chart choice explanations in chart specs, reused-result prose, and the inspector.
- Show reused-result metadata in the inspector.

## Non-Goals

- No LangGraph migration.
- No raw SQL input or SQL editor.
- No restricted SQL validator expansion.
- No auth or permission model.
- No Phase 5 evaluation harness work.
- No broad UI redesign.

## Conversation State Additions

The state now preserves these fields from the last successful governed result:

- `last_tool_name`
- `last_query_mode`
- `last_sql`
- `last_columns`
- `last_rows`
- `last_chart_spec`
- `last_limit`
- `last_warnings`
- `last_query_metadata`
- `last_plan`, when available

Only already-returned governed result data is stored. Provider credentials and secrets are not part of the state contract.

## Visualization Follow-Up Policy

1. `/chat` reads the latest user message and merges request state.
2. If the message is visualization-only and prior result rows/columns exist, `/chat` short-circuits before model tool selection.
3. The orchestrator builds a `visualize_result` response from prior governed result data.
4. The response preserves original query mode and SQL and marks:
   - `source_result_tool`
   - `source_query_mode`
   - `visualization_follow_up = true`
   - `no_new_sql_executed = true`
   - `chart_override_requested`
5. If no prior result exists, `/chat` returns a stable clarification instead of a broken UI payload.

## Chart Override Rules

- `show as table` returns a table from the prior result.
- Heatmap requests require two dimensions and one measure.
- Bar/plot/graph requests choose the best supported visual shape:
  - two dimensions plus one measure -> `heatmap`
  - two dimensions plus multiple measures -> `grouped_bar`
  - one dimension plus a measure -> `bar`
- `grouped bar` requires two dimensions and a measure.
- `line chart` requires a time-like column and a measure.
- Unsupported shapes fall back to `table` with a chart warning.

## Heatmap Question Coverage

Heatmap tests use representative questions from the pilot pricing model:

- "Show opportunity count by implementation complexity and requested support tier for enterprise deals."
- "For analytics products, show line item count by pricing model and line role."
- "Show active contract count by billing frequency and currency."
- "Where is win rate strongest by deal segment and sales region?"

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Restricted SQL result followed by "plot the above" reuses rows | Fake-LLM chat regression test |
| No new compiled-plan query executes for visualization follow-up | Fake client call-count and tool-trace assertions |
| Prior restricted SQL query mode and SQL remain visible | Reused-result payload and inspector assertions |
| Chart spec matches assistant prose | Regression assertion on message and `chart_spec.chart_type` |
| Heatmap works for two-dimension, one-measure questions | Row-aware chart spec tests |
| Compiled-plan result followed by "show as table" is reused safely | Fake-LLM chat regression test |
| No prior result plus "plot the above" is stable | Clarification response regression test |
