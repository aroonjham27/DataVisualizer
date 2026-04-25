from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlannedField:
    entity: str
    name: str
    label: str
    kind: str

    @property
    def field_id(self) -> str:
        return f"{self.entity}.{self.name}"


@dataclass(frozen=True)
class PlannedFilter:
    field: PlannedField
    operator: str
    value: Any
    source: str = "question"


@dataclass(frozen=True)
class PlannedMeasure:
    field: PlannedField
    aggregation: str
    local_filters: tuple[PlannedFilter, ...] = ()
    role: str = "primary"


@dataclass(frozen=True)
class PlanJoinStep:
    left_entity: str
    right_entity: str
    cardinality: str
    traversal: str
    join_keys: tuple[tuple[str, str], ...]
    notes: str = ""


@dataclass(frozen=True)
class DrillSelection:
    field: PlannedField
    values: tuple[Any, ...]
    source: str = "visual_member"


@dataclass(frozen=True)
class DrillState:
    hierarchy_name: str
    hierarchy_label: str
    levels: tuple[str, ...]
    current_level_index: int
    next_level: str | None
    selected_member: DrillSelection | None = None
    is_continuation: bool = False


@dataclass(frozen=True)
class ChartIntent:
    chart_type: str
    reason: str


@dataclass(frozen=True)
class AnalysisPlan:
    question: str
    semantic_model_name: str
    semantic_model_version: str
    status: str
    primary_entity: str
    measures: tuple[PlannedMeasure, ...]
    dimensions: tuple[PlannedField, ...]
    time_dimension: PlannedField | None
    time_grain: str | None
    filters: tuple[PlannedFilter, ...]
    join_path: tuple[PlanJoinStep, ...]
    drill: DrillState | None
    chart_intent: ChartIntent | None
    warnings: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisPlan":
        def parse_field(raw: dict[str, Any] | None) -> PlannedField | None:
            if raw is None:
                return None
            return PlannedField(**raw)

        def parse_filter(raw: dict[str, Any]) -> PlannedFilter:
            return PlannedFilter(field=parse_field(raw["field"]), operator=raw["operator"], value=raw["value"], source=raw.get("source", "question"))  # type: ignore[arg-type]

        def parse_measure(raw: dict[str, Any]) -> PlannedMeasure:
            local_filters = tuple(parse_filter(item) for item in raw.get("local_filters", ()))
            return PlannedMeasure(
                field=parse_field(raw["field"]),  # type: ignore[arg-type]
                aggregation=raw["aggregation"],
                local_filters=local_filters,
                role=raw.get("role", "primary"),
            )

        def parse_join(raw: dict[str, Any]) -> PlanJoinStep:
            return PlanJoinStep(
                left_entity=raw["left_entity"],
                right_entity=raw["right_entity"],
                cardinality=raw["cardinality"],
                traversal=raw["traversal"],
                join_keys=tuple((left, right) for left, right in raw["join_keys"]),
                notes=raw.get("notes", ""),
            )

        def parse_selection(raw: dict[str, Any] | None) -> DrillSelection | None:
            if raw is None:
                return None
            return DrillSelection(
                field=parse_field(raw["field"]),  # type: ignore[arg-type]
                values=tuple(raw.get("values", ())),
                source=raw.get("source", "visual_member"),
            )

        def parse_drill(raw: dict[str, Any] | None) -> DrillState | None:
            if raw is None:
                return None
            return DrillState(
                hierarchy_name=raw["hierarchy_name"],
                hierarchy_label=raw["hierarchy_label"],
                levels=tuple(raw["levels"]),
                current_level_index=raw["current_level_index"],
                next_level=raw.get("next_level"),
                selected_member=parse_selection(raw.get("selected_member")),
                is_continuation=raw.get("is_continuation", False),
            )

        def parse_chart(raw: dict[str, Any] | None) -> ChartIntent | None:
            if raw is None:
                return None
            return ChartIntent(chart_type=raw["chart_type"], reason=raw["reason"])

        return cls(
            question=payload["question"],
            semantic_model_name=payload["semantic_model_name"],
            semantic_model_version=payload["semantic_model_version"],
            status=payload["status"],
            primary_entity=payload["primary_entity"],
            measures=tuple(parse_measure(item) for item in payload.get("measures", ())),
            dimensions=tuple(parse_field(item) for item in payload.get("dimensions", ()) if item is not None),  # type: ignore[arg-type]
            time_dimension=parse_field(payload.get("time_dimension")),
            time_grain=payload.get("time_grain"),
            filters=tuple(parse_filter(item) for item in payload.get("filters", ())),
            join_path=tuple(parse_join(item) for item in payload.get("join_path", ())),
            drill=parse_drill(payload.get("drill")),
            chart_intent=parse_chart(payload.get("chart_intent")),
            warnings=tuple(payload.get("warnings", ())),
            matched_terms=tuple(payload.get("matched_terms", ())),
            notes=tuple(payload.get("notes", ())),
        )


