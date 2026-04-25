# Testing

The current validation workflow uses Python's standard-library `unittest` runner.

## Run The Test Suite

From the repository root:

```powershell
py -3 -m unittest discover -s tests -t .
```

## Current Coverage

- semantic model loading
- golden-question planning for the pilot dataset
- drill continuation behavior
- selected visual member drill scoping
- join path correctness
- warning/status behavior
- fallback planning behavior
- `AnalysisPlan` serialization round trips
- minimal API payload handling
- true HTTP planning API round trips
- deterministic SQL compilation
- read-only DuckDB execution against seed CSVs
- unsupported SQL plan-shape rejection
- end-to-end compiled-plan answer generation
- deterministic chart spec generation for `line`, `bar`, `grouped_bar`, and `table`
- true HTTP `/answer` round trips
- selected-member drill context through the answer path and over HTTP
- restricted SQL gateway success and rejection cases
- structurally invalid restricted SQL lookalike rejection
- true truncation detection with one-extra-row probing
- row-aware chart fallback behavior for empty, sparse, over-wide, and too-many-category results
- heatmap chart specs for two-dimension, one-measure result shapes
- chart choice explanations in chart specs, reused-result prose, and inspector/static UI coverage
- stable API success and error envelopes
- routing flag behavior and compiled-plan-default routing metadata
- restricted SQL tool contract round trips
- deterministic fake-LLM routing tests for automatic restricted-SQL fallback after compiled-plan insufficiency
- safe restricted-SQL fallback rejection behavior that returns a compiled result with warnings
- result-aware conversation state for visualization-only follow-ups over prior governed results
- reused-result chart override behavior for restricted SQL and compiled-plan results
- provider adapter env parsing and graceful missing-credential behavior
- governed tool registration and schema shape for model tool-calling
- chat orchestration tool-call execution with a fake LLM client
- conversational carry-forward for `go deeper`, `just enterprise`, `top 5`, and `show as table`
- true HTTP `/chat` round trips
- opt-in dev `/chat` trace endpoint disabled-by-default behavior and secret-field redaction
- env-gated live-model smoke tests for normal analytics, drill follow-up, and compiled-plan-default routing
- root UI shell serving
- static UI asset serving
- UI contract helpers for chart view-model shaping
- selected-member drill payload generation from rendered chart rows
- inspector view-model shaping from governed answer and chat tool payloads
- grouped warning, routing-note, query-note, and chart fallback explanation coverage
- active filter, SQL, entity, row-limit, truncation, and chart-type visibility in inspector tests

## Expectations

- Add or update golden questions when planner behavior changes materially.
- Keep tests semantic-model-first: assert plans reference semantic entities and fields, not raw SQL.
- When ambiguity is expected, test for warnings rather than forcing brittle guesses.
- Keep SQL compiler tests focused on structured plans and compiled SQL, never natural-language SQL generation.
- Keep restricted SQL tests focused on governed validation boundaries; it is a fallback tool surface, not the default answer path.
- Keep automatic fallback tests focused on routing behavior and SQL shape, not exact formatting.
- Keep visualization follow-up tests deterministic and assert no new query tool runs when prior results can be reused.
- When chart heuristics change, test both the intended chart and the table fallback reason.
- For heatmaps, use representative two-category-dimension questions from the pricing seed, such as implementation complexity by support tier, pricing model by line role, billing frequency by currency, and segment by region.
- Keep tool-facing payload tests explicit about `ok`, `tool_name`, `data`, `error`, routing metadata, and structured warnings.
- Keep most orchestration tests on the fake client so behavior stays deterministic.
- Keep dev trace tests focused on bounded, opt-in observability and redaction; do not make tracing required for normal `/chat` behavior.
- Gate live-model smoke tests behind environment checks so they are optional for normal local runs.
- Keep UI tests lightweight and contract-focused unless the repo gains a browser automation harness.
- Keep inspector tests derived from existing `/chat` and tool-result payloads rather than adding separate debug-only contracts.

## Live Smoke Tests

Live chat smoke coverage is intentionally optional. Run it only when provider credentials are configured in the environment:

```powershell
$env:DATAVISUALIZER_RUN_LIVE_SMOKE="1"
py -3 -m unittest tests.test_chat.LiveChatSmokeTests
```

The live smoke path currently checks:

- a normal analytics question
- a drill follow-up
- a case where restricted SQL is allowed but compiled-plan should still be chosen

The deterministic chat suite includes golden fallback questions for custom opportunity, quote-line/product, and contract-header breakdowns. These tests assert that `/chat` evaluates `answer` first, uses `restricted_sql` only when policy and compiled-plan signals justify it, preserves inspector metadata, and handles restricted-SQL validation failure without broken UI payloads.

The suite also covers Phase 4.6 visualization follow-ups: a restricted-SQL table followed by "plot the above" must reuse the prior rows, preserve original SQL and query mode, set `no_new_sql_executed`, and produce a chart spec that matches the assistant prose.
