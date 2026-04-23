# Answer Pipeline And Query Gateway Spec

## Task Summary

Build the first end-to-end answer path on top of the existing semantic planner, SQL compiler, and DuckDB execution harness.

## Goals

- Default `/answer` to the governed compiled-plan path.
- Return one structured answer payload containing the plan, query metadata, SQL, typed result columns, rows, truncation metadata, warnings, and chart spec.
- Generate deterministic chart specs for the current pilot chart intents: `line`, `bar`, `grouped_bar`, and `table`.
- Add a query gateway with two explicit modes:
  - `compiled_plan`: plan -> compiler -> execution
  - `restricted_sql`: validated governed SQL -> execution
- Keep restricted SQL as a secondary service boundary for future LLM tooling, not the default answer route.
- Add tests for answer generation, chart specs, HTTP `/answer`, selected-member drill context, and restricted SQL validation.

## Non-Goals

- No frontend UI rendering.
- No LLM-authored arbitrary SQL generation.
- No broad SQL parser or optimizer.
- No new web framework.
- No broad semantic model refactor.

## Repo Facts Observed

- `origin/main` and local `main` were in sync before this work.
- The repo contains seed CSVs under `data/seed/`.
- The repo contains a reviewed semantic model at `configs/semantic_models/pilot_pricing_v0.json`.
- The repo contains deterministic planner contracts and selected-member drill support under `datavisualizer/`.
- The repo contains a deterministic DuckDB SQL compiler and read-only execution harness.
- The repo uses Python standard-library `unittest` and a standard-library HTTP server for API tests.
- DuckDB is available in the local environment.

## Design Choices For This Pass

- Add the answer pipeline as a thin orchestration layer over existing planner/compiler/executor components.
- Keep result metadata semantic by deriving column lineage from the `AnalysisPlan`, not by guessing from raw SQL.
- Treat chart specs as declarative metadata only; no frontend rendering is introduced.
- Validate restricted SQL with a pilot-focused allowlist:
  - read-only `SELECT` statements only for this pilot pass
  - no multi-statement SQL
  - no direct file access
  - semantic-model entity names only in `FROM`/`JOIN`
  - joins must match approved semantic-model join edges
  - row limits are enforced by the gateway

## Supported Answer Shapes

- Planned semantic questions supported by the existing planner.
- Compiled-plan execution against seed CSVs.
- Plan filters, selected-member drill filters, measure-local filters, grouped dimensions, time buckets, and row limits supported by the compiler.
- Chart specs for `line`, `bar`, `grouped_bar`, and `table`.
- Restricted SQL queries that stay within semantic-model entities and approved joins.

## Rejected Query Shapes

- Unsupported planner/compiler plan shapes.
- Restricted SQL with write operations, direct file access, unapproved entities, unapproved joins, unsafe identifiers, multi-statement text, `WITH`, or unsupported statement types.
- Restricted SQL as the automatic route when compiled-plan execution can answer the request.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| `/answer` defaults to compiled plans | Unit and HTTP tests assert `query_mode == compiled_plan` |
| Answer payload is structured and serializable | Unit tests inspect plan, SQL, metadata, columns, rows, truncation, warnings, and chart spec |
| Chart specs are deterministic | Unit tests cover line, bar, grouped bar, and table pilot questions |
| Drill context flows through answer path | Unit and HTTP tests pass selected visual member context |
| Restricted SQL validates governed shapes | Unit tests cover approved SQL success |
| Restricted SQL rejects unsafe shapes | Unit tests cover write SQL, direct file access, unapproved entities, and unapproved joins |
| Existing planner/compiler behavior remains intact | Full `unittest` suite |
