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
from .errors import RequestValidationError, normalize_error
from .llm_client import DisabledLlmClient, LlmClient, LlmResponse, OpenAiCompatibleLlmClient
from .semantic_resolver import normalize_semantic_term
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
        trace = [ToolCallTrace(tool_name=tool_call.name, arguments=tool_args, result_ok=bool(tool_result.get("ok")))]
        if tool_call.name == "answer":
            fallback = self._attempt_restricted_sql_fallback(
                request=request,
                active_state=active_state,
                latest_user_message=latest_user_message,
                llm_messages=llm_messages,
                compiled_tool_result=tool_result,
            )
            if fallback is not None:
                fallback_tool_call, fallback_args, fallback_result, fallback_llm_response = fallback
                trace.append(
                    ToolCallTrace(
                        tool_name=fallback_tool_call.name,
                        arguments=fallback_args,
                        result_ok=bool(fallback_result.get("ok")),
                    )
                )
                updated_state = self._updated_state(active_state, request, fallback_tool_call.name, fallback_result)
                final_message = self._final_assistant_message(
                    llm_messages,
                    fallback_llm_response,
                    fallback_tool_call,
                    fallback_result,
                    force_restricted_sql_notice=True,
                )
                return ChatResponse(
                    tool_name="chat",
                    assistant_message=final_message,
                    executed_tool_name=fallback_tool_call.name,
                    tool_result=fallback_result,
                    conversation_state=updated_state,
                    tool_trace=tuple(trace),
                )
        updated_state = self._updated_state(active_state, request, tool_call.name, tool_result)
        final_message = self._final_assistant_message(
            llm_messages,
            llm_response,
            tool_call,
            tool_result,
            force_restricted_sql_notice=tool_call.name == "restricted_sql",
        )
        return ChatResponse(
            tool_name="chat",
            assistant_message=final_message,
            executed_tool_name=tool_call.name,
            tool_result=tool_result,
            conversation_state=updated_state,
            tool_trace=tuple(trace),
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
            "Use restricted_sql only when it is explicitly available and clearly justified by a SQL-specific request or a backend fallback prompt.\n"
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
        *,
        force_restricted_sql_notice: bool = False,
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
            message = self._fallback_summary(tool_result)
            return self._with_restricted_sql_notice(message) if force_restricted_sql_notice else message
        if final.message.content.strip():
            message = final.message.content.strip()
            return self._with_restricted_sql_notice(message) if force_restricted_sql_notice else message
        message = self._fallback_summary(tool_result)
        return self._with_restricted_sql_notice(message) if force_restricted_sql_notice else message

    def _fallback_summary(self, tool_result: dict[str, Any]) -> str:
        data = tool_result.get("data", {})
        if tool_result.get("tool_name") == "answer":
            return f"Returned {data.get('limit', {}).get('returned_rows', 0)} rows using {data.get('query_mode', 'compiled_plan')}."
        if tool_result.get("tool_name") == "restricted_sql":
            return f"Executed governed restricted SQL and returned {data.get('limit', {}).get('returned_rows', 0)} rows."
        return "Completed the requested tool call."

    def _attempt_restricted_sql_fallback(
        self,
        *,
        request: ChatRequest,
        active_state: ConversationState,
        latest_user_message: str,
        llm_messages: list[dict[str, Any]],
        compiled_tool_result: dict[str, Any],
    ) -> tuple[Any, dict[str, Any], dict[str, Any], LlmResponse] | None:
        reasons = self._compiled_plan_insufficiency_reasons(compiled_tool_result, latest_user_message)
        if not reasons or not self._restricted_sql_fallback_allowed(request, latest_user_message):
            return None
        if not hasattr(self.tools, "restricted_sql_tool"):
            return None
        restricted_tool = self.tools.restricted_sql_tool
        fallback_messages = self._restricted_sql_fallback_messages(llm_messages, compiled_tool_result, reasons)
        try:
            fallback_response = self.llm_client.generate(
                fallback_messages,
                tools=[restricted_tool.to_openai_tool()],
                tool_choice={"type": "function", "function": {"name": "restricted_sql"}},
            )
            fallback_tool_call = self._require_single_tool_call(fallback_response, (restricted_tool,))
        except Exception as exc:  # noqa: BLE001
            self._annotate_compiled_result_with_failed_fallback(compiled_tool_result, normalize_error(exc).message)
            return None
        fallback_args = self._enrich_tool_arguments(
            fallback_tool_call.name,
            fallback_tool_call.arguments,
            request,
            active_state,
            latest_user_message,
        )
        try:
            fallback_result = self.tools.execute(fallback_tool_call.name, fallback_args)
        except Exception as exc:  # noqa: BLE001
            self._annotate_compiled_result_with_failed_fallback(compiled_tool_result, normalize_error(exc).message)
            return None
        if not fallback_result.get("ok"):
            error = fallback_result.get("error") or {}
            self._annotate_compiled_result_with_failed_fallback(
                compiled_tool_result,
                str(error.get("message", "Restricted SQL fallback did not return a successful result.")),
            )
            return None
        self._annotate_restricted_sql_fallback_result(fallback_result, request, "; ".join(reasons))
        return fallback_tool_call, fallback_args, fallback_result, fallback_response

    def _restricted_sql_fallback_allowed(self, request: ChatRequest, latest_user_message: str) -> bool:
        if request.routing.compiled_plan_only or not request.routing.restricted_sql_allowed:
            return False
        return self._looks_like_analytics_request(latest_user_message) and self._looks_representable_as_restricted_sql(latest_user_message)

    def _compiled_plan_insufficiency_reasons(self, tool_result: dict[str, Any], question: str) -> tuple[str, ...]:
        if not tool_result.get("ok"):
            return ("compiled-plan tool did not return a successful result",)
        data = tool_result.get("data") or {}
        plan = data.get("plan") or {}
        reasons: list[str] = []
        status = str(plan.get("status", ""))
        warning_text = " ".join(str(item.get("message", "")) for item in data.get("warnings", ()) if isinstance(item, dict)).lower()
        if "fallback semantic match" in warning_text:
            reasons.append("planner used a fallback semantic match")
        if status and status != "ok" and any(term in warning_text for term in ("unsupported", "incomplete", "could not", "did not add")):
            reasons.append(f"plan status is {status}")
        missing_fields = self._missing_requested_fields(question, plan)
        if missing_fields:
            reasons.append(f"requested semantic fields were missing from the plan: {', '.join(missing_fields)}")
        chart_spec = data.get("chart_spec") or {}
        chart_warning_text = " ".join(str(item) for item in chart_spec.get("warnings", ())).lower()
        if chart_spec.get("chart_type") == "table" and "unsupported" in chart_warning_text:
            reasons.append("chart generation fell back to a table for the compiled-plan shape")
        return tuple(dict.fromkeys(reasons))

    def _missing_requested_fields(self, question: str, plan: dict[str, Any]) -> tuple[str, ...]:
        requested = self._requested_semantic_fields(question, kinds={"dimension", "time_dimension"})
        if not requested:
            return ()
        planned: set[str] = set()
        for field in plan.get("dimensions", ()) or ():
            field_id = self._field_id_from_payload(field)
            if field_id:
                planned.add(field_id)
        time_field = self._field_id_from_payload(plan.get("time_dimension"))
        if time_field:
            planned.add(time_field)
        planned_field_names = {field_id.split(".", 1)[1] for field_id in planned if "." in field_id}
        for filter_ in plan.get("filters", ()) or ():
            field_id = self._field_id_from_payload((filter_ or {}).get("field") if isinstance(filter_, dict) else None)
            if field_id:
                planned.add(field_id)
                planned_field_names.add(field_id.split(".", 1)[1])
        return tuple(
            field_id
            for field_id in requested
            if field_id not in planned and ("." not in field_id or field_id.split(".", 1)[1] not in planned_field_names)
        )

    def _requested_semantic_fields(self, question: str, *, kinds: set[str] | None = None) -> tuple[str, ...]:
        normalized = normalize_semantic_term(question)
        matches: list[str] = []
        for entity in self.answer_service.semantic_model.entities.values():
            for field in entity.dimensions:
                if kinds is None or "dimension" in kinds:
                    if self._question_mentions_any(normalized, self._field_terms(field.name, field.label, field.synonyms)):
                        matches.append(f"{entity.name}.{field.name}")
            for field in entity.time_dimensions:
                if kinds is None or "time_dimension" in kinds:
                    terms = [*self._field_terms(field.name, field.label, ()), field.name.replace("_date", " month").replace("_", " ")]
                    if self._question_mentions_any(normalized, terms):
                        matches.append(f"{entity.name}.{field.name}")
            for measure in entity.measures:
                if kinds is None or "measure" in kinds:
                    if self._question_mentions_any(normalized, self._field_terms(measure.name, measure.label, ())):
                        matches.append(f"{entity.name}.{measure.name}")
        return tuple(dict.fromkeys(matches))

    def _looks_like_analytics_request(self, question: str) -> bool:
        normalized = normalize_semantic_term(question)
        analytics_terms = (
            "show",
            "count",
            "rate",
            "sum",
            "average",
            "avg",
            "trend",
            "breakdown",
            "compare",
            "by",
            "how many",
            "what is",
            "which",
        )
        return any(term in normalized for term in analytics_terms)

    def _looks_representable_as_restricted_sql(self, question: str) -> bool:
        if self._requested_semantic_fields(question):
            return True
        normalized = normalize_semantic_term(question)
        for entity in self.answer_service.semantic_model.entities.values():
            entity_terms = (entity.name.replace("_", " "), entity.label, *entity.synonyms)
            if self._question_mentions_any(normalized, entity_terms):
                return True
        return False

    def _restricted_sql_fallback_messages(
        self,
        llm_messages: list[dict[str, Any]],
        compiled_tool_result: dict[str, Any],
        reasons: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        messages = list(llm_messages)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": "compiled-plan-evaluation",
                "name": "answer",
                "content": json.dumps(compiled_tool_result),
            }
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "The compiled-plan result is not sufficient for this valid analytics request. "
                    f"Reasons: {'; '.join(reasons)}.\n"
                    "Return exactly one restricted_sql tool call. Produce a safe governed SELECT only; do not include prose. "
                    "Use only the semantic entities, fields, and approved joins below. "
                    "Do not use comments, CTEs, subqueries, UNION, OR predicates, file access, or unsafe SQL.\n\n"
                    f"{self._restricted_sql_semantic_context()}"
                ),
            }
        )
        return messages

    def _restricted_sql_semantic_context(self) -> str:
        lines = ["Semantic entities and fields:"]
        for entity in self.answer_service.semantic_model.entities.values():
            dimensions = ", ".join(field.name for field in entity.dimensions) or "none"
            time_dimensions = ", ".join(field.name for field in entity.time_dimensions) or "none"
            measures = ", ".join(
                f"{measure.name}({measure.aggregation}{':' + measure.field if measure.field else ''})"
                for measure in entity.measures
            ) or "none"
            lines.append(f"- {entity.name}: dimensions [{dimensions}], time [{time_dimensions}], measures [{measures}]")
        lines.append("Approved joins:")
        for join in self.answer_service.semantic_model.allowed_joins:
            if join.status != "approved_for_v0":
                continue
            keys = " and ".join(f"{join.left_entity}.{left} = {join.right_entity}.{right}" for left, right in join.join_keys)
            lines.append(f"- {join.left_entity} JOIN {join.right_entity} ON {keys}")
        return "\n".join(lines)

    def _annotate_restricted_sql_fallback_result(
        self,
        tool_result: dict[str, Any],
        request: ChatRequest,
        fallback_reason: str,
    ) -> None:
        data = tool_result.get("data") or {}
        data["fallback_reason"] = fallback_reason
        data["routing"] = {
            "policy": request.routing.policy,
            "compiled_plan_only": request.routing.compiled_plan_only,
            "restricted_sql_allowed": request.routing.restricted_sql_allowed,
            "selected_query_mode": "restricted_sql",
        }
        columns = data.get("columns") or ()
        data.setdefault(
            "chart_spec",
            {
                "chart_type": "table",
                "title": "Restricted SQL Result",
                "x": None,
                "y": (),
                "series": None,
                "columns": tuple(column.get("name") for column in columns if isinstance(column, dict)),
                "warnings": ("Restricted SQL fallback results default to table rendering.",),
            },
        )
        metadata = data.setdefault("query_metadata", {})
        notes = list(metadata.get("validation_notes", ()))
        notes.append(f"Automatic fallback reason: {fallback_reason}")
        notes.append("Used alternate governed query path after compiled-plan evaluation.")
        metadata["validation_notes"] = tuple(notes)

    def _annotate_compiled_result_with_failed_fallback(self, tool_result: dict[str, Any], message: str) -> None:
        data = tool_result.get("data")
        if not isinstance(data, dict):
            return
        warnings = list(data.get("warnings", ()))
        warnings.append(
            {
                "code": "routing_restricted_sql_fallback_failed",
                "message": f"Restricted SQL fallback was attempted but rejected safely: {message}",
                "source": "query",
            }
        )
        data["warnings"] = tuple(warnings)
        metadata = data.setdefault("query_metadata", {})
        notes = list(metadata.get("validation_notes", ()))
        notes.append(f"Restricted SQL fallback rejected safely: {message}")
        metadata["validation_notes"] = tuple(notes)

    def _with_restricted_sql_notice(self, message: str) -> str:
        notice = (
            "I used an alternate governed query path because this request needed a more custom breakdown than "
            "the standard planner currently supports. Please review the inspector for query details."
        )
        if notice in message:
            return message
        return f"{notice}\n\n{message}" if message else notice

    def _field_terms(self, name: str, label: str, synonyms: tuple[str, ...]) -> tuple[str, ...]:
        terms = [label]
        if "_" in name:
            terms.append(name.replace("_", " "))
        terms.extend(term for term in synonyms if " " in normalize_semantic_term(term))
        return tuple(dict.fromkeys(terms))

    def _question_mentions_any(self, normalized_question: str, terms: tuple[str, ...] | list[str]) -> bool:
        for term in terms:
            normalized_term = normalize_semantic_term(term)
            if not normalized_term:
                continue
            if normalized_term in {"account", "product", "opportunity", "contract", "line", "customer"}:
                continue
            if " " not in normalized_term and len(normalized_term) < 6:
                continue
            padded_question = f" {normalized_question} "
            padded_term = f" {normalized_term} "
            if padded_term in padded_question:
                return True
        return False

    def _field_id_from_payload(self, field: Any) -> str:
        if not isinstance(field, dict):
            return ""
        entity = field.get("entity")
        name = field.get("name")
        return f"{entity}.{name}" if entity and name else ""
