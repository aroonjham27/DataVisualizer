from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .execution import SqlExecutionError
from .query_gateway import RestrictedSqlValidationError
from .sql_compiler import SqlCompilationError


@dataclass(frozen=True)
class ErrorPayload:
    error_type: str
    error_code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BackendContractError(Exception):
    error_type = "validation_error"
    error_code = "backend_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details

    def to_payload(self) -> ErrorPayload:
        return ErrorPayload(
            error_type=self.error_type,
            error_code=self.error_code,
            message=str(self),
            details=self.details,
        )


class RequestValidationError(BackendContractError):
    error_type = "validation_error"
    error_code = "invalid_request"


class UnsupportedQueryShapeError(BackendContractError):
    error_type = "unsupported_query_shape"
    error_code = "unsupported_query_shape"


class QueryExecutionFailure(BackendContractError):
    error_type = "execution_failure"
    error_code = "query_execution_failed"


def normalize_error(exc: Exception) -> ErrorPayload:
    if isinstance(exc, BackendContractError):
        return exc.to_payload()
    if isinstance(exc, (SqlCompilationError, RestrictedSqlValidationError)):
        return UnsupportedQueryShapeError(str(exc)).to_payload()
    if isinstance(exc, SqlExecutionError):
        return QueryExecutionFailure(str(exc)).to_payload()
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return RequestValidationError(str(exc)).to_payload()
    return QueryExecutionFailure(str(exc)).to_payload()


def success_envelope(tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "tool_name": tool_name,
        "data": data,
        "error": None,
    }


def error_envelope(tool_name: str, payload: ErrorPayload) -> dict[str, Any]:
    return {
        "ok": False,
        "tool_name": tool_name,
        "data": None,
        "error": payload.to_dict(),
    }
