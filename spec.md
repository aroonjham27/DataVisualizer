# Restricted SQL And Chart Hardening Spec

## Task Summary

Harden the restricted-SQL fallback boundary and make chart specs inspect result rows so the answer pipeline is safer and more renderer-ready.

## Goals

- Keep `/answer` defaulting to the compiled-plan path.
- Replace broad restricted-SQL relation parsing with a small tokenized structure parser.
- Preserve semantic-model-approved entities and joins only.
- Preserve read-only behavior and gateway-enforced row limits.
- Improve result-limit metadata by detecting true truncation with one-extra-row probing.
- Generate chart specs from both semantic columns and result rows.
- Fall back to tables for weak chart shapes such as empty, sparse, over-wide, or too-many-category results.

## Non-Goals

- No frontend UI rendering.
- No arbitrary LLM-authored SQL execution.
- No broad SQL parser.
- No new SQL clauses unless this pass validates them explicitly.
- No semantic model redesign.

## Repo Facts Observed

- Local `main` and `origin/main` were in sync before this work.
- The repo contains a planner, compiler, answer service, chart spec generator, query gateway, and stdlib tests.
- Restricted SQL is already a secondary internal gateway path, not the default `/answer` route.
- Existing tests cover planning, compilation, execution, answer generation, `/answer`, and restricted SQL basics.

## Design Choices For This Pass

- Keep the restricted SQL subset intentionally small: one `SELECT`, semantic `FROM`, optional explicit `JOIN ... ON`, optional `WHERE`, `GROUP BY`, `ORDER BY`, and optional trailing `LIMIT`.
- Tokenize SQL before validating relation order and join clauses, rather than relying on regex relation extraction.
- Continue to reject structurally ambiguous or unsupported SQL instead of trying to repair it.
- Execute one extra row internally and trim before returning results so `truncated` means more data was actually available.
- Keep chart heuristics deterministic and conservative. If chart quality is questionable, return a `table` spec with warnings.

## Supported Restricted SQL Shapes

- Read-only `SELECT` statements only.
- Semantic-model entity names in `FROM` and `JOIN`.
- Optional aliases using bare alias or `AS alias`.
- Explicit inner `JOIN ... ON left_alias.key = right_alias.key`.
- Approved semantic-model join edges only.
- Optional `WHERE` with simple `=` or `IN` predicates joined by `AND`.
- Optional `GROUP BY`, `ORDER BY`, and trailing `LIMIT`.

## Rejected Restricted SQL Shapes

- Writes or side effects.
- Semicolons or multiple statements.
- Direct file/table-function access such as `read_csv_auto`.
- Unknown entities.
- Cross joins, comma joins, subqueries, CTEs, derived tables, unions, set operations, or nested relation expressions.
- Joins without approved semantic keys.
- Joins with `OR`, inequality, function calls, or incomplete `ON` predicates.
- Unsupported operators such as `LIKE`, `ILIKE`, regex, inequality, arithmetic predicates, or unvalidated functions in filters.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Restricted SQL uses tokenized structure validation | Unit tests for malformed relation/join shapes that used to look superficially valid |
| Approved restricted SQL still executes | Existing and new gateway tests |
| Unsafe restricted SQL is rejected | Unit tests for subqueries, comma joins, incomplete joins, unsupported predicates, and direct file access |
| True truncation is detected | Answer tests with small and oversized row limits |
| Chart specs inspect rows | Unit tests for empty results, too many categories, over-wide grouped results, sparse results, and valid single/multi-series specs |
| `/answer` remains compiled-plan default | Existing and updated answer tests |
