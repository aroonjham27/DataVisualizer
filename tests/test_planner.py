from __future__ import annotations

import json
import unittest
from pathlib import Path

from datavisualizer.contracts import AnalysisPlan, DrillSelection
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

    def test_selected_member_drill_context_scopes_follow_up(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("analytics",))

        follow_up = self.planner.plan("Go one level deeper", current_state=initial, selected_member=selected_member)

        self.assertIsNotNone(follow_up.drill)
        self.assertEqual(follow_up.drill.selected_member, selected_member)
        self.assertEqual([(item.field.field_id, item.operator, item.value, item.source) for item in follow_up.filters], [
            ("products.product_family", "=", "analytics", "visual_member")
        ])

    def test_competitor_plan_has_expected_join_path_edges(self) -> None:
        plan = self.planner.plan("Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?")

        edges = {(step.left_entity, step.right_entity, step.traversal) for step in plan.join_path}
        self.assertEqual(edges, {
            ("opportunities", "opportunity_competitors", "reverse"),
            ("opportunity_competitors", "competitors", "forward"),
        })

    def test_quote_mix_plan_has_expected_product_join_path(self) -> None:
        plan = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")

        self.assertEqual([(step.left_entity, step.right_entity, step.traversal) for step in plan.join_path], [
            ("opportunity_line_items", "products", "forward")
        ])

    def test_semantic_resolver_adds_direct_win_rate_dimensions(self) -> None:
        plan = self.planner.plan("What is the win rate by close month, industry, and region for enterprise?")

        self.assertEqual(_field_ids(plan.dimensions), ["accounts.industry", "opportunities.sales_region"])
        self.assertEqual(plan.time_dimension.field_id if plan.time_dimension else None, "opportunities.close_date")
        self.assertEqual([(item.field.field_id, item.operator, item.value) for item in plan.filters], [
            ("opportunities.segment", "=", "enterprise")
        ])
        self.assertIn("account-level sales region", " ".join(plan.warnings))

    def test_semantic_resolver_adds_user_directed_drill_target(self) -> None:
        initial = self.planner.plan("What is win rate by close month for enterprise?")

        follow_up = self.planner.plan("Go one level deeper to region", current_state=initial)

        self.assertEqual(_field_ids(follow_up.dimensions), ["opportunities.sales_region"])
        self.assertEqual([(item.field.field_id, item.operator, item.value) for item in follow_up.filters], [
            ("opportunities.segment", "=", "enterprise")
        ])
        self.assertIn("user-directed drill target opportunities.sales_region", " ".join(follow_up.notes))

    def test_semantic_resolver_adds_product_style_follow_up_dimension(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")

        by_product = self.planner.plan("Show that by product only", current_state=initial)
        by_pricing_model = self.planner.plan("break it down by pricing model", current_state=initial)

        self.assertIn("products.product_name", _field_ids(by_product.dimensions))
        self.assertIn("products.pricing_model", _field_ids(by_pricing_model.dimensions))
        self.assertIn("requested semantic breakdown products.pricing_model", " ".join(by_pricing_model.notes))

    def test_warning_status_behavior(self) -> None:
        review_needed = self.planner.plan("What is win rate by sales region?")
        ok_plan = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")

        self.assertEqual(review_needed.status, "review_needed")
        self.assertIn("account-level sales region", " ".join(review_needed.warnings))
        self.assertEqual(ok_plan.status, "ok")
        self.assertEqual(ok_plan.warnings, ())

    def test_fallback_planning_behavior_for_unsupported_trend_question(self) -> None:
        plan = self.planner.plan("Show me the retention trend by renewal risk")

        self.assertEqual(plan.status, "review_needed")
        self.assertEqual(plan.primary_entity, "opportunities")
        self.assertEqual(_measure_field_ids(plan.measures), ["opportunities.opportunity_count"])
        self.assertEqual(plan.chart_intent.chart_type if plan.chart_intent else None, "table")
        self.assertIn("fallback semantic match", " ".join(plan.warnings))

    def test_analysis_plan_serialization_round_trip(self) -> None:
        plan = self.planner.plan("Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?")
        payload = json.loads(json.dumps(plan.to_dict()))

        restored = AnalysisPlan.from_dict(payload)

        self.assertEqual(restored, plan)


if __name__ == "__main__":
    unittest.main()
