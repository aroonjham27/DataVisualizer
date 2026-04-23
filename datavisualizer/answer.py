from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .charting import ChartSpecGenerator
from .contracts import (
    AnalysisPlan,
    AnswerRequest,
    AnswerResponse,
    DrillSelection,
    ResultColumn,
    ResultLimitMetadata,
)
from .planner import DEFAULT_MODEL_PATH, SemanticPlanner
from .query_gateway import QueryGateway
from .semantic_model import SemanticModel, load_semantic_model


class AnswerService:
    def __init__(self, semantic_model: SemanticModel):
        self.semantic_model = semantic_model
        self.planner = SemanticPlanner(semantic_model)
        self.gateway = QueryGateway(semantic_model)
        self.chart_specs = ChartSpecGenerator()

    @classmethod
    def from_default_model(cls) -> "AnswerService":
        return cls(load_semantic_model(DEFAULT_MODEL_PATH))

    @classmethod
    def from_model_path(cls, model_path: str | Path | None) -> "AnswerService":
        return cls(load_semantic_model(model_path or DEFAULT_MODEL_PATH))

    def answer_request(self, request: AnswerRequest) -> AnswerResponse:
        return self.answer(
            question=request.question,
            current_analysis_state=request.current_analysis_state,
            selected_member=request.selected_member,
            row_limit=request.row_limit,
        )

    def answer(
        self,
        question: str,
        current_analysis_state: AnalysisPlan | None = None,
        selected_member: DrillSelection | None = None,
        row_limit: int | None = None,
    ) -> AnswerResponse:
        plan = self.planner.plan(question, current_state=current_analysis_state, selected_member=selected_member)
        execution = self.gateway.execute_compiled_plan(plan, row_limit=row_limit)
        rows = tuple(tuple(self._json_safe(value) for value in row) for row in execution.result.rows)
        columns = self._result_columns(plan, execution.result.columns)
        chart_spec = self.chart_specs.generate(plan, columns, rows)
        warnings = tuple(dict.fromkeys((*plan.warnings, *chart_spec.warnings)))
        return AnswerResponse(
            plan=plan,
            query_mode=execution.query_mode,
            query_metadata=execution.metadata,
            sql=execution.sql,
            columns=columns,
            rows=rows,
            limit=ResultLimitMetadata(
                row_limit=execution.metadata.row_limit,
                returned_rows=len(rows),
                truncated=execution.truncated,
                possibly_truncated=execution.truncated,
            ),
            warnings=warnings,
            chart_spec=chart_spec,
        )

    def _result_columns(self, plan: AnalysisPlan, result_columns: tuple[str, ...]) -> tuple[ResultColumn, ...]:
        expected = {}
        for field in plan.dimensions:
            expected[self._field_alias(field.entity, field.name)] = ResultColumn(
                name=self._field_alias(field.entity, field.name),
                label=field.label,
                data_type=self._field_type(field.entity, field.name, "dimension"),
                semantic_lineage=(field.field_id,),
                role="dimension",
            )
        if plan.time_dimension is not None:
            alias = self._field_alias(plan.time_dimension.entity, plan.time_dimension.name, plan.time_grain or "day")
            expected[alias] = ResultColumn(
                name=alias,
                label=f"{plan.time_dimension.label} ({plan.time_grain or 'day'})",
                data_type="date",
                semantic_lineage=(plan.time_dimension.field_id,),
                role="time",
            )
        used_measure_aliases: set[str] = set()
        for measure in plan.measures:
            alias = self._measure_alias(measure.field.entity, measure.field.name, measure.role, used_measure_aliases)
            used_measure_aliases.add(alias)
            expected[alias] = ResultColumn(
                name=alias,
                label=measure.field.label,
                data_type="number",
                semantic_lineage=(measure.field.field_id,),
                role="measure",
            )
        return tuple(
            expected.get(
                column,
                ResultColumn(name=column, label=column, data_type="unknown", semantic_lineage=(), role="unknown"),
            )
            for column in result_columns
        )

    def _field_type(self, entity_name: str, field_name: str, kind: str) -> str:
        entity = self.semantic_model.entity(entity_name)
        if kind == "dimension":
            return entity.get_dimension(field_name).type
        return "unknown"

    def _field_alias(self, entity: str, field: str, suffix: str | None = None) -> str:
        alias = f"{entity}_{field}"
        if suffix:
            alias = f"{alias}_{suffix}"
        return alias

    def _measure_alias(self, entity: str, field: str, role: str, used_aliases: set[str]) -> str:
        base = f"{entity}_{field}"
        if role != "primary":
            base = f"{base}_{role}"
        alias = base
        counter = 2
        while alias in used_aliases:
            alias = f"{base}_{counter}"
            counter += 1
        return alias

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value
