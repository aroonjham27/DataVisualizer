from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .answer import AnswerService
from .contracts import (
    ChatRequest,
    ChatResponse,
    ConversationState,
    RoutingControls,
    ToolCallTrace,
)
from .errors import RequestValidationError
from .llm_client import DisabledLlmClient, LlmClient, LlmResponse, OpenAiCompatibleLlmClient
from .tool_registry import ToolRegistry, ToolDefinition


class ChatOrchestrator:
    def __init__(self, answer_service: AnswerService, llm_client: LlmClient, max_iterations: int = 4):
        self.answer_service = answer_service
        self.llm_client = llm_client
        self.max_iterations = max_iterations
        self.tools = ToolRegistry(answer_service)

    @classmethod
    def from_env(cls, model_path: str | Path | None = None) -> "ChatOrchestrator":
        answer_service = AnswerService.from_model_path(model_path)
        try:
            llm_client = OpenAiCompatibleLlmClient.from_env()
            max_iterations = llm_client.config.default_max_iterations
        except Exception as exc:  # noqa: BLE001
            llm_client = DisabledLlmClient(str(exc))
            max_iterations = 4
        return cls(answer_service=answer_service, llm_client=llm_client, max_iterations=max_iterations)

    def chat_request(self, request: ChatRequest) -> ChatResponse:
        if not request.messages:
            raise RequestValidationError("Chat request must include at least one message.")
        latest_user_message = self._latest_user_message(request)
        state = request.conversation_state or ConversationState()
        active_state = self._merge_state_with_request(state, request)
        tool_definitions = self.tools.tools_for_chat(latest_user_message, request.routing)
        llm_messages = self._llm_messages(request, active_state)
        llm_response = self.llm_client.generate(
            llm_messages,
            tools=[tool.to_openai_tool() for tool in tool_definitions],
            tool_choice="required",
        )
        tool_call = self._require_single_tool_call(llm_response, tool_definitions)
        tool_args = self._enrich_tool_arguments(tool_call.name, tool_call.arguments, request, active_state, latest_user_message)
        tool_result = self.tools.execute(tool_call.name, tool_args)
        updated_state = self._updated_state(active_state, request, tool_call.name, tool_result)
        final_message = self._final_assistant_message(llm_messages, llm_response, tool_call, tool_result)
        return ChatResponse(
            tool_name="chat",
            assistant_message=final_message,
            executed_tool_name=tool_call.name,
            tool_result=tool_result,
            conversation_state=updated_state,
            tool_trace=(ToolCallTrace(tool_name=tool_call.name, arguments=tool_args, result_ok=bool(tool_result.get("ok"))),),
        )

    def registered_tools(self, latest_user_message: str, routing: RoutingControls) -> tuple[ToolDefinition, ...]:
        return self.tools.tools_for_chat(latest_user_message, routing)

    def _latest_user_message(self, request: ChatRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content
        raise RequestValidationError("Chat request must include at least one user message.")

    def _merge_state_with_request(self, state: ConversationState, request: ChatRequest) -> ConversationState:
        return ConversationState(
            current_analysis_state=state.current_analysis_state,
            selected_member=request.selected_member or state.selected_member,
            last_tool_name=state.last_tool_name,
            last_query_mode=state.last_query_mode,
            last_chart_type=state.last_chart_type,
            last_row_limit=state.last_row_limit,
        )

    def _llm_messages(self, request: ChatRequest, state: ConversationState) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt(state, request.routing),
            }
        ]
        for message in request.messages:
            messages.append({"role": message.role, "content": message.content})
        return messages

    def _system_prompt(self, state: ConversationState, routing: RoutingControls) -> str:
        state_bits = []
        if state.current_analysis_state is not None:
            state_bits.append(f"Current analysis question: {state.current_analysis_state.question}")
        if state.selected_member is not None:
            state_bits.append(f"Selected member: {state.selected_member.field.field_id}={list(state.selected_member.values)}")
        if state.last_chart_type is not None:
            state_bits.append(f"Last chart type: {state.last_chart_type}")
        state_text = "\n".join(state_bits) if state_bits else "No prior analysis state is available."
        return (
            "You are the analytics orchestrator for a governed BI backend.\n"
            "Default to the answer tool for normal analytics.\n"
            "Use restricted_sql only when it is explicitly available and clearly justified by a SQL-specific request.\n"
            "For conversational follow-ups, reuse the current analysis state when helpful.\n"
            "In final responses, describe filters only when they appear in the returned tool result's plan.filters.\n"
            "After a governed tool result is available, summarize that completed result and do not request another tool call.\n"
            "For 'top 5', set row_limit to 5 and reuse the current plan.\n"
            "For 'show as table', set chart_type_override to table and reuse the current plan.\n"
            f"Routing policy: {routing.policy}.\n"
            f"{state_text}"
        )

    def _require_single_tool_call(self, response: LlmResponse, tools: tuple[ToolDefinition, ...]) -> Any:
        available_names = {tool.name for tool in tools}
        tool_calls = response.message.tool_calls
        if len(tool_calls) != 1:
            raise RequestValidationError("LLM must return exactly one tool call for chat orchestration.")
        tool_call = tool_calls[0]
        if tool_call.name not in available_names:
            raise RequestValidationError(f"LLM selected an unregistered tool: {tool_call.name}")
        return tool_call

    def _enrich_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        request: ChatRequest,
        state: ConversationState,
        latest_user_message: str,
    ) -> dict[str, Any]:
        enriched = dict(arguments)
        if tool_name == "answer":
            enriched["question"] = latest_user_message
            if request.semantic_model_path is not None:
                enriched.setdefault("semantic_model_path", request.semantic_model_path)
            enriched.setdefault(
                "routing",
                {
                    "compiled_plan_only": request.routing.compiled_plan_only,
                    "restricted_sql_allowed": request.routing.restricted_sql_allowed,
                },
            )
            if state.current_analysis_state is not None:
                enriched.setdefault("current_analysis_state", state.current_analysis_state.to_dict())
            if state.selected_member is not None:
                enriched.setdefault(
                    "selected_member",
                    {
                        "field": state.selected_member.field.__dict__,
                        "values": list(state.selected_member.values),
                        "source": state.selected_member.source,
                    },
                )
            normalized = latest_user_message.lower().strip()
            if "reuse_current_plan" in enriched:
                enriched["reuse_current_plan"] = False
            if normalized in {"top 5", "top five"} and state.current_analysis_state is not None:
                enriched["reuse_current_plan"] = True
                enriched.setdefault("row_limit", 5)
            if normalized == "show as table" and state.current_analysis_state is not None:
                enriched["reuse_current_plan"] = True
                enriched.setdefault("chart_type_override", "table")
        elif tool_name == "restricted_sql":
            if request.semantic_model_path is not None:
                enriched.setdefault("semantic_model_path", request.semantic_model_path)
        return enriched

    def _updated_state(
        self,
        state: ConversationState,
        request: ChatRequest,
        tool_name: str,
        tool_result: dict[str, Any],
    ) -> ConversationState:
        if not tool_result.get("ok"):
            return state
        data = tool_result["data"]
        if tool_name == "answer":
            from .contracts import AnalysisPlan, ConversationState as ConversationStateContract, DrillSelection, PlannedField  # local import to avoid cycle

            selected_member = state.selected_member
            drill_payload = data["plan"].get("drill")
            if drill_payload and drill_payload.get("selected_member"):
                selected_payload = drill_payload["selected_member"]
                selected_member = DrillSelection(
                    field=PlannedField(**selected_payload["field"]),
                    values=tuple(selected_payload.get("values", ())),
                    source=selected_payload.get("source", "visual_member"),
                )
            return ConversationStateContract(
                current_analysis_state=AnalysisPlan.from_dict(data["plan"]),
                selected_member=selected_member,
                last_tool_name="answer",
                last_query_mode=data["query_mode"],
                last_chart_type=data["chart_spec"]["chart_type"],
                last_row_limit=data["limit"]["row_limit"],
            )
        return ConversationState(
            current_analysis_state=state.current_analysis_state,
            selected_member=state.selected_member,
            last_tool_name=tool_name,
            last_query_mode=data["query_mode"],
            last_chart_type=state.last_chart_type,
            last_row_limit=data["limit"]["row_limit"],
        )

    def _final_assistant_message(
        self,
        base_messages: list[dict[str, Any]],
        llm_response: LlmResponse,
        tool_call: Any,
        tool_result: dict[str, Any],
    ) -> str:
        if not tool_result.get("ok"):
            return tool_result.get("error", {}).get("message", "The tool call failed.")
        follow_up_messages = list(base_messages)
        follow_up_messages.append(
            {
                "role": "assistant",
                "content": llm_response.message.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments),
                        },
                    }
                ],
            }
        )
        follow_up_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": json.dumps(tool_result),
            }
        )
        follow_up_messages.append(
            {
                "role": "user",
                "content": (
                    "Summarize the completed governed tool result for the user. "
                    "Do not call another tool. Do not describe filters unless they appear in plan.filters."
                ),
            }
        )
        final = self.llm_client.generate(follow_up_messages, tools=None, tool_choice=None)
        if final.message.tool_calls:
            return self._fallback_summary(tool_result)
        if final.message.content.strip():
            return final.message.content.strip()
        return self._fallback_summary(tool_result)

    def _fallback_summary(self, tool_result: dict[str, Any]) -> str:
        data = tool_result.get("data", {})
        if tool_result.get("tool_name") == "answer":
            return f"Returned {data.get('limit', {}).get('returned_rows', 0)} rows using {data.get('query_mode', 'compiled_plan')}."
        if tool_result.get("tool_name") == "restricted_sql":
            return f"Executed governed restricted SQL and returned {data.get('limit', {}).get('returned_rows', 0)} rows."
        return "Completed the requested tool call."
