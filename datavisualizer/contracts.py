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
