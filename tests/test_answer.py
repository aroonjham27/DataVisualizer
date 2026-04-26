from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from dataclasses import replace
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

from datavisualizer.answer import AnswerService
from datavisualizer.api import PlanningRequestHandler, handle_answer_request, handle_restricted_sql_request
from datavisualizer.charting import ChartSpecGenerator
from datavisualizer.contracts import ChartIntent, DrillSelection, ResultColumn, RoutingControls
from datavisualizer.query_gateway import QueryGateway, RestrictedSqlValidationError


class AnswerPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = AnswerService.from_default_model()

    def test_answer_generation_defaults_to_compiled_plan(self) -> None:
        response = self.service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=7)

        self.assertEqual(response.tool_name, "answer")
        self.assertEqual(response.routing.policy, "compiled_plan_only")
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

    def test_answer_routing_can_allow_restricted_sql_without_changing_default_lane(self) -> None:
        response = self.service.answer(
            "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
            row_limit=5,
            routing=RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
        )

        self.assertEqual(response.routing.policy, "restricted_sql_allowed")
        self.assertFalse(response.routing.compiled_plan_only)
        self.assertTrue(response.routing.restricted_sql_allowed)
        self.assertEqual(response.routing.selected_query_mode, "compiled_plan")
        self.assertIn("compiled-plan remained the selected lane", " ".join(response.query_metadata.validation_notes))

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
        self.assertTrue(response["ok"])
        self.assertEqual(response["tool_name"], "answer")
        self.assertEqual(response["data"]["tool_name"], "answer")
        self.assertEqual(response["data"]["routing"]["policy"], "compiled_plan_only")
        self.assertEqual(response["data"]["query_mode"], "compiled_plan")
        self.assertEqual(response["data"]["chart_spec"]["chart_type"], "grouped_bar")
        self.assertLessEqual(response["data"]["limit"]["returned_rows"], 5)
        self.assertEqual(response["data"]["columns"][0]["semantic_lineage"], ("products.product_family",))

    def test_handle_answer_request_returns_stable_error_payload(self) -> None:
        response = self._post_answer(
            {
                "question": "What is win rate by close month, account segment, sales region, and lifecycle type?",
                "routing": {
                    "compiled_plan_only": True,
                    "restricted_sql_allowed": True,
                },
            },
            expected_status=400,
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["tool_name"], "answer")
        self.assertEqual(response["error"]["error_type"], "validation_error")
        self.assertEqual(response["error"]["error_code"], "invalid_request")
        self.assertIn("compiled_plan_only", response["error"]["message"])

    def test_selected_member_drill_context_flows_through_answer(self) -> None:
        initial = self.service.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("analytics",))

        response = self.service.answer("Go one level deeper", current_analysis_state=initial, selected_member=selected_member, row_limit=5)

        self.assertEqual(response.plan.filters[0].field.field_id, "products.product_family")
        self.assertEqual(response.plan.filters[0].value, "analytics")
        self.assertIn('WHERE "t1"."product_family" = \'analytics\'', response.sql)
        self.assertIn("products_product_name", response.chart_spec.columns)

    def test_embedded_segment_filter_follow_up_is_grounded_in_payload(self) -> None:
        initial = self.service.answer("What is win rate by close month and account segment?", row_limit=20)

        response = self.service.answer(
            "What is win rate by close month for mid market only",
            current_analysis_state=initial.plan,
            row_limit=20,
        )

        self.assertIn(("accounts.segment", "=", "mid_market"), self._filter_signatures(response))
        self.assertIn('WHERE "t1"."segment" = \'mid_market\'', response.sql)
        self.assertTrue(response.rows)
        segment_index = self._column_index(response, "accounts_segment")
        self.assertTrue(all(row[segment_index] == "mid_market" for row in response.rows))
        self.assertEqual(response.chart_spec.chart_type, "line")
        self.assertIsNone(response.chart_spec.series)
        self.assertIn("Active filter: Account Segment = mid_market", response.query_metadata.validation_notes)

    def test_embedded_product_filter_follow_up_is_grounded_in_payload(self) -> None:
        initial = self.service.answer(
            "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
            row_limit=20,
        )

        response = self.service.answer("Show that for analytics only", current_analysis_state=initial.plan, row_limit=20)

        self.assertIn(("products.product_family", "=", "analytics"), self._filter_signatures(response))
        self.assertIn('WHERE "t1"."product_family" = \'analytics\'', response.sql)
        self.assertTrue(response.rows)
        family_index = self._column_index(response, "products_product_family")
        self.assertTrue(all(row[family_index] == "analytics" for row in response.rows))
        self.assertEqual(response.chart_spec.chart_type, "grouped_bar")
        self.assertEqual(response.chart_spec.x, "products_product_family")
        self.assertIn("Active filter: Product Family = analytics", response.query_metadata.validation_notes)

    def test_semantic_resolved_direct_dimensions_flow_through_answer_payload(self) -> None:
        response = self.service.answer("What is the win rate by close month, industry, and region for enterprise?", row_limit=20)

        self.assertIn("accounts.industry", [field.field_id for field in response.plan.dimensions])
        self.assertIn("opportunities.sales_region", [field.field_id for field in response.plan.dimensions])
        self.assertIn(("opportunities.segment", "=", "enterprise"), self._filter_signatures(response))
        self.assertIn('WHERE "t0"."segment" = \'enterprise\'', response.sql)
        self.assertIn("accounts_industry", [column.name for column in response.columns])
        self.assertIn("opportunities_sales_region", [column.name for column in response.columns])
        self.assertIn("accounts", response.query_metadata.involved_entities)
        self.assertIn("opportunities", response.query_metadata.involved_entities)
        self.assertEqual(response.chart_spec.chart_type, "line")

    def test_semantic_resolved_drill_target_flows_through_answer_payload(self) -> None:
        initial = self.service.answer("What is win rate by close month for enterprise?", row_limit=20)

        response = self.service.answer("Go one level deeper to region", current_analysis_state=initial.plan, row_limit=20)

        self.assertIn("opportunities.sales_region", [field.field_id for field in response.plan.dimensions])
        self.assertIn(("opportunities.segment", "=", "enterprise"), self._filter_signatures(response))
        self.assertIn('WHERE "t0"."segment" = \'enterprise\'', response.sql)
        self.assertIn("opportunities_sales_region", [column.name for column in response.columns])
        self.assertEqual(response.chart_spec.chart_type, "line")

    def test_http_answer_round_trip(self) -> None:
        payload = self._post_answer(
            {
                "question": "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
                "row_limit": 4,
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_name"], "answer")
        self.assertEqual(payload["data"]["query_mode"], "compiled_plan")
        self.assertEqual(payload["data"]["routing"]["policy"], "compiled_plan_only")
        self.assertEqual(payload["data"]["chart_spec"]["chart_type"], "grouped_bar")
        self.assertLessEqual(payload["data"]["limit"]["returned_rows"], 4)

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

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["query_mode"], "compiled_plan")
        self.assertEqual(payload["data"]["plan"]["filters"][0]["field"]["entity"], "products")
        self.assertEqual(payload["data"]["plan"]["filters"][0]["field"]["name"], "product_family")
        self.assertEqual(payload["data"]["plan"]["filters"][0]["value"], "analytics")
        self.assertIn("products_product_name", payload["data"]["chart_spec"]["columns"])

    def test_http_answer_round_trip_with_restricted_sql_allowed_flag(self) -> None:
        payload = self._post_answer(
            {
                "question": "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
                "routing": {
                    "compiled_plan_only": False,
                    "restricted_sql_allowed": True,
                },
                "row_limit": 4,
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["routing"]["policy"], "restricted_sql_allowed")
        self.assertEqual(payload["data"]["routing"]["selected_query_mode"], "compiled_plan")

    def test_answer_empty_result_falls_back_to_table(self) -> None:
        initial = self.service.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("not_a_product_family",))

        response = self.service.answer("Go one level deeper", current_analysis_state=initial, selected_member=selected_member, row_limit=5)

        self.assertEqual(response.limit.returned_rows, 0)
        self.assertFalse(response.limit.truncated)
        self.assertEqual(response.chart_spec.chart_type, "table")
        self.assertIn("empty", " ".join(item.message for item in response.warnings).lower())

    def test_answer_over_wide_result_falls_back_to_table(self) -> None:
        service = AnswerService.from_default_model()
        service.chart_specs.max_chart_columns = 3

        response = service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=5)

        self.assertEqual(response.chart_spec.chart_type, "table")
        self.assertIn("over-wide", " ".join(item.message for item in response.warnings))

    def test_restricted_sql_tool_contract_is_serializable(self) -> None:
        response = handle_restricted_sql_request(
            {
                "sql": "SELECT segment, COUNT(DISTINCT opportunity_id) AS opportunity_count "
                "FROM opportunities GROUP BY segment ORDER BY opportunity_count DESC",
                "row_limit": 3,
            },
            service=self.service,
        )

        json.dumps(response)
        self.assertTrue(response["ok"])
        self.assertEqual(response["tool_name"], "restricted_sql")
        self.assertEqual(response["data"]["query_mode"], "restricted_sql")
        self.assertLessEqual(response["data"]["limit"]["returned_rows"], 3)

    def test_http_restricted_sql_round_trip_returns_stable_error_payload(self) -> None:
        payload = self._post_json(
            "/restricted-sql",
            {"sql": "SELECT * FROM missing_entity"},
            expected_status=400,
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["tool_name"], "restricted_sql")
        self.assertEqual(payload["error"]["error_type"], "unsupported_query_shape")
        self.assertEqual(payload["error"]["error_code"], "unsupported_query_shape")

    def _post_answer(self, payload: dict[str, object], expected_status: int = 200) -> dict[str, object]:
        return self._post_json("/answer", payload, expected_status=expected_status)

    def _filter_signatures(self, response) -> list[tuple[str, str, object]]:
        return [(filter_.field.field_id, filter_.operator, filter_.value) for filter_ in response.plan.filters]

    def _column_index(self, response, column_name: str) -> int:
        for index, column in enumerate(response.columns):
            if column.name == column_name:
                return index
        raise AssertionError(f"Column not found: {column_name}")

    def _post_json(self, path: str, payload: dict[str, object], expected_status: int = 200) -> dict[str, object]:
        PlanningRequestHandler.answer_service = self.service
        PlanningRequestHandler.planner = self.service.planner
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, expected_status)
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                self.assertEqual(exc.code, expected_status)
                body = exc.read().decode("utf-8")
                exc.close()
                return json.loads(body)
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

    def test_restricted_sql_canonicalizes_indexed_filter_values(self) -> None:
        for segment_value in ("enterprise", "Enterprise", "ENTERPRISE"):
            with self.subTest(segment_value=segment_value):
                result = self.gateway.execute_restricted_sql(
                    "SELECT implementation_complexity, support_tier_requested, "
                    "COUNT(DISTINCT opportunity_id) AS opportunity_count "
                    f"FROM opportunities WHERE segment = '{segment_value}' "
                    "GROUP BY implementation_complexity, support_tier_requested "
                    "ORDER BY opportunity_count DESC",
                    row_limit=20,
                )

                self.assertIn("segment = 'enterprise'", result.sql)
                self.assertGreater(len(result.result.rows), 0)
                self.assertEqual(
                    result.result.columns,
                    ("implementation_complexity", "support_tier_requested", "opportunity_count"),
                )

    def test_restricted_sql_rejects_unknown_indexed_filter_value(self) -> None:
        with self.assertRaises(RestrictedSqlValidationError):
            self.gateway.execute_restricted_sql(
                "SELECT implementation_complexity, support_tier_requested, "
                "COUNT(DISTINCT opportunity_id) AS opportunity_count "
                "FROM opportunities WHERE segment = 'Enterprise Plus' "
                "GROUP BY implementation_complexity, support_tier_requested",
                row_limit=20,
            )

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

    def test_heatmap_for_opportunity_complexity_and_support_tier_question(self) -> None:
        plan = replace(
            self.plan,
            question="Show opportunity count by implementation complexity and requested support tier for enterprise deals.",
            chart_intent=ChartIntent(chart_type="heatmap", reason="test"),
        )
        columns = (
            ResultColumn("implementation_complexity", "Implementation Complexity", "string", ("opportunities.implementation_complexity",), "dimension"),
            ResultColumn("support_tier_requested", "Requested Support Tier", "string", ("opportunities.support_tier_requested",), "dimension"),
            ResultColumn("opportunity_count", "Opportunities", "number", ("opportunities.opportunity_count",), "measure"),
        )
        rows = (("high", "enterprise", 12), ("medium", "standard", 8))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "heatmap")
        self.assertEqual(chart.x, "implementation_complexity")
        self.assertEqual(chart.series, "support_tier_requested")
        self.assertEqual(chart.y, ("opportunity_count",))
        self.assertIn("two category dimensions and one measure", chart.chart_choice_explanation)

    def test_heatmap_for_line_item_pricing_model_and_line_role_question(self) -> None:
        plan = replace(
            self.plan,
            question="For analytics products, show line item count by pricing model and line role.",
            chart_intent=ChartIntent(chart_type="heatmap", reason="test"),
        )
        columns = (
            ResultColumn("pricing_model", "Pricing Model", "string", ("products.pricing_model",), "dimension"),
            ResultColumn("line_role", "Line Role", "string", ("opportunity_line_items.line_role",), "dimension"),
            ResultColumn("line_item_count", "Line Items", "number", ("opportunity_line_items.line_item_count",), "measure"),
        )
        rows = (("subscription", "base", 4), ("transactional", "add_on", 7))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "heatmap")
        self.assertEqual(chart.x, "pricing_model")
        self.assertEqual(chart.series, "line_role")
        self.assertEqual(chart.y, ("line_item_count",))

    def test_heatmap_with_extra_dimensions_falls_back_to_table(self) -> None:
        plan = replace(
            self.plan,
            question="Show stale mixed win rate payload as a heatmap.",
            chart_intent=ChartIntent(chart_type="heatmap", reason="test"),
        )
        columns = (
            ResultColumn("sales_region", "Deal Sales Region", "string", ("opportunities.sales_region",), "dimension"),
            ResultColumn("pricing_model", "Pricing Model", "string", ("products.pricing_model",), "dimension"),
            ResultColumn("line_role", "Line Role", "string", ("opportunity_line_items.line_role",), "dimension"),
            ResultColumn("opportunities_win_rate", "Win Rate", "number", ("opportunities.win_rate",), "measure"),
        )
        rows = (("na", "subscription", "base", 0.42),)

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "table")
        self.assertIn("exactly two dimensions and one measure", " ".join(chart.warnings))

    def test_heatmap_for_contract_billing_frequency_and_currency_question(self) -> None:
        plan = replace(
            self.plan,
            question="Show active contract count by billing frequency and currency.",
            chart_intent=ChartIntent(chart_type="heatmap", reason="test"),
        )
        columns = (
            ResultColumn("billing_frequency", "Billing Frequency", "string", ("contracts.billing_frequency",), "dimension"),
            ResultColumn("currency_code", "Currency", "string", ("contracts.currency_code",), "dimension"),
            ResultColumn("active_contract_count", "Active Contracts", "number", ("contracts.active_contract_count",), "measure"),
        )
        rows = (("monthly", "USD", 10), ("annual", "USD", 6))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "heatmap")
        self.assertEqual(chart.x, "billing_frequency")
        self.assertEqual(chart.series, "currency_code")
        self.assertEqual(chart.y, ("active_contract_count",))

    def test_heatmap_for_win_rate_by_segment_and_region_question(self) -> None:
        plan = replace(
            self.plan,
            question="Where is win rate strongest by deal segment and sales region?",
            chart_intent=ChartIntent(chart_type="heatmap", reason="test"),
        )
        columns = (
            ResultColumn("segment", "Deal Segment", "string", ("opportunities.segment",), "dimension"),
            ResultColumn("sales_region", "Deal Sales Region", "string", ("opportunities.sales_region",), "dimension"),
            ResultColumn("win_rate", "Win Rate", "number", ("opportunities.win_rate",), "measure"),
        )
        rows = (("enterprise", "apac", 0.52), ("mid_market", "na", 0.47))

        chart = self.generator.generate(plan, columns, rows)

        self.assertEqual(chart.chart_type, "heatmap")
        self.assertEqual(chart.x, "segment")
        self.assertEqual(chart.series, "sales_region")
        self.assertEqual(chart.y, ("win_rate",))


if __name__ == "__main__":
    unittest.main()
