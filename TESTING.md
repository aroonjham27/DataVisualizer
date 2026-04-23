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

## Expectations

- Add or update golden questions when planner behavior changes materially.
- Keep tests semantic-model-first: assert plans reference semantic entities and fields, not raw SQL.
- When ambiguity is expected, test for warnings rather than forcing brittle guesses.
- Keep SQL compiler tests focused on structured plans and compiled SQL, never natural-language SQL generation.
- Keep restricted SQL tests focused on governed validation boundaries; it is a fallback tool surface, not the default answer path.
