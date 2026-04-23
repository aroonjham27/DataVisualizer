from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from datavisualizer.contracts import DrillSelection
from datavisualizer.api import PlanningRequestHandler, handle_plan_request
from datavisualizer.planner import SemanticPlanner


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner = SemanticPlanner.from_default_model()

    def test_handle_plan_request_returns_serializable_plan(self) -> None:
        response = handle_plan_request(
            {"question": "What is win rate by close month, account segment, sales region, and lifecycle type?"},
            planner=self.planner,
        )

        self.assertEqual(response["primary_entity"], "opportunities")
        self.assertEqual(response["time_dimension"]["entity"], "opportunities")
        self.assertEqual(response["time_dimension"]["name"], "close_date")
        self.assertEqual(response["time_grain"], "month")

    def test_handle_plan_request_accepts_selected_member_for_drill(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("analytics",))

        response = handle_plan_request(
            {
                "question": "Go one level deeper",
                "current_analysis_state": initial.to_dict(),
                "selected_member": {
                    "field": selected_member.field.__dict__,
                    "values": selected_member.values,
                    "source": selected_member.source,
                },
            },
            planner=self.planner,
        )

        self.assertEqual(response["drill"]["selected_member"]["field"]["entity"], "products")
        self.assertEqual(response["drill"]["selected_member"]["values"], ("analytics",))
        self.assertEqual(response["filters"][0]["field"]["name"], "product_family")

    def test_http_round_trip_returns_analysis_plan(self) -> None:
        PlanningRequestHandler.planner = self.planner
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/analysis-plan"
            request = urllib.request.Request(
                url,
                data=json.dumps({"question": "What is win rate by close month, account segment, sales region, and lifecycle type?"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(payload["primary_entity"], "opportunities")
        self.assertEqual(payload["measures"][0]["field"]["name"], "win_rate")


if __name__ == "__main__":
    unittest.main()
