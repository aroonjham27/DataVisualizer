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

## Expectations

- Add or update golden questions when planner behavior changes materially.
- Keep tests semantic-model-first: assert plans reference semantic entities and fields, not raw SQL.
- When ambiguity is expected, test for warnings rather than forcing brittle guesses.
