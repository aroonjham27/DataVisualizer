from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .contracts import AnalysisRequest
from .planner import DEFAULT_MODEL_PATH, SemanticPlanner
from .semantic_model import load_semantic_model


def build_planner(model_path: str | None = None) -> SemanticPlanner:
    target = Path(model_path).resolve() if model_path else DEFAULT_MODEL_PATH
    return SemanticPlanner(load_semantic_model(target))


def handle_plan_request(payload: dict[str, Any], planner: SemanticPlanner | None = None) -> dict[str, Any]:
    request = AnalysisRequest.from_dict(payload)
    active_planner = planner or build_planner(request.semantic_model_path)
    plan = active_planner.plan(request.question, request.current_analysis_state)
    return plan.to_dict()


class PlanningRequestHandler(BaseHTTPRequestHandler):
    planner = build_planner()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/analysis-plan":
            self.send_error(HTTPStatus.NOT_FOUND, "Unsupported route")
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
            response = handle_plan_request(payload, self.planner)
        except Exception as exc:  # noqa: BLE001
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        response_body = json.dumps(response, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
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
