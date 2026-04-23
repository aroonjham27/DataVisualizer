from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sql_compiler import CompiledQuery


class SqlExecutionError(ValueError):
    """Raised when SQL execution is unsafe or fails."""


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def execute_compiled_query(compiled_query: CompiledQuery) -> QueryResult:
    sql = compiled_query.sql.strip()
    _validate_read_only_sql(sql)
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SqlExecutionError("DuckDB Python package is required for execution.") from exc

    connection = duckdb.connect(database=":memory:", read_only=False)
    try:
        cursor = connection.execute(sql)
        rows = tuple(tuple(row) for row in cursor.fetchall())
        columns = tuple(column[0] for column in cursor.description or ())
        return QueryResult(columns=columns, rows=rows)
    finally:
        connection.close()


def _validate_read_only_sql(sql: str) -> None:
    normalized = " ".join(sql.lower().split())
    if not (normalized.startswith("select ") or normalized.startswith("with ")):
        raise SqlExecutionError("Only SELECT or WITH read queries may be executed.")
    blocked_tokens = (
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " create ",
        " attach ",
        " detach ",
        " copy ",
        " pragma ",
        " call ",
    )
    padded = f" {normalized} "
    for token in blocked_tokens:
        if token in padded:
            raise SqlExecutionError(f"Blocked non-read SQL token: {token.strip()}")
