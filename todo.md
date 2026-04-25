# Todo

- [x] Inspect current `/chat`, `/answer`, restricted SQL, UI inspector, docs, and tests
- [x] Update `spec.md` for the Phase 4.5 governed fallback pass
- [x] Keep compiled-plan `/answer` as the first/default chat lane
- [x] Add compiled-plan insufficiency detection for fallback semantic matches, missing requested fields, unsupported/incomplete review-needed states, and unsupported chart fallback metadata
- [x] Add bounded automatic restricted-SQL fallback orchestration behind routing controls
- [x] Provide the fallback LLM call with governed semantic entities, fields, approved joins, and SQL safety rules only
- [x] Preserve restricted SQL validation and return compiled results with warnings when fallback SQL is rejected
- [x] Add alternate governed query path messaging
- [x] Add fallback reason metadata for inspector rendering
- [x] Add deterministic fake-LLM golden routing tests for supported, single-entity fallback, approved-join fallback, contract fallback, and validation failure cases
- [x] Update README, TESTING, ARCHITECTURE, and roadmap tracking
- [x] Run deterministic test coverage
