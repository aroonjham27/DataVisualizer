from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
