# Plan-To-SQL Compiler Spec

## Task Summary

Build a deterministic compiler that turns a governed `AnalysisPlan` into safe read-only DuckDB SQL for the pilot seed dataset.

## Goals

- Compile only from the semantic model and structured `AnalysisPlan`.
- Support primary entity selection, approved join paths, grouped dimensions, time bucketing, measure aggregations, measure-local filters, plan filters, selected-member drill filters, stable ordering, and row limiting.
- Add a minimal DuckDB execution harness for verification against seed CSVs.
- Add tests for SQL compilation and basic execution.
- Add a lightweight true HTTP round-trip test for the planning API.

## Non-Goals

- No frontend UI.
- No natural-language SQL generation.
- No arbitrary SQL expression support.
- No broad SQL optimizer or warehouse abstraction.
- No external frameworks.

## Repo Facts Observed

- `origin/main` and local `main` were in sync before this work.
- The repo contains seed CSVs under `data/seed/`.
- The repo contains a reviewed semantic model at `configs/semantic_models/pilot_pricing_v0.json`.
- The repo contains deterministic planner contracts and drill context support under `datavisualizer/`.
- The repo contains a standard-library `unittest` suite.
- DuckDB Python package `1.5.2` is available in the local environment.

## Design Choices For This Pass

- Keep SQL generation deterministic and pilot-focused.
- Compile CTEs over `read_csv_auto(...)` for each referenced semantic entity.
- Reject unsupported plan shapes instead of guessing.
- Use semantic aliases and compiler-owned SQL expressions rather than raw user text.
- Keep execution harness read-only by accepting compiled SQL only and rejecting non-`SELECT` SQL.

## Supported Plan Shapes

- One primary entity.
- Approved join paths from `AnalysisPlan.join_path`.
- Dimensions and time buckets in `SELECT` and `GROUP BY`.
- Aggregations: `count_distinct`, `sum`, `average`, and the pilot `win_rate` ratio.
- Measure-local equality filters via `CASE WHEN ... THEN ... END`.
- Plan filters with `=` and `in`.
- `year`, `quarter`, `month`, and `day` time grains.
- Stable `ORDER BY` on grouped fields and `LIMIT`.

## Rejected Plan Shapes

- Unknown entities or fields.
- Joins not present in the plan's approved join path.
- Unsupported aggregations.
- Unsupported filter operators.
- Unsupported time grains.
- Raw SQL expressions from requests or plans.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| SQL uses semantic model and plan fields only | Unit tests assert compiled SQL uses expected CSV CTEs, aliases, joins, and no raw-question SQL |
| Join paths compile correctly | Unit tests for quote/product and competitor/opportunity/competitor joins |
| Filters compile safely | Unit tests for selected-member drill filters and measure-local filters |
| Time bucketing compiles | Unit tests for close-month and usage-month plans |
| Compiled SQL executes against seed CSVs | DuckDB execution tests with non-empty result sets |
| Unsupported shapes are rejected | Unit tests for unsupported aggregation/filter/time grain |
| Planning API has true HTTP coverage | Test starts local stdlib HTTP server and posts to `/analysis-plan` |
