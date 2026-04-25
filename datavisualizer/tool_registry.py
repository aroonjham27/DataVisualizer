from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .answer import AnswerService
from .contracts import AnswerRequest, RestrictedSqlRequest, RoutingControls
from .errors import success_envelope


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    def __init__(self, answer_service: AnswerService):
        self.answer_service = answer_service
        self.answer_tool = ToolDefinition(
            name="answer",
            description="Default governed analytics tool. Use this first for normal analytics questions and conversation follow-ups.",
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "current_analysis_state": {"type": "object"},
                    "selected_member": {"type": "object"},
                    "row_limit": {"type": "integer"},
                    "routing": {
                        "type": "object",
                        "properties": {
                            "compiled_plan_only": {"type": "boolean"},
                            "restricted_sql_allowed": {"type": "boolean"},
                        },
                    },
                    "reuse_current_plan": {"type": "boolean"},
                    "chart_type_override": {"type": "string", "enum": ["line", "bar", "grouped_bar", "heatmap", "table"]},
                },
                "required": ["question"],
            },
            output_schema=self._success_output_schema("answer"),
        )
        self.restricted_sql_tool = ToolDefinition(
            name="restricted_sql",
            description="Governed restricted SQL capability. Use only when normal compiled-plan analytics is not sufficient and routing allows it.",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "row_limit": {"type": "integer"},
                },
                "required": ["sql"],
            },
            output_schema=self._success_output_schema("restricted_sql"),
        )

    def tools_for_chat(self, latest_user_message: str, routing: RoutingControls) -> tuple[ToolDefinition, ...]:
        tools = [self.answer_tool]
        if routing.restricted_sql_allowed and self._should_offer_restricted_sql(latest_user_message):
            tools.append(self.restricted_sql_tool)
        return tuple(tools)

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "answer":
            response = self.answer_service.answer_request(AnswerRequest.from_dict(arguments))
            return success_envelope("answer", response.to_dict())
        if tool_name == "restricted_sql":
            response = self.answer_service.restricted_sql_request(RestrictedSqlRequest.from_dict(arguments))
            return success_envelope("restricted_sql", response.to_dict())
        raise ValueError(f"Unknown tool: {tool_name}")

    def _should_offer_restricted_sql(self, latest_user_message: str) -> bool:
        normalized = latest_user_message.lower()
        trigger_terms = (
            "restricted sql",
            "write sql",
            "show sql",
            "select ",
            "join ",
            "manual query",
            "sql query",
        )
        return any(term in normalized for term in trigger_terms)

    def _success_output_schema(self, tool_name: str) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "tool_name": {"type": "string", "enum": [tool_name]},
                "data": {"type": "object"},
                "error": {"type": ["object", "null"]},
            },
            "required": ["ok", "tool_name", "data", "error"],
        }
