from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .answer import AnswerService
from .contracts import AnalysisRequest, AnswerRequest, RestrictedSqlRequest
from .errors import error_envelope, normalize_error, success_envelope
from .planner import DEFAULT_MODEL_PATH, SemanticPlanner
from .semantic_model import load_semantic_model


def build_planner(model_path: str | None = None) -> SemanticPlanner:
    target = Path(model_path).resolve() if model_path else DEFAULT_MODEL_PATH
    return SemanticPlanner(load_semantic_model(target))


def handle_plan_request(payload: dict[str, Any], planner: SemanticPlanner | None = None) -> dict[str, Any]:
    request = AnalysisRequest.from_dict(payload)
    active_planner = planner or build_planner(request.semantic_model_path)
    plan = active_planner.plan(request.question, request.current_analysis_state, request.selected_member)
    return success_envelope("analysis_plan", plan.to_dict())


def handle_answer_request(payload: dict[str, Any], service: AnswerService | None = None) -> dict[str, Any]:
    request = AnswerRequest.from_dict(payload)
    active_service = service or AnswerService.from_model_path(request.semantic_model_path)
    return success_envelope("answer", active_service.answer_request(request).to_dict())


def handle_restricted_sql_request(payload: dict[str, Any], service: AnswerService | None = None) -> dict[str, Any]:
    request = RestrictedSqlRequest.from_dict(payload)
    active_service = service or AnswerService.from_model_path(request.semantic_model_path)
    return success_envelope("restricted_sql", active_service.restricted_sql_request(request).to_dict())


class PlanningRequestHandler(BaseHTTPRequestHandler):
    planner = build_planner()
    answer_service = AnswerService.from_default_model()

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/analysis-plan", "/answer", "/restricted-sql"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Unsupported route")
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
            if self.path == "/analysis-plan":
                response = handle_plan_request(payload, self.planner)
                status = HTTPStatus.OK
            elif self.path == "/restricted-sql":
                response = handle_restricted_sql_request(payload, self.answer_service)
                status = HTTPStatus.OK
            else:
                response = handle_answer_request(payload, self.answer_service)
                status = HTTPStatus.OK
        except Exception as exc:  # noqa: BLE001
            payload = normalize_error(exc)
            tool_name = "analysis_plan" if self.path == "/analysis-plan" else "restricted_sql" if self.path == "/restricted-sql" else "answer"
            response = error_envelope(tool_name, payload)
            status = HTTPStatus.BAD_REQUEST if payload.error_type in {"validation_error", "unsupported_query_shape"} else HTTPStatus.INTERNAL_SERVER_ERROR

        response_body = json.dumps(response, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DataVisualizer semantic planning API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--semantic-model-path", default=str(DEFAULT_MODEL_PATH))
    args = parser.parse_args()

    PlanningRequestHandler.planner = build_planner(args.semantic_model_path)
    PlanningRequestHandler.answer_service = AnswerService.from_model_path(args.semantic_model_path)
    server = ThreadingHTTPServer((args.host, args.port), PlanningRequestHandler)
    try:
        print(f"Serving semantic planner API on http://{args.host}:{args.port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
