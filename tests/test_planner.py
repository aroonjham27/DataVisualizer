from __future__ import annotations

import json
import unittest
from pathlib import Path

from datavisualizer.planner import SemanticPlanner


FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "golden_questions.json"


def _field_ids(fields) -> list[str]:
    return [field.field_id for field in fields]


def _measure_field_ids(measures) -> list[str]:
    return [measure.field.field_id for measure in measures]


class PlannerGoldenQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner = SemanticPlanner.from_default_model()
        cls.fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))

    def test_golden_questions_plan_to_expected_structures(self) -> None:
        for entry in self.fixtures:
            with self.subTest(question=entry["question"]):
                plan = self.planner.plan(entry["question"])
                expected = entry["expected"]
                self.assertEqual(plan.primary_entity, expected["primary_entity"])
                if "measures" in expected:
                    self.assertEqual(_measure_field_ids(plan.measures), expected["measures"])
                if "measure_filters" in expected:
                    actual_measure_filters = []
                    for measure in plan.measures:
                        for filter_ in measure.local_filters:
                            actual_measure_filters.append(f"{filter_.field.field_id}{filter_.operator}{filter_.value}")
                    self.assertEqual(actual_measure_filters, expected["measure_filters"])
                if "dimensions" in expected:
                    self.assertEqual(_field_ids(plan.dimensions), expected["dimensions"])
                if "filters" in expected:
                    actual_filters = [f"{item.field.field_id}{item.operator}{item.value}" for item in plan.filters]
                    self.assertEqual(actual_filters, expected["filters"])
                self.assertEqual(plan.time_dimension.field_id if plan.time_dimension else None, expected.get("time_dimension"))
                self.assertEqual(plan.time_grain, expected.get("time_grain"))
                self.assertEqual(plan.chart_intent.chart_type if plan.chart_intent else None, expected["chart_type"])

    def test_drill_continuation_adds_next_hierarchy_level(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        follow_up = self.planner.plan("Go one level deeper", current_state=initial)

        self.assertEqual(_field_ids(follow_up.dimensions), [
            "products.product_family",
            "products.product_name",
            "opportunity_line_items.line_role",
        ])
        self.assertIsNotNone(follow_up.drill)
        self.assertEqual(follow_up.drill.current_level_index, 1)
        self.assertEqual(follow_up.drill.next_level, "opportunity_line_items.line_role")
        self.assertEqual(follow_up.chart_intent.chart_type if follow_up.chart_intent else None, "table")

    def test_drill_continuation_warns_when_no_drill_path_exists(self) -> None:
        initial = self.planner.plan("Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?")
        follow_up = self.planner.plan("Go one level deeper", current_state=initial)

        self.assertIn("No deeper drill level is available", " ".join(follow_up.warnings))


if __name__ == "__main__":
    unittest.main()
