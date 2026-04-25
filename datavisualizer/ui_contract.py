from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping, Sequence

from .contracts import ChartSpec, DrillSelection, PlannedField, ResultColumn


def row_records(columns: Sequence[ResultColumn], rows: Sequence[Sequence[Any]]) -> tuple[dict[str, Any], ...]:
    names = [column.name for column in columns]
    records = []
    for row in rows:
        record = {}
        for index, name in enumerate(names):
            record[name] = row[index] if index < len(row) else None
        records.append(record)
    return tuple(records)


def build_chart_view_model(
    chart_spec: ChartSpec,
    columns: Sequence[ResultColumn],
    rows: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    records = row_records(columns, rows)
    if chart_spec.chart_type == "table":
        return {
            "chart_type": "table",
            "columns": tuple(chart_spec.columns),
            "rows": records,
        }
    if chart_spec.chart_type == "bar":
        measure = chart_spec.y[0] if chart_spec.y else None
        return {
            "chart_type": "bar",
            "x": chart_spec.x,
            "y": tuple(chart_spec.y),
            "bars": tuple(
                {
                    "label": record.get(chart_spec.x or ""),
                    "value": record.get(measure) if measure else None,
                    "row_index": index,
                }
                for index, record in enumerate(records)
            ),
        }
    if chart_spec.chart_type == "grouped_bar":
        bars = []
        for index, record in enumerate(records):
            category = record.get(chart_spec.x or "")
            series_value = record.get(chart_spec.series) if chart_spec.series else None
            for measure_name in chart_spec.y:
                key = measure_name
                if series_value not in (None, ""):
                    key = f"{series_value}:{measure_name}"
                bars.append(
                    {
                        "category": category,
                        "series": key,
                        "value": record.get(measure_name),
                        "row_index": index,
                    }
                )
        return {
            "chart_type": "grouped_bar",
            "x": chart_spec.x,
            "series": chart_spec.series,
            "y": tuple(chart_spec.y),
            "bars": tuple(bars),
        }
    if chart_spec.chart_type == "line":
        x_values = _sorted_unique(record.get(chart_spec.x or "") for record in records)
        lines: dict[str, dict[str, dict[str, Any]]] = {}
        for index, record in enumerate(records):
            series_value = record.get(chart_spec.series) if chart_spec.series else None
            for measure_name in chart_spec.y:
                key = measure_name
                if series_value not in (None, ""):
                    key = f"{series_value}:{measure_name}"
                point = {
                    "x": record.get(chart_spec.x or ""),
                    "y": record.get(measure_name),
                    "row_index": index,
                }
                lines.setdefault(key, {})[str(point["x"])] = point
        return {
            "chart_type": "line",
            "x": chart_spec.x,
            "x_values": tuple(x_values),
            "series": chart_spec.series,
            "y": tuple(chart_spec.y),
            "lines": tuple(
                {
                    "key": key,
                    "points": tuple(point_by_x[str(x_value)] for x_value in x_values if str(x_value) in point_by_x),
                }
                for key, point_by_x in lines.items()
            ),
        }
    return {"chart_type": chart_spec.chart_type}


def build_selected_member(
    chart_spec: ChartSpec,
    columns: Sequence[ResultColumn],
    rows: Sequence[Sequence[Any]],
    row_index: int,
) -> DrillSelection | None:
    records = row_records(columns, rows)
    if row_index < 0 or row_index >= len(records):
        return None
    drill_column = _select_drill_column(chart_spec, columns)
    if drill_column is None:
        return None
    value = records[row_index].get(drill_column.name)
    if value in (None, ""):
        return None
    field_id = drill_column.semantic_lineage[0] if drill_column.semantic_lineage else ""
    if "." in field_id:
        entity, name = field_id.split(".", 1)
    else:
        entity = "unknown"
        name = drill_column.name
    kind = "time_dimension" if drill_column.role == "time" else drill_column.role
    return DrillSelection(
        field=PlannedField(entity=entity, name=name, label=drill_column.label, kind=kind),
        values=(value,),
        source="visual_member",
    )


def drill_selection_payload(
    chart_spec: ChartSpec,
    columns: Sequence[ResultColumn],
    rows: Sequence[Sequence[Any]],
    row_index: int,
) -> dict[str, Any] | None:
    selection = build_selected_member(chart_spec, columns, rows, row_index)
    return asdict(selection) if selection else None


def build_inspector_view_model(tool_data: Mapping[str, Any]) -> dict[str, Any]:
    """Shape an existing governed tool result for the UI inspector."""

    plan = _as_mapping(tool_data.get("plan"))
    query_metadata = _as_mapping(tool_data.get("query_metadata"))
    routing = _as_mapping(tool_data.get("routing"))
    limit = _as_mapping(tool_data.get("limit"))
    chart_spec = _as_mapping(tool_data.get("chart_spec"))
    filters = _filter_view_models(plan.get("filters", ()) if plan else ())
    warning_groups = _warning_groups(tool_data, chart_spec, query_metadata)
    return {
        "tool_name": tool_data.get("tool_name"),
        "query_mode": tool_data.get("query_mode"),
        "routing_policy": routing.get("policy") if routing else None,
        "sql": tool_data.get("sql", ""),
        "fallback_reason": tool_data.get("fallback_reason"),
        "applied_filters": filters,
        "involved_entities": tuple(query_metadata.get("involved_entities", ())) if query_metadata else (),
        "limit": {
            "row_limit": limit.get("row_limit") if limit else None,
            "returned_rows": limit.get("returned_rows") if limit else None,
            "truncated": bool(limit.get("truncated", False)) if limit else False,
        },
        "chart": {
            "chart_type": chart_spec.get("chart_type") if chart_spec else None,
            "title": chart_spec.get("title") if chart_spec else None,
            "fallback_reasons": tuple(chart_spec.get("warnings", ())) if chart_spec and chart_spec.get("chart_type") == "table" else (),
        },
        "analysis_plan": _analysis_plan_summary(plan),
        "warning_groups": warning_groups,
    }


def _select_drill_column(chart_spec: ChartSpec, columns: Sequence[ResultColumn]) -> ResultColumn | None:
    by_name = {column.name: column for column in columns}
    x_column = by_name.get(chart_spec.x or "")
    series_column = by_name.get(chart_spec.series or "") if chart_spec.series else None
    if x_column is not None and x_column.role == "dimension":
        return x_column
    if series_column is not None and series_column.role == "dimension":
        return series_column
    if x_column is not None:
        return x_column
    return series_column


def _sorted_unique(values: Iterable[Any]) -> tuple[Any, ...]:
    filtered = [value for value in values if value not in (None, "")]
    return tuple(sorted(dict.fromkeys(filtered), key=lambda value: str(value)))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _analysis_plan_summary(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    if not plan:
        return None
    return {
        "question": plan.get("question"),
        "status": plan.get("status"),
        "primary_entity": plan.get("primary_entity"),
        "measures": tuple(_field_id(item.get("field", {})) for item in plan.get("measures", ())),
        "dimensions": tuple(_field_id(item) for item in plan.get("dimensions", ())),
        "time_dimension": _field_id(plan.get("time_dimension")) if plan.get("time_dimension") else None,
        "time_grain": plan.get("time_grain"),
        "matched_terms": tuple(plan.get("matched_terms", ())),
    }


def _filter_view_models(filters: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    return tuple(_filter_view_model(filter_) for filter_ in filters)


def _filter_view_model(filter_: Any) -> dict[str, Any]:
    item = _as_mapping(filter_)
    field = _as_mapping(item.get("field"))
    value = item.get("value")
    operator = item.get("operator", "")
    value_text = ", ".join(str(part) for part in value) if isinstance(value, (list, tuple)) else str(value)
    label = field.get("label") or _field_id(field) or "Filter"
    return {
        "field_id": _field_id(field),
        "label": label,
        "operator": operator,
        "value": value,
        "source": item.get("source", "question"),
        "text": f"{label} {'=' if operator == '=' else str(operator).upper()} {value_text}",
    }


def _warning_groups(
    tool_data: Mapping[str, Any],
    chart_spec: Mapping[str, Any],
    query_metadata: Mapping[str, Any],
) -> dict[str, tuple[dict[str, Any], ...] | tuple[str, ...]]:
    grouped: dict[str, list[dict[str, Any]] | list[str]] = {
        "plan": [],
        "chart": [],
        "fallback": [],
        "routing": [],
        "query": [],
    }
    for warning in tool_data.get("warnings", ()):
        item = _as_mapping(warning)
        source = item.get("source", "query")
        normalized = {
            "code": item.get("code", ""),
            "source": source,
            "message": item.get("message", ""),
        }
        if source == "plan":
            grouped["plan"].append(normalized)  # type: ignore[union-attr]
        elif source == "chart":
            grouped["chart"].append(normalized)  # type: ignore[union-attr]
        else:
            grouped["query"].append(normalized)  # type: ignore[union-attr]

    if chart_spec.get("chart_type") == "table":
        for reason in chart_spec.get("warnings", ()):
            grouped["fallback"].append(str(reason))  # type: ignore[union-attr]

    for note in query_metadata.get("validation_notes", ()):
        text = str(note)
        if text.startswith("Active filter:"):
            continue
        if "routing" in text.lower() or "restricted sql was allowed" in text.lower():
            grouped["routing"].append(text)  # type: ignore[union-attr]
        else:
            grouped["query"].append({"code": "", "source": "query", "message": text})  # type: ignore[union-attr]

    return {key: tuple(value) for key, value in grouped.items()}


def _field_id(field: Any) -> str:
    item = _as_mapping(field)
    entity = item.get("entity")
    name = item.get("name")
    if entity and name:
        return f"{entity}.{name}"
    return ""