@dataclass(frozen=True)
class AnalysisRequest:
    question: str
    current_analysis_state: AnalysisPlan | None = None
    selected_member: DrillSelection | None = None
    semantic_model_path: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisRequest":
        def parse_field(raw: dict[str, Any] | None) -> PlannedField | None:
            if raw is None:
                return None
            return PlannedField(**raw)

        def parse_selection(raw: dict[str, Any] | None) -> DrillSelection | None:
            if raw is None:
                return None
            return DrillSelection(
                field=parse_field(raw["field"]),  # type: ignore[arg-type]
                values=tuple(raw.get("values", ())),
                source=raw.get("source", "visual_member"),
            )

        current_state_payload = payload.get("current_analysis_state")
        current_state = AnalysisPlan.from_dict(current_state_payload) if current_state_payload else None
        return cls(
            question=payload["question"],
            current_analysis_state=current_state,
            selected_member=parse_selection(payload.get("selected_member")),
            semantic_model_path=payload.get("semantic_model_path"),
        )


@dataclass(frozen=True)
class RoutingControls:
    compiled_plan_only: bool = True
    restricted_sql_allowed: bool = False
    policy: str = field(init=False)

    def __post_init__(self) -> None:
        if self.compiled_plan_only and self.restricted_sql_allowed:
            raise ValueError("Routing controls cannot request compiled_plan_only and restricted_sql_allowed at the same time.")
        if not self.compiled_plan_only and not self.restricted_sql_allowed:
            raise ValueError("Routing controls must enable at least one governed query lane.")
        policy = "compiled_plan_only" if self.compiled_plan_only else "restricted_sql_allowed"
        object.__setattr__(self, "policy", policy)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RoutingControls":
        if not payload:
            return cls()
        return cls(
            compiled_plan_only=bool(payload.get("compiled_plan_only", True)),
            restricted_sql_allowed=bool(payload.get("restricted_sql_allowed", False)),
        )


@dataclass(frozen=True)
class RoutingMetadata:
    policy: str
    compiled_plan_only: bool
    restricted_sql_allowed: bool
    selected_query_mode: str


@dataclass(frozen=True)
class WarningItem:
    code: str
    message: str
    source: str


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    current_analysis_state: AnalysisPlan | None = None
    selected_member: DrillSelection | None = None
    semantic_model_path: str | None = None
    row_limit: int | None = None
    routing: RoutingControls = field(default_factory=RoutingControls)
    reuse_current_plan: bool = False
    chart_type_override: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnswerRequest":
        analysis_request = AnalysisRequest.from_dict(payload)
        row_limit = payload.get("row_limit")
        return cls(
            question=analysis_request.question,
            current_analysis_state=analysis_request.current_analysis_state,
            selected_member=analysis_request.selected_member,
            semantic_model_path=analysis_request.semantic_model_path,
            row_limit=int(row_limit) if row_limit is not None else None,
            routing=RoutingControls.from_dict(payload.get("routing")),
            reuse_current_plan=bool(payload.get("reuse_current_plan", False)),
            chart_type_override=payload.get("chart_type_override"),
        )


@dataclass(frozen=True)
class RestrictedSqlRequest:
    sql: str
    row_limit: int | None = None
    semantic_model_path: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RestrictedSqlRequest":
        row_limit = payload.get("row_limit")
        return cls(
            sql=payload["sql"],
            row_limit=int(row_limit) if row_limit is not None else None,
            semantic_model_path=payload.get("semantic_model_path"),
        )


@dataclass(frozen=True)
class QueryMetadata:
    query_mode: str
    row_limit: int
    involved_entities: tuple[str, ...]
    validation_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultColumn:
    name: str
    label: str
    data_type: str
    semantic_lineage: tuple[str, ...]
    role: str


@dataclass(frozen=True)
class ResultLimitMetadata:
    row_limit: int
    returned_rows: int
    truncated: bool
    possibly_truncated: bool


@dataclass(frozen=True)
class ChartSpec:
    chart_type: str
    title: str
    x: str | None = None
    y: tuple[str, ...] = ()
    series: str | None = None
    columns: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    chart_choice_explanation: str = ""


