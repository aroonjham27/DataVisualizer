from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer

from datavisualizer.answer import AnswerService
from datavisualizer.api import PlanningRequestHandler, handle_answer_request
from datavisualizer.charting import ChartSpecGenerator
from datavisualizer.contracts import ChartIntent, DrillSelection, ResultColumn
from datavisualizer.query_gateway import QueryGateway, RestrictedSqlValidationError


class AnswerPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = AnswerService.from_default_model()

    def test_answer_generation_defaults_to_compiled_plan(self) -> None:
        response = self.service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=7)

        self.assertEqual(response.query_mode, "compiled_plan")
        self.assertEqual(response.query_metadata.query_mode, "compiled_plan")
        self.assertEqual(response.limit.row_limit, 7)
        self.assertLessEqual(response.limit.returned_rows, 7)
        self.assertTrue(response.limit.truncated)
        self.assertIn("opportunities", response.query_metadata.involved_entities)
        self.assertIn("read_csv_auto", response.sql)
        self.assertEqual(response.chart_spec.chart_type, "line")
        self.assertIn("opportunities_win_rate", response.chart_spec.y)
        self.assertEqual(response.columns[-1].semantic_lineage, ("opportunities.win_rate",))

    def test_chart_specs_for_pilot_chart_intents(self) -> None:
        line = self.service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=3)
        grouped = self.service.answer("How do quoted discount rates and annualized quote amounts vary by product family and line role?", row_limit=3)
        bar = self.service.answer("Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?", row_limit=3)
        table = self.service.answer("Show me the retention trend by renewal risk", row_limit=3)

        self.assertEqual(line.chart_spec.chart_type, "line")
        self.assertEqual(line.chart_spec.x, "opportunities_close_date_month")
        self.assertEqual(grouped.chart_spec.chart_type, "grouped_bar")
        self.assertEqual(grouped.chart_spec.x, "products_product_family")
        self.assertEqual(grouped.chart_spec.series, "opportunity_line_items_line_role")
        self.assertEqual(bar.chart_spec.chart_type, "bar")
        self.assertEqual(bar.chart_spec.x, "competitors_competitor_name")
        self.assertEqual(table.chart_spec.chart_type, "table")
        self.assertIn("opportunities_opportunity_count", table.chart_spec.columns)

    def test_handle_answer_request_is_serializable(self) -> None:
        response = handle_answer_request(
            {
                "question": "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
                "row_limit": 5,
            },
            service=self.service,
        )

        json.dumps(response)
        self.assertEqual(response["query_mode"], "compiled_plan")
        self.assertEqual(response["chart_spec"]["chart_type"], "grouped_bar")
        self.assertLessEqual(response["limit"]["returned_rows"], 5)
        self.assertEqual(response["columns"][0]["semantic_lineage"], ("products.product_family",))

    def test_selected_member_drill_context_flows_through_answer(self) -> None:
        initial = self.service.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("analytics",))

        response = self.service.answer("Go one level deeper", current_analysis_state=initial, selected_member=selected_member, row_limit=5)

        self.assertEqual(response.plan.filters[0].field.field_id, "products.product_family")
        self.assertEqual(response.plan.filters[0].value, "analytics")
        self.assertIn('WHERE "t1"."product_family" = \'analytics\'', response.sql)
        self.assertIn("products_product_name", response.chart_spec.columns)

    def test_http_answer_round_trip(self) -> None:
        payload = self._post_answer(
            {
                "question": "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
                "row_limit": 4,
            }
        )

        self.assertEqual(payload["query_mode"], "compiled_plan")
        self.assertEqual(payload["chart_spec"]["chart_type"], "grouped_bar")
        self.assertLessEqual(payload["limit"]["returned_rows"], 4)

    def test_http_answer_round_trip_with_selected_member_drill_context(self) -> None:
        initial = self.service.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        payload = self._post_answer(
            {
                "question": "Go one level deeper",
                "current_analysis_state": initial.to_dict(),
                "selected_member": {
                    "field": initial.dimensions[0].__dict__,
                    "values": ["analytics"],
                    "source": "visual_member",
                },
                "row_limit": 4,
            }
        )

        self.assertEqual(payload["query_mode"], "compiled_plan")
        self.assertEqual(payload["plan"]["filters"][0]["field"]["entity"], "products")
        self.assertEqual(payload["plan"]["filters"][0]["field"]["name"], "product_family")
        self.assertEqual(payload["plan"]["filters"][0]["value"], "analytics")
        self.assertIn("products_product_name", payload["chart_spec"]["columns"])

    def test_answer_empty_result_falls_back_to_table(self) -> None:
        initial = self.service.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("not_a_product_family",))

        response = self.service.answer("Go one level deeper", current_analysis_state=initial, selected_member=selected_member, row_limit=5)

        self.assertEqual(response.limit.returned_rows, 0)
        self.assertFalse(response.limit.truncated)
        self.assertEqual(response.chart_spec.chart_type, "table")
        self.assertIn("empty", " ".join(response.warnings).lower())

    def test_answer_over_wide_result_falls_back_to_table(self) -> None:
        service = AnswerService.from_default_model()
        service.chart_specs.max_chart_columns = 3

        response = service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=5)

        self.assertEqual(response.chart_spec.chart_type, "table")
        self.assertIn("over-wide", " ".join(response.warnings))

    def _post_answer(self, payload: dict[str, object]) -> dict[str, object]:
        PlanningRequestHandler.answer_service = self.service
        PlanningRequestHandler.planner = self.service.planner
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/answer",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class RestrictedSqlGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gateway = QueryGateway.from_default_model(default_limit=5)

    def test_restricted_sql_executes_approved_single_entity_query(self) -> None:
        result = self.gateway.execute_restricted_sql(
            "SELECT segment, COUNT(DISTINCT opportunity_id) AS opportunity_count "
            "FROM opportunities GROUP BY segment ORDER BY opportunity_count DESC",
            row_limit=3,
        )

        self.assertEqual(result.query_mode, "restricted_sql")
        self.assertEqual(result.metadata.row_limit, 3)
        self.assertEqual(result.metadata.involved_entities, ("opportunities",))
        self.assertLessEqual(len(result.result.rows), 3)
        self.assertTrue(result.truncated)

    def test_restricted_sql_executes_approved_join_query(self) -> None:
        result = self.gateway.execute_restricted_sql(
            "SELECT a.segment, COUNT(DISTINCT o.opportunity_id) AS opportunity_count "
            "FROM accounts a JOIN opportunities o ON a.account_id = o.account_id "
            "GROUP BY a.segment ORDER BY opportunity_count DESC",
            row_limit=3,
        )

        self.assertEqual(result.metadata.involved_entities, ("accounts", "opportunities"))
        self.assertLessEqual(len(result.result.rows), 3)

    def test_restricted_sql_rejects_unsafe_or_unsupported_shapes(self) -> None:
        bad_queries = [
            "DROP TABLE accounts",
            "SELECT * FROM read_csv_auto('data/seed/accounts.csv')",
            "SELECT * FROM missing_entity",
            "SELECT * FROM accounts JOIN usage_metrics ON accounts.account_id = usage_metrics.product_id",
            "SELECT * FROM opportunities WHERE opportunity_name LIKE '%renewal%'",
            "SELECT * FROM opportunities; SELECT * FROM accounts",
        ]

        for sql in bad_queries:
            with self.subTest(sql=sql):
                with self.assertRaises(RestrictedSqlValidationError):
                    self.gateway.execute_restricted_sql(sql)

    def test_restricted_sql_rejects_structurally_invalid_lookalikes(self) -> None:
        bad_queries = [
            "SELECT * FROM (SELECT * FROM opportunities) o",
            "SELECT * FROM accounts, opportunities",
            "SELECT * FROM accounts JOIN opportunities",
            "SELECT * FROM accounts JOIN opportunities ON accounts.account_id",
            "SELECT * FROM accounts JOIN opportunities ON accounts.account_id = opportunities.account_id OR 1 = 1",
            "SELECT * FROM accounts JOIN opportunities ON lower(accounts.account_id) = opportunities.account_id",
            "SELECT * FROM accounts JOIN opportunities ON accounts.account_id <> opportunities.account_id",
            "SELECT * FROM accounts unexpected_alias opportunities",
            "SELECT * FROM accounts WHERE segment != 'enterprise'",
            "WITH q AS (SELECT * FROM accounts) SELECT * FROM q",
        ]

        for sql in bad_queries:
            with self.subTest(sql=sql):
                with self.assertRaises(RestrictedSqlValidationError):
                    self.gateway.execute_restricted_sql(sql)


class RowAwareChartSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = ChartSpecGenerator()
        self.plan = AnswerService.from_default_model().planner.plan(
            "How do quoted discount rates and annualized quote amounts vary by product family and line role?"
        )

    def test_too_many_categories_falls_back_to_table(self) -> None:
        columns = (
            ResultColumn("category", "Category", "string", ("products.product_family",), "dimension"),
            ResultColumn("value", "Value", "number", ("opportunity_line_items.annualized_amount",), "measure"),
        )
        rows = tuple((f"category_{index}", index) for index in range(self.generator.max_categories + 1))
        plan = replace(self.plan, chart_intent=ChartIntent(chart_type="bar", reason="test"))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "table")
        self.assertIn("too many categories", " ".join(chart.warnings))

    def test_sparse_rows_fall_back_to_table(self) -> None:
        columns = (
            ResultColumn("category", "Category", "string", ("products.product_family",), "dimension"),
            ResultColumn("value", "Value", "number", ("opportunity_line_items.annualized_amount",), "measure"),
        )
        rows = (("analytics", None), ("workflow", None), ("platform", None))
        plan = replace(self.plan, chart_intent=ChartIntent(chart_type="bar", reason="test"))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "table")
        self.assertIn("sparse", " ".join(chart.warnings))

    def test_single_series_grouped_bar_omits_series(self) -> None:
        columns = (
            ResultColumn("category", "Category", "string", ("products.product_family",), "dimension"),
            ResultColumn("value", "Value", "number", ("opportunity_line_items.annualized_amount",), "measure"),
        )
        rows = (("analytics", 10), ("workflow", 20))
        plan = replace(self.plan, chart_intent=ChartIntent(chart_type="grouped_bar", reason="test"))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "grouped_bar")
        self.assertIsNone(chart.series)


if __name__ == "__main__":
    unittest.main()
