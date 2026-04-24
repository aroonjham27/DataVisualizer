from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Sequence

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
