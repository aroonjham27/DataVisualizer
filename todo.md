# Todo

- [x] Inspect current `/chat`, conversation state, chart rendering, inspector, and tests
- [x] Update `spec.md` for Phase 4.6 result-aware visualization follow-ups
- [x] Extend conversation state with the last governed result snapshot
- [x] Detect visualization-only follow-ups before model tool selection
- [x] Reuse prior governed rows, columns, SQL, query metadata, warnings, limits, chart spec, and plan when available
- [x] Generate deterministic chart specs for reused results
- [x] Add heatmap chart specs for two-dimension, one-measure result shapes
- [x] Add chart choice explanations to chart specs, reused-result prose, and inspector metadata
- [x] Support table, heatmap, bar, grouped bar, and line chart overrides with table fallback warnings
- [x] Preserve original query mode and SQL in reused-result inspector metadata
- [x] Add no-new-SQL and source-result metadata
- [x] Return a stable clarification when there is no prior result to plot
- [x] Add regression tests for restricted SQL plot follow-up, compiled-plan show-as-table follow-up, missing prior result, heatmap questions, and prose/chart consistency
- [x] Update README, TESTING, ARCHITECTURE, and roadmap tracking
- [x] Run deterministic test coverage
