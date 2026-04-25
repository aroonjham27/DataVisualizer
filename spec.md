# Phase 4.5 Governed Fallback Orchestration Spec

## Task Summary

Harden `/chat` so restricted SQL can act as an invisible governed fallback when the default compiled-plan `/answer` path cannot confidently satisfy a valid analytics request.

## Goals

- Keep `/chat` as the user-facing path.
- Keep `/answer` as the default compiled-plan analytics lane.
- Evaluate compiled-plan adequacy before any automatic restricted-SQL attempt.
- Use restricted SQL only when routing allows it and the request can be represented as a safe governed `SELECT`.
- Preserve the restricted SQL validator and gateway as the only execution path for fallback SQL.
- Avoid exposing a restricted-SQL mode, raw SQL input, or frontend SQL editor.
- Add transparent assistant messaging and inspector metadata when fallback is used.
- Cover routing behavior with deterministic fake-LLM tests.

## Non-Goals

- No broad SQL surface expansion.
- No raw client-side query path.
- No auth or permission model.
- No frontend redesign.
- No replacement of compiled-plan as the normal path.

## Fallback Policy

1. `/chat` asks the model for the normal governed `answer` tool call.
2. The backend executes `/answer` and inspects the compiled-plan result.
3. Restricted SQL is considered only when:
   - routing allows `restricted_sql`
   - the request looks like a valid analytics request
   - compiled-plan signals indicate fallback, unsupported, incomplete, or missing semantic coverage
   - the requested fields/entities appear representable over semantic-model entities and approved joins
4. The backend then asks the model for exactly one `restricted_sql` tool call using a fallback prompt that includes only governed semantic entities, fields, approved joins, and safety rules.
5. SQL execution still flows through the existing restricted SQL validator and gateway.
6. If validation or execution rejects the fallback SQL, `/chat` returns the compiled-plan result with a warning rather than repairing SQL unsafely.

## Insufficiency Signals

- Planner fallback semantic-match warning.
- Review-needed states tied to unsupported or incomplete planning warnings.
- Requested semantic dimensions or filters missing from the compiled plan.
- Unsupported chart/table fallback metadata.

Review-needed ambiguity alone is not enough when the compiled plan covers the requested fields.

## UX Contract

- The assistant includes an alternate governed query path notice when restricted SQL is used.
- The inspector shows:
  - `query_mode = restricted_sql`
  - fallback reason
  - SQL executed
  - involved entities
  - row limit and truncation status
- Restricted SQL fallback results default to table rendering unless a later governed chart contract is added.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Supported compiled-plan question stays compiled-plan | Fake-LLM chat test with win rate by close month and account segment |
| Single-entity custom breakdown falls back | Fake-LLM chat test asserting opportunity SQL shape |
| Approved-join custom breakdown falls back | Fake-LLM chat test asserting quote-line to products join |
| Contract-header custom aggregation falls back | Fake-LLM chat test asserting active contracts SQL shape |
| Validation failure is safe | Fake-LLM chat test with invalid restricted SQL and compiled-result warning |
| Inspector exposes fallback reason | UI contract and chat tests using fallback result metadata |
