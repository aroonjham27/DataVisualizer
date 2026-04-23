from __future__ import annotations

import csv
import re
from collections import deque
from dataclasses import replace
from pathlib import Path

from .contracts import (
    AnalysisPlan,
    ChartIntent,
    DrillSelection,
    DrillState,
    PlanJoinStep,
    PlannedField,
    PlannedFilter,
    PlannedMeasure,
)
from .semantic_model import DrillHierarchy, SemanticJoin, SemanticModel, load_semantic_model

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "configs" / "semantic_models" / "pilot_pricing_v0.json"


def _normalize(text: str) -> str:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _field_id(entity: str, name: str) -> str:
    return f"{entity}.{name}"


class SemanticPlanner:
    def __init__(self, semantic_model: SemanticModel):
        self.semantic_model = semantic_model
        self.value_index = self._build_value_index()
        self.join_graph = self._build_join_graph()

    @classmethod
    def from_default_model(cls) -> "SemanticPlanner":
        return cls(load_semantic_model(DEFAULT_MODEL_PATH))

    def plan(
        self,
        question: str,
        current_state: AnalysisPlan | None = None,
        selected_member: DrillSelection | None = None,
    ) -> AnalysisPlan:
        normalized = _normalize(question)
        if self._is_drill_continuation(normalized):
            return self._continue_drill(question, current_state, selected_member)
        return self._plan_initial(question, normalized)

    def _plan_initial(self, question: str, normalized_question: str) -> AnalysisPlan:
        if "win rate" in normalized_question:
            return self._plan_win_rate(question, normalized_question)
        if "competitor" in normalized_question or "competitors" in normalized_question:
            return self._plan_competitors(question, normalized_question)
        if "subscription fee" in normalized_question or "support fee" in normalized_question:
            return self._plan_contract_terms(question, normalized_question)
        if self._is_usage_question(normalized_question):
            return self._plan_usage(question, normalized_question)
        if "discount" in normalized_question or "annualized quote" in normalized_question or "quoted" in normalized_question:
            return self._plan_quote_mix(question, normalized_question)
        return self._plan_fallback(question, normalized_question)

    def _plan_win_rate(self, question: str, normalized_question: str) -> AnalysisPlan:
        measures = [self._measure("opportunities", "win_rate")]
        dimensions = []
        matched_terms = ["win rate"]
        warnings: list[str] = []
        if "account segment" in normalized_question:
            dimensions.append(self._dimension("accounts", "segment"))
            matched_terms.append("account segment")
        elif "segment" in normalized_question:
            dimensions.append(self._dimension("opportunities", "segment"))
            matched_terms.append("segment")
        if "sales region" in normalized_question:
            chosen = "opportunities"
            dimensions.append(self._dimension(chosen, "sales_region"))
            matched_terms.append("sales region")
            warnings.append("Resolved 'sales region' to opportunities.sales_region; account-level sales region is also available in the semantic model.")
        if "lifecycle type" in normalized_question:
            dimensions.append(self._dimension("opportunities", "lifecycle_type"))
            matched_terms.append("lifecycle type")
        time_dimension = None
        time_grain = None
        if "close month" in normalized_question or "close date" in normalized_question or "by month" in normalized_question:
            time_dimension = self._time_dimension("opportunities", "close_date")
            time_grain = "month"
            matched_terms.append("close month")
        filters: list[PlannedFilter] = []
        join_path = self._resolve_join_path("opportunities", dimensions, filters, time_dimension)
        drill = self._select_drill_state([*dimensions, *( [time_dimension] if time_dimension else [])], "opportunity_outcome")
        chart_intent = self._select_chart_intent(measures, dimensions, time_dimension, normalized_question)
        return self._build_plan(
            question=question,
            primary_entity="opportunities",
            measures=measures,
            dimensions=dimensions,
            time_dimension=time_dimension,
            time_grain=time_grain,
            filters=filters,
            join_path=join_path,
            drill=drill,
            chart_intent=chart_intent,
            matched_terms=matched_terms,
            warnings=warnings,
        )

    def _plan_quote_mix(self, question: str, normalized_question: str) -> AnalysisPlan:
        measures = [
            self._measure("opportunity_line_items", "annualized_amount", role="primary"),
            self._measure("opportunity_line_items", "average_discount_pct", role="comparison"),
        ]
        dimensions = []
        matched_terms = ["quoted", "discount"]
        if "product family" in normalized_question:
            dimensions.append(self._dimension("products", "product_family"))
            matched_terms.append("product family")
        if "line role" in normalized_question:
            dimensions.append(self._dimension("opportunity_line_items", "line_role"))
            matched_terms.append("line role")
        filters: list[PlannedFilter] = []
        join_path = self._resolve_join_path("opportunity_line_items", dimensions, filters, None)
        drill = self._select_drill_state(dimensions, "product_quote_mix")
        chart_intent = self._select_chart_intent(measures, dimensions, None, normalized_question)
        return self._build_plan(
            question=question,
            primary_entity="opportunity_line_items",
            measures=measures,
            dimensions=dimensions,
            time_dimension=None,
            time_grain=None,
            filters=filters,
            join_path=join_path,
            drill=drill,
            chart_intent=chart_intent,
            matched_terms=matched_terms,
            warnings=[],
        )

    def _plan_competitors(self, question: str, normalized_question: str) -> AnalysisPlan:
        measures = [self._measure("opportunity_competitors", "competitor_mention_count")]
        dimensions = [self._dimension("competitors", "competitor_name")]
        matched_terms = ["competitors"]
        if "price" in normalized_question or "positioned" in normalized_question:
            dimensions.append(self._dimension("opportunity_competitors", "price_positioning"))
            matched_terms.append("price positioning")
        filters = self._extract_filters(normalized_question, ["opportunity_competitors", "competitors", "opportunities"])
        join_path = self._resolve_join_path("opportunity_competitors", dimensions, filters, None)
        chart_intent = self._select_chart_intent(measures, dimensions, None, normalized_question)
        drill = self._select_drill_state(dimensions, "competitive_landscape")
        warnings = []
        if "price" in normalized_question:
            warnings.append("Competitive price positioning remains a review-needed semantic attribute in the v0 model.")
        return self._build_plan(
            question=question,
            primary_entity="opportunity_competitors",
            measures=measures,
            dimensions=dimensions,
            time_dimension=None,
            time_grain=None,
            filters=filters,
            join_path=join_path,
            drill=drill,
            chart_intent=chart_intent,
            matched_terms=matched_terms,
            warnings=warnings,
        )

    def _plan_contract_terms(self, question: str, normalized_question: str) -> AnalysisPlan:
        measures = [
            self._measure("contract_terms", "annual_subscription_fee", role="primary"),
            self._measure("contract_terms", "support_fee", role="comparison"),
        ]
        dimensions = []
        matched_terms = ["subscription fee", "support fee"]
        if "contract status" in normalized_question:
            dimensions.append(self._dimension("contracts", "contract_status"))
            matched_terms.append("contract status")
        if "billing frequency" in normalized_question:
            dimensions.append(self._dimension("contracts", "billing_frequency"))
            matched_terms.append("billing frequency")
        if "support tier" in normalized_question:
            dimensions.append(self._dimension("contract_terms", "support_tier"))
            matched_terms.append("support tier")
        if "term sequence" in normalized_question:
            dimensions.append(self._dimension("contract_terms", "term_sequence"))
            matched_terms.append("term sequence")
        filters: list[PlannedFilter] = []
        join_path = self._resolve_join_path("contract_terms", dimensions, filters, None)
        drill = self._select_drill_state(dimensions, "contract_structure")
        chart_intent = self._select_chart_intent(measures, dimensions, None, normalized_question)
        return self._build_plan(
            question=question,
            primary_entity="contract_terms",
            measures=measures,
            dimensions=dimensions,
            time_dimension=None,
            time_grain=None,
            filters=filters,
            join_path=join_path,
            drill=drill,
            chart_intent=chart_intent,
            matched_terms=matched_terms,
            warnings=[],
        )

    def _plan_usage(self, question: str, normalized_question: str) -> AnalysisPlan:
        measures: list[PlannedMeasure] = []
        matched_terms = []
        warnings: list[str] = []
        if "active users" in normalized_question:
            measures.append(
                self._measure(
                    "usage_metrics",
                    "metric_value",
                    role="primary",
                    local_filters=(self._filter("usage_metrics", "metric_name", "=", "active_users"),),
                )
            )
            matched_terms.append("active users")
        if "processed transactions" in normalized_question:
            role = "comparison" if measures else "primary"
            measures.append(
                self._measure(
                    "usage_metrics",
                    "metric_value",
                    role=role,
                    local_filters=(self._filter("usage_metrics", "metric_name", "=", "processed_transactions"),),
                )
            )
            matched_terms.append("processed transactions")
        if not measures:
            measures.append(self._measure("usage_metrics", "metric_value"))
        dimensions = []
        if "product family" in normalized_question:
            dimensions.append(self._dimension("products", "product_family"))
            matched_terms.append("product family")
        if "customer segment" in normalized_question or "account segment" in normalized_question:
            dimensions.append(self._dimension("accounts", "segment"))
            matched_terms.append("customer segment")
        time_dimension = self._time_dimension("usage_metrics", "metric_period_start")
        time_grain = "month"
        join_path = self._resolve_join_path("usage_metrics", dimensions, (), time_dimension)
        chart_intent = self._select_chart_intent(measures, dimensions, time_dimension, normalized_question)
        filters = []
        if "after contract start" in normalized_question:
            warnings.append("The planner did not add an explicit post-start filter because usage rows are already contract-linked; a later SQL compiler should decide whether a stricter date predicate is needed.")
            matched_terms.append("after contract start")
        drill = self._select_drill_state(dimensions + [time_dimension], "usage_by_product")
        return self._build_plan(
            question=question,
            primary_entity="usage_metrics",
            measures=measures,
            dimensions=dimensions,
            time_dimension=time_dimension,
            time_grain=time_grain,
            filters=filters,
            join_path=join_path,
            drill=drill,
            chart_intent=chart_intent,
            matched_terms=matched_terms,
            warnings=warnings,
        )

    def _plan_fallback(self, question: str, normalized_question: str) -> AnalysisPlan:
        matched_terms: list[str] = []
        best_entity = "opportunities"
        best_measure = self._measure("opportunities", "opportunity_count")
        best_score = 0
        question_terms = set(normalized_question.split())
        for entity in self.semantic_model.entities.values():
            for measure in entity.measures:
                candidate_terms = set(_normalize(measure.label).split()) | set(_normalize(measure.name).split())
                score = len(question_terms & candidate_terms)
                if score > best_score:
                    best_score = score
                    best_entity = entity.name
                    best_measure = self._measure(entity.name, measure.name)
        if best_score < 2:
            best_entity = "opportunities"
            best_measure = self._measure("opportunities", "opportunity_count")
        warnings = ["Planner used a fallback semantic match because no curated pilot pattern matched the question."]
        return self._build_plan(
            question=question,
            primary_entity=best_entity,
            measures=[best_measure],
            dimensions=[],
            time_dimension=None,
            time_grain=None,
            filters=[],
            join_path=[],
            drill=None,
            chart_intent=ChartIntent(chart_type="table", reason="Fallback plans default to a review-friendly table."),
            matched_terms=matched_terms,
            warnings=warnings,
        )

    def _continue_drill(
        self,
        question: str,
        current_state: AnalysisPlan | None,
        selected_member: DrillSelection | None = None,
    ) -> AnalysisPlan:
        if current_state is None:
            return self._build_plan(
                question=question,
                primary_entity="opportunities",
                measures=[self._measure("opportunities", "opportunity_count")],
                dimensions=[],
                time_dimension=None,
                time_grain=None,
                filters=[],
                join_path=[],
                drill=None,
                chart_intent=ChartIntent(chart_type="table", reason="No prior state was available for drill continuation."),
                matched_terms=[],
                warnings=["Drill continuation was requested, but no current analysis state was provided."],
            )
        if current_state.drill is None or current_state.drill.next_level is None:
            return replace(
                current_state,
                question=question,
                status="review_needed",
                warnings=current_state.warnings + ("No deeper drill level is available for the current analysis state.",),
            )
        active_selection = selected_member
        if active_selection is None and current_state.drill.selected_member is not None:
            active_selection = current_state.drill.selected_member
        next_field_id = current_state.drill.next_level
        next_field = self._field_from_field_id(next_field_id)
        updated_dimensions = list(current_state.dimensions)
        updated_filters = self._filters_with_selected_member(list(current_state.filters), active_selection)
        insert_at = len(updated_dimensions)
        current_drill_field_id = current_state.drill.levels[current_state.drill.current_level_index]
        for index, field in enumerate(updated_dimensions):
            if field.field_id == current_drill_field_id:
                insert_at = index + 1
                break
        if not any(field.field_id == next_field.field_id for field in updated_dimensions):
            updated_dimensions.insert(insert_at, next_field)
        hierarchy = self.semantic_model.drill_hierarchy(current_state.drill.hierarchy_name)
        new_depth = current_state.drill.current_level_index + 1
        next_level = hierarchy.levels[new_depth + 1] if new_depth + 1 < len(hierarchy.levels) else None
        updated_drill = DrillState(
            hierarchy_name=hierarchy.name,
            hierarchy_label=hierarchy.label,
            levels=hierarchy.levels,
            current_level_index=new_depth,
            next_level=next_level,
            selected_member=active_selection,
            is_continuation=True,
        )
        updated_join_path = self._resolve_join_path(
            current_state.primary_entity,
            updated_dimensions,
            updated_filters,
            current_state.time_dimension,
        )
        updated_chart = self._select_chart_intent(list(current_state.measures), updated_dimensions, current_state.time_dimension, _normalize(question))
        return AnalysisPlan(
            question=question,
            semantic_model_name=current_state.semantic_model_name,
            semantic_model_version=current_state.semantic_model_version,
            status="ok",
            primary_entity=current_state.primary_entity,
            measures=current_state.measures,
            dimensions=tuple(updated_dimensions),
            time_dimension=current_state.time_dimension,
            time_grain=current_state.time_grain,
            filters=tuple(updated_filters),
            join_path=tuple(updated_join_path),
            drill=updated_drill,
            chart_intent=updated_chart,
            warnings=current_state.warnings,
            matched_terms=current_state.matched_terms + ("drill continuation",),
            notes=current_state.notes + (f"Added drill level {next_field.field_id}.",),
        )

    def _build_plan(
        self,
        *,
        question: str,
        primary_entity: str,
        measures: list[PlannedMeasure],
        dimensions: list[PlannedField],
        time_dimension: PlannedField | None,
        time_grain: str | None,
        filters: list[PlannedFilter],
        join_path: list[PlanJoinStep],
        drill: DrillState | None,
        chart_intent: ChartIntent | None,
        matched_terms: list[str],
        warnings: list[str],
    ) -> AnalysisPlan:
        return AnalysisPlan(
            question=question,
            semantic_model_name=self.semantic_model.name,
            semantic_model_version=self.semantic_model.version,
            status="ok" if not warnings else "review_needed",
            primary_entity=primary_entity,
            measures=tuple(measures),
            dimensions=tuple(dimensions),
            time_dimension=time_dimension,
            time_grain=time_grain,
            filters=tuple(filters),
            join_path=tuple(join_path),
            drill=drill,
            chart_intent=chart_intent,
            warnings=tuple(warnings),
            matched_terms=tuple(dict.fromkeys(matched_terms)),
            notes=(),
        )

    def _measure(
        self,
        entity_name: str,
        measure_name: str,
        *,
        role: str = "primary",
        local_filters: tuple[PlannedFilter, ...] = (),
    ) -> PlannedMeasure:
        entity = self.semantic_model.entity(entity_name)
        measure = entity.get_measure(measure_name)
        return PlannedMeasure(
            field=PlannedField(entity=entity_name, name=measure.name, label=measure.label, kind="measure"),
            aggregation=measure.aggregation,
            local_filters=local_filters,
            role=role,
        )

    def _dimension(self, entity_name: str, dimension_name: str) -> PlannedField:
        dimension = self.semantic_model.entity(entity_name).get_dimension(dimension_name)
        return PlannedField(entity=entity_name, name=dimension.name, label=dimension.label, kind="dimension")

    def _time_dimension(self, entity_name: str, dimension_name: str) -> PlannedField:
        dimension = self.semantic_model.entity(entity_name).get_time_dimension(dimension_name)
        return PlannedField(entity=entity_name, name=dimension.name, label=dimension.label, kind="time_dimension")

    def _filter(self, entity_name: str, field_name: str, operator: str, value: object) -> PlannedFilter:
        field = self._field_from_field_id(_field_id(entity_name, field_name))
        return PlannedFilter(field=field, operator=operator, value=value)

    def _field_from_field_id(self, field_id: str) -> PlannedField:
        entity_name, field_name = field_id.split(".", 1)
        entity = self.semantic_model.entity(entity_name)
        for dimension in entity.dimensions:
            if dimension.name == field_name:
                return PlannedField(entity=entity_name, name=dimension.name, label=dimension.label, kind="dimension")
        for dimension in entity.time_dimensions:
            if dimension.name == field_name:
                return PlannedField(entity=entity_name, name=dimension.name, label=dimension.label, kind="time_dimension")
        for measure in entity.measures:
            if measure.name == field_name:
                return PlannedField(entity=entity_name, name=measure.name, label=measure.label, kind="measure")
        raise KeyError(f"Unknown semantic field: {field_id}")

    def _extract_filters(self, normalized_question: str, candidate_entities: list[str]) -> list[PlannedFilter]:
        filters: list[PlannedFilter] = []
        matches_by_value: dict[str, list[tuple[str, str, str]]] = {}
        for entity_name in candidate_entities:
            for field_name, values in self.value_index.get(entity_name, {}).items():
                for normalized_value, raw_value in values:
                    if normalized_value and re.search(rf"\b{re.escape(normalized_value)}\b", normalized_question):
                        matches_by_value.setdefault(normalized_value, []).append((entity_name, field_name, raw_value))
        for normalized_value, matches in matches_by_value.items():
            chosen_entity, chosen_field, raw_value = self._choose_filter_match(matches, candidate_entities, normalized_question)
            filters.append(self._filter(chosen_entity, chosen_field, "=", raw_value))
        deduped: dict[tuple[str, str, object], PlannedFilter] = {}
        for item in filters:
            deduped[(item.field.entity, item.field.name, item.value)] = item
        return list(deduped.values())

    def _choose_filter_match(
        self,
        matches: list[tuple[str, str, str]],
        candidate_entities: list[str],
        normalized_question: str,
    ) -> tuple[str, str, str]:
        preferred_order = list(candidate_entities)
        if "account segment" in normalized_question:
            preferred_order.insert(0, "accounts")
        for preferred_entity in preferred_order:
            for entity_name, field_name, raw_value in matches:
                if entity_name == preferred_entity:
                    return entity_name, field_name, raw_value
        return matches[0]

    def _resolve_join_path(
        self,
        primary_entity: str,
        dimensions: list[PlannedField],
        filters: list[PlannedFilter],
        time_dimension: PlannedField | None,
    ) -> list[PlanJoinStep]:
        target_entities = {field.entity for field in dimensions}
        target_entities.update(filter_.field.entity for filter_ in filters)
        if time_dimension is not None:
            target_entities.add(time_dimension.entity)
        target_entities.discard(primary_entity)
        steps: list[PlanJoinStep] = []
        seen: set[tuple[str, str, str]] = set()
        for target_entity in sorted(target_entities):
            for step in self._shortest_join_path(primary_entity, target_entity):
                signature = (step.left_entity, step.right_entity, step.traversal)
                if signature not in seen:
                    steps.append(step)
                    seen.add(signature)
        return steps

    def _shortest_join_path(self, start_entity: str, end_entity: str) -> list[PlanJoinStep]:
        if start_entity == end_entity:
            return []
        queue: deque[tuple[str, list[PlanJoinStep]]] = deque([(start_entity, [])])
        visited = {start_entity}
        while queue:
            current, path = queue.popleft()
            for neighbor, join, traversal in self.join_graph.get(current, ()):
                if neighbor in visited:
                    continue
                step = PlanJoinStep(
                    left_entity=join.left_entity,
                    right_entity=join.right_entity,
                    cardinality=join.cardinality,
                    traversal=traversal,
                    join_keys=join.join_keys,
                    notes=join.notes,
                )
                next_path = path + [step]
                if neighbor == end_entity:
                    return next_path
                visited.add(neighbor)
                queue.append((neighbor, next_path))
        raise ValueError(f"No allowed join path from {start_entity} to {end_entity}")

    def _build_join_graph(self) -> dict[str, list[tuple[str, SemanticJoin, str]]]:
        graph: dict[str, list[tuple[str, SemanticJoin, str]]] = {}
        for join in self.semantic_model.allowed_joins:
            graph.setdefault(join.left_entity, []).append((join.right_entity, join, "forward"))
            graph.setdefault(join.right_entity, []).append((join.left_entity, join, "reverse"))
        return graph

    def _select_drill_state(self, fields: list[PlannedField], preferred_hierarchy_name: str | None = None) -> DrillState | None:
        hierarchies = (
            [self.semantic_model.drill_hierarchy(preferred_hierarchy_name)]
            if preferred_hierarchy_name
            else list(self.semantic_model.drill_hierarchies)
        )
        field_ids = {field.field_id for field in fields}
        best: tuple[int, DrillHierarchy] | None = None
        for hierarchy in hierarchies:
            prefix_length = 0
            for level in hierarchy.levels:
                if level in field_ids:
                    prefix_length += 1
                else:
                    break
            if prefix_length > 0 and (best is None or prefix_length > best[0]):
                best = (prefix_length, hierarchy)
        if best is None:
            return None
        prefix_length, hierarchy = best
        current_level_index = prefix_length - 1
        next_level = hierarchy.levels[prefix_length] if prefix_length < len(hierarchy.levels) else None
        return DrillState(
            hierarchy_name=hierarchy.name,
            hierarchy_label=hierarchy.label,
            levels=hierarchy.levels,
            current_level_index=current_level_index,
            next_level=next_level,
            is_continuation=False,
        )

    def _select_chart_intent(
        self,
        measures: list[PlannedMeasure],
        dimensions: list[PlannedField],
        time_dimension: PlannedField | None,
        normalized_question: str,
    ) -> ChartIntent:
        if time_dimension is not None:
            return ChartIntent(chart_type="line", reason="A time dimension is present, so a trend-oriented chart is the safest default.")
        if len(measures) > 1 and len(dimensions) <= 2:
            return ChartIntent(chart_type="grouped_bar", reason="Multiple measures across a small set of dimensions fit a grouped comparison chart.")
        if "most" in normalized_question or "which" in normalized_question:
            return ChartIntent(chart_type="bar", reason="The question asks for a ranked comparison across categories.")
        if len(dimensions) >= 3:
            return ChartIntent(chart_type="table", reason="The plan includes several grouping dimensions, so a table is the most stable initial answer.")
        return ChartIntent(chart_type="bar", reason="A categorical comparison without time is best represented as a bar chart.")

    def _is_drill_continuation(self, normalized_question: str) -> bool:
        phrases = (
            "go one level deeper",
            "one level deeper",
            "go deeper",
            "drill down",
            "drill one level",
        )
        return any(phrase in normalized_question for phrase in phrases)

    def _is_usage_question(self, normalized_question: str) -> bool:
        usage_terms = (
            "active users",
            "processed transactions",
            "usage",
            "consumption",
            "metric value",
            "metric values",
        )
        return any(term in normalized_question for term in usage_terms)

    def _filters_with_selected_member(
        self,
        filters: list[PlannedFilter],
        selected_member: DrillSelection | None,
    ) -> list[PlannedFilter]:
        if selected_member is None:
            return filters
        operator = "=" if len(selected_member.values) == 1 else "in"
        value: object
        if len(selected_member.values) == 1:
            value = selected_member.values[0]
        else:
            value = selected_member.values
        selected_filter = PlannedFilter(
            field=selected_member.field,
            operator=operator,
            value=value,
            source=selected_member.source,
        )
        existing = {
            (filter_.field.field_id, filter_.operator, str(filter_.value), filter_.source)
            for filter_ in filters
        }
        signature = (
            selected_filter.field.field_id,
            selected_filter.operator,
            str(selected_filter.value),
            selected_filter.source,
        )
        if signature in existing:
            return filters
        return [*filters, selected_filter]

    def _build_value_index(self) -> dict[str, dict[str, list[tuple[str, str]]]]:
        index: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for entity in self.semantic_model.entities.values():
            source_path = self.semantic_model.source_path_for_entity(entity.name)
            if not source_path.exists():
                continue
            with source_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                distinct_values: dict[str, set[str]] = {field.name: set() for field in entity.dimensions}
                for row in reader:
                    for field in entity.dimensions:
                        value = (row.get(field.name) or "").strip()
                        if value:
                            distinct_values[field.name].add(value)
                indexed_fields: dict[str, list[tuple[str, str]]] = {}
                for field_name, values in distinct_values.items():
                    filtered_values = []
                    if 0 < len(values) <= 12:
                        for value in sorted(values):
                            if value.lower() in {"true", "false"}:
                                continue
                            filtered_values.append((_normalize(value), value))
                    if filtered_values:
                        indexed_fields[field_name] = filtered_values
                if indexed_fields:
                    index[entity.name] = indexed_fields
        return index
