from __future__ import annotations

import unittest

from datavisualizer.contracts import DrillSelection
from datavisualizer.api import handle_plan_request
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


if __name__ == "__main__":
    unittest.main()
