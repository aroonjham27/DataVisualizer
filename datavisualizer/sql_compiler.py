from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import AnalysisPlan, PlanJoinStep, PlannedField, PlannedFilter, PlannedMeasure
from .planner import DEFAULT_MODEL_PATH
from .semantic_model import SemanticEntity, SemanticMeasure, SemanticModel, load_semantic_model


class SqlCompilationError(ValueError):
    """Raised when an analysis plan shape cannot be compiled safely."""


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    row_limit: int
    involved_entities: tuple[str, ...]


@dataclass(frozen=True)
class _SelectedExpression:
    expression: str
    alias: str
    field: PlannedField
    is_time: bool = False


class DuckDbSqlCompiler:
    def __init__(self, semantic_model: SemanticModel, default_limit: int = 500):
        self.semantic_model = semantic_model
        self.default_limit = default_limit

    @classmethod
    def from_default_model(cls, default_limit: int = 500) -> "DuckDbSqlCompiler":
        return cls(load_semantic_model(DEFAULT_MODEL_PATH), default_limit=default_limit)

    def compile(self, plan: AnalysisPlan, row_limit: int | None = None) -> CompiledQuery:
        limit = row_limit if row_limit is not None else self.default_limit
        if limit <= 0:
            raise SqlCompilationError("Row limit must be positive.")
        self._validate_plan(plan)

        alias_by_entity = self._assign_aliases(plan)
        group_expressions = self._group_expressions(plan, alias_by_entity)
        measure_expressions = self._measure_expressions(plan, alias_by_entity)
        if not measure_expressions:
            raise SqlCompilationError("Plan must include at least one measure.")

        ctes = self._compile_ctes(alias_by_entity)
        select_items = [f"{item.expression} AS {self._quote_identifier(item.alias)}" for item in group_expressions]
        select_items.extend(f"{expression} AS {self._quote_identifier(alias)}" for expression, alias in measure_expressions)
        from_clause = self._compile_from_clause(plan, alias_by_entity)
        where_clause = self._compile_where_clause(plan.filters, alias_by_entity)
        group_by_clause = self._compile_group_by_clause(group_expressions)
        order_by_clause = self._compile_order_by_clause(group_expressions, measure_expressions)

        sql_parts = [
            "WITH",
            ",\n".join(ctes),
            "SELECT",
            ",\n  ".join(f"  {item}" for item in select_items),
            from_clause,
        ]
        if where_clause:
            sql_parts.append(where_clause)
        if group_by_clause:
            sql_parts.append(group_by_clause)
        if order_by_clause:
            sql_parts.append(order_by_clause)
        sql_parts.append(f"LIMIT {limit}")
        return CompiledQuery(
            sql="\n".join(sql_parts),
            row_limit=limit,
            involved_entities=tuple(alias_by_entity.keys()),
        )

    def _validate_plan(self, plan: AnalysisPlan) -> None:
        self._entity(plan.primary_entity)
        for field in (*plan.dimensions, *( [plan.time_dimension] if plan.time_dimension else [])):
            self._validate_non_measure_field(field)
        for measure in plan.measures:
            self._semantic_measure(measure)
            for local_filter in measure.local_filters:
                self._validate_filter(local_filter)
        for filter_ in plan.filters:
            self._validate_filter(filter_)
        if plan.time_grain is not None and plan.time_grain not in {"year", "quarter", "month", "day"}:
            raise SqlCompilationError(f"Unsupported time grain: {plan.time_grain}")
        allowed_join_edges = {
            frozenset((join.left_entity, join.right_entity))
            for join in self.semantic_model.allowed_joins
            if join.status == "approved_for_v0"
        }
        for join in plan.join_path:
            if frozenset((join.left_entity, join.right_entity)) not in allowed_join_edges:
                raise SqlCompilationError(f"Join is not approved by the semantic model: {join.left_entity} -> {join.right_entity}")

    def _validate_non_measure_field(self, field: PlannedField) -> None:
        entity = self._entity(field.entity)
        if field.kind == "dimension":
            entity.get_dimension(field.name)
            return
        if field.kind == "time_dimension":
            entity.get_time_dimension(field.name)
            return
        raise SqlCompilationError(f"Unsupported grouped field kind: {field.kind}")

    def _validate_filter(self, filter_: PlannedFilter) -> None:
        if filter_.operator not in {"=", "in"}:
            raise SqlCompilationError(f"Unsupported filter operator: {filter_.operator}")
        field = filter_.field
        entity = self._entity(field.entity)
        if field.kind == "dimension":
            entity.get_dimension(field.name)
        elif field.kind == "time_dimension":
            entity.get_time_dimension(field.name)
        else:
            raise SqlCompilationError(f"Unsupported filter field kind: {field.kind}")

    def _assign_aliases(self, plan: AnalysisPlan) -> dict[str, str]:
        alias_by_entity = {plan.primary_entity: "t0"}
        for join in plan.join_path:
            self._add_join_alias(join, alias_by_entity)
        for field in plan.dimensions:
            if field.entity not in alias_by_entity:
                raise SqlCompilationError(f"Missing join path for dimension entity: {field.entity}")
        if plan.time_dimension and plan.time_dimension.entity not in alias_by_entity:
            raise SqlCompilationError(f"Missing join path for time dimension entity: {plan.time_dimension.entity}")
        for filter_ in plan.filters:
            if filter_.field.entity not in alias_by_entity:
                raise SqlCompilationError(f"Missing join path for filter entity: {filter_.field.entity}")
        for measure in plan.measures:
            if measure.field.entity not in alias_by_entity:
                raise SqlCompilationError(f"Missing join path for measure entity: {measure.field.entity}")
            for local_filter in measure.local_filters:
                if local_filter.field.entity not in alias_by_entity:
                    raise SqlCompilationError(f"Missing join path for measure-local filter entity: {local_filter.field.entity}")
        return alias_by_entity

    def _add_join_alias(self, join: PlanJoinStep, alias_by_entity: dict[str, str]) -> None:
        self._entity(join.left_entity)
        self._entity(join.right_entity)
        left_known = join.left_entity in alias_by_entity
        right_known = join.right_entity in alias_by_entity
        if left_known and right_known:
            return
        if left_known:
            alias_by_entity[join.right_entity] = f"t{len(alias_by_entity)}"
            return
        if right_known:
            alias_by_entity[join.left_entity] = f"t{len(alias_by_entity)}"
            return
        raise SqlCompilationError(f"Join path is disconnected from the primary entity: {join.left_entity} -> {join.right_entity}")

    def _compile_ctes(self, alias_by_entity: dict[str, str]) -> list[str]:
        ctes = []
        for entity_name in alias_by_entity:
            entity = self._entity(entity_name)
            path = self.semantic_model.source_path_for_entity(entity_name).resolve()
            if not path.exists():
                raise SqlCompilationError(f"Source file not found for entity {entity_name}: {path}")
            ctes.append(
                f"{self._quote_identifier(entity_name)} AS ("
                f"SELECT * FROM read_csv_auto({self._literal(str(path))}, header=true)"
                f")"
            )
        return ctes

    def _compile_from_clause(self, plan: AnalysisPlan, alias_by_entity: dict[str, str]) -> str:
        joined_entities = {plan.primary_entity}
        from_clause = f"FROM {self._quote_identifier(plan.primary_entity)} AS {self._quote_identifier(alias_by_entity[plan.primary_entity])}"
        join_clauses = []
        for join in plan.join_path:
            if join.left_entity in joined_entities and join.right_entity not in joined_entities:
                joining_entity = join.right_entity
                joined_entity = join.left_entity
            elif join.right_entity in joined_entities and join.left_entity not in joined_entities:
                joining_entity = join.left_entity
                joined_entity = join.right_entity
            elif join.left_entity in joined_entities and join.right_entity in joined_entities:
                continue
            else:
                raise SqlCompilationError(f"Join path is out of order: {join.left_entity} -> {join.right_entity}")
            condition = self._join_condition(join, alias_by_entity)
            join_clauses.append(
                f"LEFT JOIN {self._quote_identifier(joining_entity)} AS {self._quote_identifier(alias_by_entity[joining_entity])} ON {condition}"
            )
            joined_entities.add(joining_entity)
            joined_entities.add(joined_entity)
        return "\n".join([from_clause, *join_clauses])

    def _join_condition(self, join: PlanJoinStep, alias_by_entity: dict[str, str]) -> str:
        parts = []
        for left_key, right_key in join.join_keys:
            parts.append(
                f"{self._qualified(join.left_entity, left_key, alias_by_entity)} = "
                f"{self._qualified(join.right_entity, right_key, alias_by_entity)}"
            )
        if not parts:
            raise SqlCompilationError(f"Join has no keys: {join.left_entity} -> {join.right_entity}")
        return " AND ".join(parts)

    def _group_expressions(self, plan: AnalysisPlan, alias_by_entity: dict[str, str]) -> list[_SelectedExpression]:
        expressions = []
        for field in plan.dimensions:
            expressions.append(
                _SelectedExpression(
                    expression=self._qualified(field.entity, field.name, alias_by_entity),
                    alias=self._alias_for_field(field),
                    field=field,
                )
            )
        if plan.time_dimension is not None:
            expressions.append(
                _SelectedExpression(
                    expression=self._time_expression(plan.time_dimension, plan.time_grain, alias_by_entity),
                    alias=self._alias_for_field(plan.time_dimension, suffix=plan.time_grain or "day"),
                    field=plan.time_dimension,
                    is_time=True,
                )
            )
        return expressions

    def _measure_expressions(self, plan: AnalysisPlan, alias_by_entity: dict[str, str]) -> list[tuple[str, str]]:
        expressions = []
        used_aliases: set[str] = set()
        for measure in plan.measures:
            semantic_measure = self._semantic_measure(measure)
            expression = self._measure_expression(measure, semantic_measure, alias_by_entity)
            alias = self._measure_alias(measure, used_aliases)
            used_aliases.add(alias)
            expressions.append((expression, alias))
        return expressions

    def _measure_expression(
        self,
        measure: PlannedMeasure,
        semantic_measure: SemanticMeasure,
        alias_by_entity: dict[str, str],
    ) -> str:
        if semantic_measure.aggregation == "ratio" and semantic_measure.name == "win_rate":
            field = self._qualified(measure.field.entity, "opportunity_id", alias_by_entity)
            outcome = self._qualified(measure.field.entity, "outcome", alias_by_entity)
            return f"COUNT(DISTINCT CASE WHEN {outcome} = 'won' THEN {field} END)::DOUBLE / NULLIF(COUNT(DISTINCT {field}), 0)"
        if semantic_measure.aggregation not in {"count_distinct", "sum", "average"}:
            raise SqlCompilationError(f"Unsupported aggregation: {semantic_measure.aggregation}")
        source_field = semantic_measure.field
        if not source_field:
            raise SqlCompilationError(f"Measure has no source field: {measure.field.field_id}")
        value_expression = self._qualified(measure.field.entity, source_field, alias_by_entity)
        value_expression = self._apply_measure_filters(value_expression, measure, semantic_measure, alias_by_entity)
        if semantic_measure.aggregation == "count_distinct":
            return f"COUNT(DISTINCT {value_expression})"
        if semantic_measure.aggregation == "sum":
            return f"SUM({value_expression})"
        if semantic_measure.aggregation == "average":
            return f"AVG({value_expression})"
        raise SqlCompilationError(f"Unsupported aggregation: {semantic_measure.aggregation}")

    def _apply_measure_filters(
        self,
        value_expression: str,
        measure: PlannedMeasure,
        semantic_measure: SemanticMeasure,
        alias_by_entity: dict[str, str],
    ) -> str:
        predicates = []
        if semantic_measure.filter:
            predicates.append(self._compile_simple_measure_filter(measure.field.entity, semantic_measure.filter, alias_by_entity))
        predicates.extend(self._compile_filter(item, alias_by_entity) for item in measure.local_filters)
        if not predicates:
            return value_expression
        return f"CASE WHEN {' AND '.join(predicates)} THEN {value_expression} END"

    def _compile_simple_measure_filter(self, entity_name: str, filter_text: str, alias_by_entity: dict[str, str]) -> str:
        parts = filter_text.split(" = ")
        if len(parts) != 2:
            raise SqlCompilationError(f"Unsupported semantic measure filter: {filter_text}")
        field_name, value = parts
        return f"{self._qualified(entity_name, field_name, alias_by_entity)} = {self._literal(value)}"

    def _compile_where_clause(self, filters: tuple[PlannedFilter, ...], alias_by_entity: dict[str, str]) -> str:
        if not filters:
            return ""
        predicates = [self._compile_filter(filter_, alias_by_entity) for filter_ in filters]
        return f"WHERE {' AND '.join(predicates)}"

    def _compile_filter(self, filter_: PlannedFilter, alias_by_entity: dict[str, str]) -> str:
        field_expression = self._qualified(filter_.field.entity, filter_.field.name, alias_by_entity)
        if filter_.operator == "=":
            return f"{field_expression} = {self._literal(filter_.value)}"
        if filter_.operator == "in":
            values = filter_.value
            if not isinstance(values, (tuple, list)) or not values:
                raise SqlCompilationError("IN filters require a non-empty tuple or list.")
            return f"{field_expression} IN ({', '.join(self._literal(value) for value in values)})"
        raise SqlCompilationError(f"Unsupported filter operator: {filter_.operator}")

    def _compile_group_by_clause(self, group_expressions: list[_SelectedExpression]) -> str:
        if not group_expressions:
            return ""
        return "GROUP BY " + ", ".join(item.expression for item in group_expressions)

    def _compile_order_by_clause(
        self,
        group_expressions: list[_SelectedExpression],
        measure_expressions: list[tuple[str, str]],
    ) -> str:
        order_items = []
        time_items = [item for item in group_expressions if item.is_time]
        if time_items:
            order_items.extend(f"{self._quote_identifier(item.alias)} ASC" for item in time_items)
            order_items.extend(f"{self._quote_identifier(item.alias)} ASC" for item in group_expressions if not item.is_time)
        elif measure_expressions:
            order_items.append(f"{self._quote_identifier(measure_expressions[0][1])} DESC")
            order_items.extend(f"{self._quote_identifier(item.alias)} ASC" for item in group_expressions)
        if not order_items:
            order_items.extend(f"{self._quote_identifier(alias)} DESC" for _, alias in measure_expressions[:1])
        return "ORDER BY " + ", ".join(order_items)

    def _time_expression(self, field: PlannedField, time_grain: str | None, alias_by_entity: dict[str, str]) -> str:
        grain = time_grain or "day"
        if grain not in {"year", "quarter", "month", "day"}:
            raise SqlCompilationError(f"Unsupported time grain: {grain}")
        expression = self._qualified(field.entity, field.name, alias_by_entity)
        if grain == "day":
            return expression
        return f"DATE_TRUNC('{grain}', {expression})"

    def _semantic_measure(self, measure: PlannedMeasure) -> SemanticMeasure:
        entity = self._entity(measure.field.entity)
        if measure.field.kind != "measure":
            raise SqlCompilationError(f"Planned measure is not a measure field: {measure.field.field_id}")
        return entity.get_measure(measure.field.name)

    def _entity(self, entity_name: str) -> SemanticEntity:
        try:
            return self.semantic_model.entity(entity_name)
        except KeyError as exc:
            raise SqlCompilationError(f"Unknown entity: {entity_name}") from exc

    def _qualified(self, entity_name: str, field_name: str, alias_by_entity: dict[str, str]) -> str:
        if entity_name not in alias_by_entity:
            raise SqlCompilationError(f"Missing table alias for entity: {entity_name}")
        return f"{self._quote_identifier(alias_by_entity[entity_name])}.{self._quote_identifier(field_name)}"

    def _alias_for_field(self, field: PlannedField, suffix: str | None = None) -> str:
        alias = f"{field.entity}_{field.name}"
        if suffix:
            alias = f"{alias}_{suffix}"
        return alias

    def _measure_alias(self, measure: PlannedMeasure, used_aliases: set[str]) -> str:
        base = f"{measure.field.entity}_{measure.field.name}"
        if measure.role != "primary":
            base = f"{base}_{measure.role}"
        alias = base
        counter = 2
        while alias in used_aliases:
            alias = f"{base}_{counter}"
            counter += 1
        return alias

    def _quote_identifier(self, value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise SqlCompilationError(f"Unsafe identifier: {value}")
        return f'"{value}"'

    def _literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"


def compile_analysis_plan(
    plan: AnalysisPlan,
    semantic_model_path: str | Path | None = None,
    row_limit: int | None = None,
) -> CompiledQuery:
    model = load_semantic_model(semantic_model_path or DEFAULT_MODEL_PATH)
    return DuckDbSqlCompiler(model).compile(plan, row_limit=row_limit)
