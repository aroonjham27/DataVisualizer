from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from unittest.mock import patch

from datavisualizer.answer import AnswerService
from datavisualizer.api import ChatTraceLog, PlanningRequestHandler, handle_chat_request
from datavisualizer.chat_orchestrator import ChatOrchestrator
from datavisualizer.contracts import AnalysisPlan, ChatMessage, ChatRequest, ConversationState, RoutingControls
from datavisualizer.llm_client import (
    FakeLlmClient,
    LlmAssistantMessage,
    LlmResponse,
    LlmToolCall,
    OpenAiCompatibleLlmClient,
    ProviderConfig,
)
from datavisualizer.tool_registry import ToolDefinition, ToolRegistry


class DeterministicAnswerOnlyTools:
    def __init__(self, answer_service: AnswerService):
        self.answer_service = answer_service
        self.answer_tool = ToolDefinition(
            name="answer",
            description="Test-only governed analytics tool.",
            input_schema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
            output_schema={"type": "object"},
        )

    def tools_for_chat(self, latest_user_message: str, routing: RoutingControls) -> tuple[ToolDefinition, ...]:
        return (self.answer_tool,)

    def execute(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        if tool_name != "answer":
            raise AssertionError(f"Unexpected tool: {tool_name}")
        current_state = None
        if isinstance(arguments.get("current_analysis_state"), dict):
            current_state = AnalysisPlan.from_dict(arguments["current_analysis_state"])
        plan = self.answer_service.planner.plan(str(arguments.get("question", "")), current_state=current_state)
        rows = [{"example": "value"}]
        return {
            "ok": True,
            "tool_name": "answer",
            "data": {
                "plan": plan.to_dict(),
                "query_mode": "compiled_plan",
                "compiled_sql": "SELECT 1 AS example",
                "rows": rows,
                "columns": ("example",),
                "chart_spec": {"chart_type": "table"},
                "limit": {"row_limit": 100, "returned_rows": len(rows), "truncated": False},
                "warnings": (),
            },
            "error": None,
        }


class ProviderConfigTests(unittest.TestCase):
    def test_provider_config_uses_openrouter_fallbacks(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://openrouter.example/api/v1",
                "OPENROUTER_MODEL": "anthropic/test-model",
                "TIMEOUT_SECONDS": "11",
                "MAX_ITERATIONS": "7",
            },
            clear=False,
        ):
            config = ProviderConfig.from_env()

        self.assertEqual(config.base_url, "https://openrouter.example/api/v1")
        self.assertEqual(config.model, "anthropic/test-model")
        self.assertEqual(config.timeout_seconds, 11)
        self.assertEqual(config.default_max_iterations, 7)

    def test_provider_config_requires_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception):
                ProviderConfig.from_env()


class ToolRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ToolRegistry(AnswerService.from_default_model())

    def test_registry_keeps_answer_as_default_tool(self) -> None:
        tools = self.registry.tools_for_chat(
            "What is win rate by close month, account segment, sales region, and lifecycle type?",
            RoutingControls(),
        )

        self.assertEqual([tool.name for tool in tools], ["answer"])

    def test_registry_only_offers_restricted_sql_when_justified(self) -> None:
        tools = self.registry.tools_for_chat(
            "Write restricted SQL to count opportunities by segment",
            RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
        )

        self.assertEqual([tool.name for tool in tools], ["answer", "restricted_sql"])
        self.assertIn("question", self.registry.answer_tool.input_schema["properties"])
        self.assertIn("sql", self.registry.restricted_sql_tool.input_schema["properties"])


class ChatOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.answer_service = AnswerService.from_default_model()

    def _scripted_orchestrator(self, responses: list[LlmResponse]) -> ChatOrchestrator:
        return ChatOrchestrator(self.answer_service, FakeLlmClient(responses), max_iterations=4)

    def _scripted_orchestrator_with_deterministic_tools(self, responses: list[LlmResponse]) -> ChatOrchestrator:
        orchestrator = self._scripted_orchestrator(responses)
        orchestrator.tools = DeterministicAnswerOnlyTools(self.answer_service)
        return orchestrator

    def test_chat_executes_answer_tool_for_normal_question(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Win rate by month is ready.")),
            ]
        )

        response = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month, account segment, sales region, and lifecycle type?"),))
        )

        self.assertEqual(response.executed_tool_name, "answer")
        self.assertEqual(response.tool_result["tool_name"], "answer")
        self.assertEqual(response.conversation_state.last_tool_name, "answer")
        self.assertEqual(response.conversation_state.last_query_mode, "compiled_plan")
        self.assertIsNotNone(response.conversation_state.current_analysis_state)

    def test_chat_carries_state_for_go_deeper_follow_up(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Drilled one level deeper.")),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="How do quoted discount rates and annualized quote amounts vary by product family and line role?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="Go one level deeper"),),
                conversation_state=first.conversation_state,
            )
        )

        self.assertEqual(second.executed_tool_name, "answer")
        self.assertIn("products.product_name", [field.field_id for field in second.conversation_state.current_analysis_state.dimensions])

    def test_final_turn_tool_call_falls_back_without_losing_tool_result(self) -> None:
        orchestrator = self._scripted_orchestrator_with_deterministic_tools(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
            ]
        )

        response = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),))
        )

        self.assertEqual(response.executed_tool_name, "answer")
        self.assertEqual(response.assistant_message, "Returned 1 rows using compiled_plan.")
        self.assertTrue(response.tool_result["ok"])
        self.assertEqual(response.tool_result["data"]["query_mode"], "compiled_plan")
        self.assertIn("chart_spec", response.tool_result["data"])
        self.assertIn("rows", response.tool_result["data"])
        final_prompt = orchestrator.llm_client.calls[1]["messages"][-1]["content"]
        self.assertIn("Do not call another tool", final_prompt)

    def test_go_deeper_final_turn_tool_call_falls_back_successfully(self) -> None:
        orchestrator = self._scripted_orchestrator_with_deterministic_tools(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-3", "answer", {}),))),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="How do quoted discount rates and annualized quote amounts vary by product family and line role?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="Go one level deeper"),),
                conversation_state=first.conversation_state,
            )
        )

        self.assertEqual(second.executed_tool_name, "answer")
        self.assertEqual(second.assistant_message, "Returned 1 rows using compiled_plan.")
        self.assertTrue(second.tool_result["ok"])
        self.assertIn("products.product_name", [field.field_id for field in second.conversation_state.current_analysis_state.dimensions])
        self.assertIn("chart_spec", second.tool_result["data"])

    def test_drill_down_follow_up_ignores_model_reuse_current_plan(self) -> None:
        orchestrator = self._scripted_orchestrator_with_deterministic_tools(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(
                    LlmAssistantMessage(
                        "",
                        (
                            LlmToolCall(
                                "call-2",
                                "answer",
                                {
                                    "question": "What is win rate by close month for enterprise?",
                                    "reuse_current_plan": True,
                                },
                            ),
                        ),
                    )
                ),
                LlmResponse(LlmAssistantMessage("Drilled down to region.")),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month for enterprise?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="can you drill down to region level?"),),
                conversation_state=first.conversation_state,
            )
        )

        self.assertIn("opportunities.sales_region", [field.field_id for field in second.conversation_state.current_analysis_state.dimensions])
        self.assertEqual(second.tool_trace[0].arguments["question"], "can you drill down to region level?")
        self.assertFalse(second.tool_trace[0].arguments["reuse_current_plan"])

    def test_chat_supports_top_five_follow_up(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Showing the top 5 rows.")),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="top 5"),), conversation_state=first.conversation_state)
        )

        self.assertEqual(second.tool_result["data"]["limit"]["row_limit"], 5)

    def test_chat_supports_show_as_table_follow_up(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Showing the table view.")),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="How do quoted discount rates and annualized quote amounts vary by product family and line role?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="show as table"),), conversation_state=first.conversation_state)
        )

        self.assertEqual(second.tool_result["data"]["chart_spec"]["chart_type"], "table")

    def test_chat_supports_just_enterprise_follow_up(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Initial answer ready.")),
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-2", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Filtered to enterprise.")),
            ]
        )
        first = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),))
        )

        second = orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="just enterprise"),), conversation_state=first.conversation_state)
        )

        filters = second.conversation_state.current_analysis_state.filters
        self.assertTrue(any(item.value == "enterprise" for item in filters))

    def test_chat_keeps_compiled_plan_default_when_restricted_sql_allowed(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Compiled plan stayed selected.")),
            ]
        )

        response = orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),),
                routing=RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
            )
        )

        self.assertEqual(response.executed_tool_name, "answer")
        self.assertEqual(response.tool_result["data"]["query_mode"], "compiled_plan")

    def test_chat_can_execute_restricted_sql_when_clearly_requested(self) -> None:
        orchestrator = self._scripted_orchestrator(
            [
                LlmResponse(
                    LlmAssistantMessage(
                        "",
                        (
                            LlmToolCall(
                                "call-1",
                                "restricted_sql",
                                {
                                    "sql": "SELECT segment, COUNT(DISTINCT opportunity_id) AS opportunity_count "
                                    "FROM opportunities GROUP BY segment ORDER BY opportunity_count DESC"
                                },
                            ),
                        ),
                    )
                ),
                LlmResponse(LlmAssistantMessage("SQL result ready.")),
            ]
        )

        response = orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="Write restricted SQL to count opportunities by segment"),),
                routing=RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
            )
        )

        self.assertEqual(response.executed_tool_name, "restricted_sql")
        self.assertEqual(response.tool_result["data"]["query_mode"], "restricted_sql")


class ChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        fake_client = FakeLlmClient(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Chat response ready.")),
            ]
        )
        self.orchestrator = ChatOrchestrator(AnswerService.from_default_model(), fake_client)

    def test_handle_chat_request_returns_chat_envelope(self) -> None:
        response = handle_chat_request(
            {"messages": [{"role": "user", "content": "What is win rate by close month and account segment?"}]},
            orchestrator=self.orchestrator,
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["tool_name"], "chat")
        self.assertEqual(response["data"]["executed_tool_name"], "answer")

    def test_http_chat_round_trip(self) -> None:
        PlanningRequestHandler.chat_orchestrator = self.orchestrator
        PlanningRequestHandler.answer_service = self.orchestrator.answer_service
        PlanningRequestHandler.planner = self.orchestrator.answer_service.planner
        PlanningRequestHandler.dev_chat_trace_enabled = False
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/chat",
                data=json.dumps({"messages": [{"role": "user", "content": "What is win rate by close month and account segment?"}]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_name"], "chat")
        self.assertEqual(payload["data"]["executed_tool_name"], "answer")

    def test_dev_chat_trace_endpoint_is_disabled_by_default(self) -> None:
        PlanningRequestHandler.dev_chat_trace_enabled = False
        PlanningRequestHandler.chat_trace_log = ChatTraceLog(limit=2)
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/dev/chat-trace", timeout=5)
                self.fail("Expected disabled trace endpoint to return 404.")
            except HTTPError as exc:
                status_code = exc.code
                exc.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(status_code, 404)

    def test_dev_chat_trace_captures_chat_envelopes_without_secrets(self) -> None:
        fake_client = FakeLlmClient(
            [
                LlmResponse(LlmAssistantMessage("", (LlmToolCall("call-1", "answer", {}),))),
                LlmResponse(LlmAssistantMessage("Trace response ready.")),
            ]
        )
        orchestrator = ChatOrchestrator(AnswerService.from_default_model(), fake_client)
        orchestrator.tools = DeterministicAnswerOnlyTools(orchestrator.answer_service)
        PlanningRequestHandler.chat_orchestrator = orchestrator
        PlanningRequestHandler.answer_service = orchestrator.answer_service
        PlanningRequestHandler.planner = orchestrator.answer_service.planner
        PlanningRequestHandler.dev_chat_trace_enabled = True
        PlanningRequestHandler.chat_trace_log = ChatTraceLog(limit=1)
        server = ThreadingHTTPServer(("127.0.0.1", 0), PlanningRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/chat",
                data=json.dumps(
                    {
                        "messages": [{"role": "user", "content": "What is win rate by close month for enterprise?"}],
                        "api_key": "should-not-appear",
                        "accessToken": "also-should-not-appear",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                chat_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/dev/chat-trace", timeout=5) as response:
                trace_payload = json.loads(response.read().decode("utf-8"))
        finally:
            PlanningRequestHandler.dev_chat_trace_enabled = False
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(chat_payload["ok"])
        self.assertTrue(trace_payload["ok"])
        entries = trace_payload["data"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "/chat")
        self.assertEqual(entries[0]["request"]["api_key"], "[redacted]")
        self.assertEqual(entries[0]["request"]["accessToken"], "[redacted]")
        self.assertEqual(entries[0]["request"]["messages"][0]["content"], "What is win rate by close month for enterprise?")
        self.assertTrue(entries[0]["response"]["ok"])


LIVE_SMOKE_ENABLED = (
    os.getenv("DATAVISUALIZER_RUN_LIVE_SMOKE") == "1"
    and bool(os.getenv("OPENROUTER_API_KEY"))
    and bool(os.getenv("OPENROUTER_MODEL") or os.getenv("ANTHROPIC_MODEL"))
)


@unittest.skipUnless(LIVE_SMOKE_ENABLED, "Live LLM smoke tests require DATAVISUALIZER_RUN_LIVE_SMOKE=1 and model credentials.")
class LiveChatSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ChatOrchestrator.from_env()

    def test_live_normal_analytics_question(self) -> None:
        response = self.orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),))
        )

        self.assertEqual(response.executed_tool_name, "answer")
        self.assertEqual(response.tool_result["data"]["query_mode"], "compiled_plan")

    def test_live_drill_follow_up(self) -> None:
        first = self.orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="How do quoted discount rates and annualized quote amounts vary by product family and line role?"),))
        )
        second = self.orchestrator.chat_request(
            ChatRequest(messages=(ChatMessage(role="user", content="go deeper"),), conversation_state=first.conversation_state)
        )

        self.assertEqual(second.executed_tool_name, "answer")
        self.assertIsNotNone(second.conversation_state.current_analysis_state)

    def test_live_restricted_sql_allowed_but_compiled_plan_chosen(self) -> None:
        response = self.orchestrator.chat_request(
            ChatRequest(
                messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),),
                routing=RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True),
            )
        )

        self.assertEqual(response.executed_tool_name, "answer")
        self.assertEqual(response.tool_result["data"]["query_mode"], "compiled_plan")


if __name__ == "__main__":
    unittest.main()