@dataclass(frozen=True)
class AnswerResponse:
    tool_name: str
    plan: AnalysisPlan
    routing: RoutingMetadata
    query_mode: str
    query_metadata: QueryMetadata
    sql: str
    columns: tuple[ResultColumn, ...]
    rows: tuple[tuple[Any, ...], ...]
    limit: ResultLimitMetadata
    warnings: tuple[WarningItem, ...]
    chart_spec: ChartSpec

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RestrictedSqlResponse:
    tool_name: str
    query_mode: str
    query_metadata: QueryMetadata
    sql: str
    columns: tuple[ResultColumn, ...]
    rows: tuple[tuple[Any, ...], ...]
    limit: ResultLimitMetadata
    warnings: tuple[WarningItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        return cls(role=payload["role"], content=payload["content"])


@dataclass(frozen=True)
class ConversationState:
    current_analysis_state: AnalysisPlan | None = None
    selected_member: DrillSelection | None = None
    last_tool_name: str | None = None
    last_query_mode: str | None = None
    last_sql: str | None = None
    last_columns: tuple[dict[str, Any], ...] = ()
    last_rows: tuple[tuple[Any, ...], ...] = ()
    last_chart_spec: dict[str, Any] | None = None
    last_limit: dict[str, Any] | None = None
    last_warnings: tuple[dict[str, Any], ...] = ()
    last_query_metadata: dict[str, Any] | None = None
    last_plan: dict[str, Any] | None = None
    last_chart_type: str | None = None
    last_row_limit: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ConversationState | None":
        if payload is None:
            return None

        def parse_field(raw: dict[str, Any] | None) -> PlannedField | None:
            if raw is None:
                return None
            return PlannedField(**raw)

        def parse_selection(raw: dict[str, Any] | None) -> DrillSelection | None:
            if raw is None:
                return None
            return DrillSelection(
                field=parse_field(raw["field"]),  # type: ignore[arg-type]
                values=tuple(raw.get("values", ())),
                source=raw.get("source", "visual_member"),
            )

        current_state_payload = payload.get("current_analysis_state")
        rows = tuple(tuple(row) for row in payload.get("last_rows", ()))
        columns = tuple(dict(column) for column in payload.get("last_columns", ()) if isinstance(column, dict))
        warnings = tuple(dict(warning) for warning in payload.get("last_warnings", ()) if isinstance(warning, dict))
        return cls(
            current_analysis_state=AnalysisPlan.from_dict(current_state_payload) if current_state_payload else None,
            selected_member=parse_selection(payload.get("selected_member")),
            last_tool_name=payload.get("last_tool_name"),
            last_query_mode=payload.get("last_query_mode"),
            last_sql=payload.get("last_sql"),
            last_columns=columns,
            last_rows=rows,
            last_chart_spec=dict(payload["last_chart_spec"]) if isinstance(payload.get("last_chart_spec"), dict) else None,
            last_limit=dict(payload["last_limit"]) if isinstance(payload.get("last_limit"), dict) else None,
            last_warnings=warnings,
            last_query_metadata=dict(payload["last_query_metadata"]) if isinstance(payload.get("last_query_metadata"), dict) else None,
            last_plan=dict(payload["last_plan"]) if isinstance(payload.get("last_plan"), dict) else None,
            last_chart_type=payload.get("last_chart_type"),
            last_row_limit=payload.get("last_row_limit"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    conversation_state: ConversationState | None = None
    selected_member: DrillSelection | None = None
    semantic_model_path: str | None = None
    routing: RoutingControls = field(default_factory=lambda: RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatRequest":
        def parse_field(raw: dict[str, Any] | None) -> PlannedField | None:
            if raw is None:
                return None
            return PlannedField(**raw)

        def parse_selection(raw: dict[str, Any] | None) -> DrillSelection | None:
            if raw is None:
                return None
            return DrillSelection(
                field=parse_field(raw["field"]),  # type: ignore[arg-type]
                values=tuple(raw.get("values", ())),
                source=raw.get("source", "visual_member"),
            )

        routing_payload = payload.get("routing")
        routing = (
            RoutingControls.from_dict(routing_payload)
            if routing_payload
            else RoutingControls(compiled_plan_only=False, restricted_sql_allowed=True)
        )
        return cls(
            messages=tuple(ChatMessage.from_dict(item) for item in payload.get("messages", ())),
            conversation_state=ConversationState.from_dict(payload.get("conversation_state")),
            selected_member=parse_selection(payload.get("selected_member")),
            semantic_model_path=payload.get("semantic_model_path"),
            routing=routing,
        )


@dataclass(frozen=True)
class ToolCallTrace:
    tool_name: str
    arguments: dict[str, Any]
    result_ok: bool


@dataclass(frozen=True)
class ChatResponse:
    tool_name: str
    assistant_message: str
    executed_tool_name: str | None
    tool_result: dict[str, Any] | None
    conversation_state: ConversationState
    tool_trace: tuple[ToolCallTrace, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
