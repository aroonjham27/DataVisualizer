# Todo

- [x] Inspect `/chat`, restricted SQL validation, planner value indexing, docs, and tests
- [x] Update `spec.md` for Phase 4.7 trust hardening
- [x] Canonicalize restricted SQL filter values against indexed governed data values before execution
- [x] Reject unknown indexed restricted SQL filter values safely
- [x] Detect explicit new standalone analytics requests before passing current analysis state to tools
- [x] Preserve state for true follow-ups such as "go deeper" and visualization-only requests
- [x] Add deterministic assistant prose consistency guard for stale measure, filter, and chart claims
- [x] Require unambiguous heatmap axes and one measure before rendering a heatmap
- [x] Fall back to table with a clarification warning when heatmap requests would silently drop extra dimensions or time fields
- [x] Add restricted SQL casing regressions for `enterprise`, `Enterprise`, and `ENTERPRISE`
- [x] Add stale-state reset regression for win-rate drill followed by analytics product line-item count
- [x] Add true-follow-up and visualization-follow-up preservation regressions
- [x] Add heatmap ambiguity regressions for extra prior dimensions and explicit axis selection
- [x] Update README, TESTING, ARCHITECTURE, spec, todo, and roadmap tracking
- [x] Run focused deterministic trust-hardening tests
- [x] Run the full deterministic test suite
