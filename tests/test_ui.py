from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from datavisualizer.answer import AnswerService
from datavisualizer.api import PlanningRequestHandler
from datavisualizer.chat_orchestrator import ChatOrchestrator
from datavisualizer.contracts import ChartSpec, ResultColumn, RoutingControls
from datavisualizer.llm_client import FakeLlmClient, LlmAssistantMessage, LlmResponse, LlmToolCall
from datavisualizer.ui_contract import build_chart_view_model, build_inspector_view_model, build_selected_member, drill_selection_payload


class UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = AnswerService.from_default_model()

    def test_grouped_bar_answer_builds_chart_view_model(self) -> None:
        response = self.service.answer(
            "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
            row_limit=4,
        )

        view_model = build_chart_view_model(response.chart_spec, response.columns, response.rows)

        self.assertEqual(view_model["chart_type"], "grouped_bar")
        self.assertTrue(view_model["bars"])
        self.assertEqual(view_model["x"], response.chart_spec.x)

    def test_grouped_bar_answer_builds_selected_member_from_x_dimension(self) -> None:
        response = self.service.answer(
            "How do quoted discount rates and annualized quote amounts vary by product family and line role?",
            row_limit=4,
        )

        selection = build_selected_member(response.chart_spec, response.columns, response.rows, 0)
        payload = drill_selection_payload(response.chart_spec, response.columns, response.rows, 0)

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.field.field_id, "products.product_family")
        self.assertEqual(payload["field"]["entity"], "products")
        self.assertEqual(payload["field"]["name"], "product_family")
        self.assertEqual(payload["source"], "visual_member")

    def test_line_chart_prefers_dimension_series_for_drill_selection(self) -> None:
        chart_spec = ChartSpec(chart_type="line", title="Win Rate", x="close_month", y=("win_rate",), series="segment")
        columns = (
            ResultColumn("close_month", "Close Month", "date", ("opportunities.close_date",), "time"),
            ResultColumn("segment", "Segment", "string", ("accounts.segment",), "dimension"),
            ResultColumn("win_rate", "Win Rate", "number", ("opportunities.win_rate",), "measure"),
        )
        rows = (
            ("2025-01-01", "enterprise", 0.5),
            ("2025-02-01", "enterprise", 0.6),
        )

        selection = build_selected_member(chart_spec, columns, rows, 0)

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.field.field_id, "accounts.segment")
        self.assertEqual(selection.values, ("enterprise",))

    def test_line_chart_view_model_dedupes_and_sorts_time_axis(self) -> None:
        chart_spec = ChartSpec(chart_type="line", title="Win Rate", x="close_month", y=("win_rate",), series="segment")
        columns = (
            ResultColumn("close_month", "Close Month", "date", ("opportunities.close_date",), "time"),
            ResultColumn("segment", "Segment", "string", ("accounts.segment",), "dimension"),
            ResultColumn("win_rate", "Win Rate", "number", ("opportunities.win_rate",), "measure"),
        )
        rows = (
            ("2025-02-01", "mid_market", 0.6),
            ("2025-01-01", "mid_market", 0.5),
            ("2025-02-01", "mid_market", 0.7),
        )

        view_model = build_chart_view_model(chart_spec, columns, rows)

        self.assertEqual(view_model["x_values"], ("2025-01-01", "2025-02-01"))
        self.assertEqual(len(view_model["lines"]), 1)
        self.assertEqual([point["x"] for point in view_model["lines"][0]["points"]], ["2025-01-01", "2025-02-01"])

    def test_inspector_view_model_surfaces_filters_sql_and_entities(self) -> None:
        initial = self.service.answer("What is win rate by close month and account segment?", row_limit=20)
        response = self.service.answer(
            "What is win rate by close month for mid market only",
            current_analysis_state=initial.plan,
            row_limit=20,
        )

        inspector = build_inspector_view_model(response.to_dict())

        self.assertEqual(inspector["query_mode"], "compiled_plan")
        self.assertIn("read_csv_auto", inspector["sql"])
        self.assertEqual(inspector["applied_filters"][0]["text"], "Account Segment = mid_market")
        self.assertIn("accounts", inspector["involved_entities"])
        self.assertEqual(inspector["limit"]["row_limit"], 20)
        self.assertIsInstance(inspector["limit"]["truncated"], bool)
        self.assertEqual(inspector["chart"]["chart_type"], "line")
        self.assertEqual(inspector["analysis_plan"]["primary_entity"], "opportunities")

    def test_inspector_groups_warnings_and_fallback_reasons(self) -> None:
        service = AnswerService.from_default_model()
        service.chart_specs.max_chart_columns = 3
        response = service.answer("What is win rate by close month, account segment, sales region, and lifecycle type?", row_limit=5)

        inspector = build_inspector_view_model(response.to_dict())

        self.assertEqual(response.chart_spec.chart_type, "table")
        self.assertTrue(inspector["warning_groups"]["chart"])
        self.assertTrue(inspector["warning_groups"]["fallback"])
        self.assertIn("over-wide", " ".join(inspector["chart"]["fallback_reasons"]))
        self.assertTrue(inspector["warning_groups"]["query"])

    def test_inspector_groups_plan_and_routing_notes(self) -> None:
        response = self.service.answer("What is win rate by sales region?", row_limit=5)
        routed = self.service.answer(
            "What is win rate by close month and account segment?",
            row_limit=5,
            routing=RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
        )

        plan_inspector = build_inspector_view_model(response.to_dict())
        routed_inspector = build_inspector_view_model(routed.to_dict())

        self.assertTrue(plan_inspector["warning_groups"]["plan"])
        self.assertTrue(routed_inspector["warning_groups"]["routing"])


class UiHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        answer_service = AnswerService.from_default_model()
        fake_client = FakeLlmClient(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Chat response ready.")),
            ]
        )
        PlanningRequestHandler.answer_service = answer_service
        PlanningRequestHandler.planner = answer_service.planner
        PlanningRequestHandler.chat_orchestrator = ChatOrchestrator(answer_service, fake_client)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_root_serves_chat_ui_shell(self) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}/", timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn('id="chat-thread"', body)
        self.assertIn('id="chat-form"', body)
        self.assertIn('/static/app.js', body)

    def test_static_assets_are_served(self) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}/static/app.js", timeout=5) as response:
            script = response.read().decode("utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}/static/styles.css", timeout=5) as response:
            styles = response.read().decode("utf-8")

        self.assertIn("sendUserMessage", script)
        self.assertIn("buildSelectedMember", script)
        self.assertIn("Active Filters", script)
        self.assertIn("What did the system do?", script)
        self.assertIn("SQL Executed", script)
        self.assertIn("Fallback explanations", script)
        self.assertIn(".chat-thread", styles)
        self.assertIn(".inspector", styles)
        self.assertIn(".sql-block", styles)

    def test_ui_still_integrates_through_chat_contract(self) -> None:
        payload = json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "What is win rate by close month and account segment?",
                    }
                ]
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))

        self.assertTrue(body["ok"])
        self.assertEqual(body["tool_name"], "chat")
        self.assertIn("assistant_message", body["data"])
        self.assertIn("tool_result", body["data"])
        self.assertIn("conversation_state", body["data"])
        inspector = build_inspector_view_model(body["data"]["tool_result"]["data"])
        self.assertEqual(inspector["query_mode"], "compiled_plan")
        self.assertIn("sql", inspector)


if __name__ == "__main__":
    unittest.main()
