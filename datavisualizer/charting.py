from __future__ import annotations

from typing import Any

from .contracts import AnalysisPlan, ChartSpec, ResultColumn


class ChartSpecGenerator:
    """Builds deterministic, renderer-agnostic chart metadata."""

    max_categories = 12
    max_grouped_categories = 8
    max_grouped_series = 6
    max_chart_columns = 5

    def generate(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...], rows: tuple[tuple[Any, ...], ...] = ()) -> ChartSpec:
        chart_type = plan.chart_intent.chart_type if plan.chart_intent else "table"
        base_warnings = self._shape_warnings(columns, rows)
        if base_warnings:
            return self._table(plan, columns, base_warnings)
        if chart_type == "line":
            return self._line(plan, columns, rows)
        if chart_type == "bar":
            return self._bar(plan, columns, rows)
        if chart_type == "grouped_bar":
            return self._grouped_bar(plan, columns, rows)
        return self._table(plan, columns)

    def _line(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...], rows: tuple[tuple[Any, ...], ...]) -> ChartSpec:
        time_column = self._first_column(columns, "time")
        measure_columns = self._columns_by_role(columns, "measure")
        dimensions = self._columns_by_role(columns, "dimension")
        warnings = []
        if time_column is None:
            warnings.append("Line chart requested without a time column.")
        if not measure_columns:
            warnings.append("Line chart needs at least one measure.")
        if warnings:
            return self._table(plan, columns, tuple(warnings))
        series = self._series_column(dimensions, rows, columns)
        return ChartSpec(
            chart_type="line",
            title=self._title(plan),
            x=time_column.name,
            y=tuple(column.name for column in measure_columns),
            series=series.name if series else None,
            columns=tuple(column.name for column in columns),
        )

    def _bar(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...], rows: tuple[tuple[Any, ...], ...]) -> ChartSpec:
        dimension = self._first_column(columns, "dimension")
        measure = self._first_column(columns, "measure")
        warnings = []
        if dimension is None or measure is None:
            warnings.append("Bar chart needs at least one dimension and one measure.")
        elif self._distinct_count(dimension, rows, columns) > self.max_categories:
            warnings.append("Bar chart has too many categories for the pilot renderer contract.")
        if warnings:
            return self._table(plan, columns, tuple(warnings))
        return ChartSpec(
            chart_type="bar",
            title=self._title(plan),
            x=dimension.name,
            y=(measure.name,),
            columns=tuple(column.name for column in columns),
        )

    def _grouped_bar(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...], rows: tuple[tuple[Any, ...], ...]) -> ChartSpec:
        dimensions = self._columns_by_role(columns, "dimension")
        measure_columns = self._columns_by_role(columns, "measure")
        warnings = []
        if not dimensions or not measure_columns:
            warnings.append("Grouped bar chart needs dimensions and measures.")
        elif len(columns) > self.max_chart_columns:
            warnings.append("Grouped bar chart has too many result columns for a reliable pilot visual.")
        elif self._distinct_count(dimensions[0], rows, columns) > self.max_grouped_categories:
            warnings.append("Grouped bar chart has too many x-axis categories for the pilot renderer contract.")
        series = dimensions[1] if len(dimensions) > 1 else None
        if series is not None and self._distinct_count(series, rows, columns) > self.max_grouped_series:
            warnings.append("Grouped bar chart has too many series for the pilot renderer contract.")
        if warnings:
            return self._table(plan, columns, tuple(warnings))
        return ChartSpec(
            chart_type="grouped_bar",
            title=self._title(plan),
            x=dimensions[0].name,
            y=tuple(column.name for column in measure_columns),
            series=series.name if series else None,
            columns=tuple(column.name for column in columns),
        )

    def _table(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...], warnings: tuple[str, ...] = ()) -> ChartSpec:
        return ChartSpec(
            chart_type="table",
            title=self._title(plan),
            columns=tuple(column.name for column in columns),
            warnings=warnings,
        )

    def _shape_warnings(self, columns: tuple[ResultColumn, ...], rows: tuple[tuple[Any, ...], ...]) -> tuple[str, ...]:
        if not rows:
            return ("Result set is empty; table view is safest.",)
        if len(columns) > self.max_chart_columns:
            return ("Result set is over-wide for the pilot chart contract.",)
        if self._sparse_rows(rows):
            return ("Result set is sparse; table view is safest.",)
        return ()

    def _sparse_rows(self, rows: tuple[tuple[Any, ...], ...]) -> bool:
        total_cells = sum(len(row) for row in rows)
        if total_cells == 0:
            return True
        empty_cells = sum(1 for row in rows for value in row if value is None or value == "")
        return empty_cells / total_cells > 0.4

    def _series_column(
        self,
        dimensions: tuple[ResultColumn, ...],
        rows: tuple[tuple[Any, ...], ...],
        columns: tuple[ResultColumn, ...],
    ) -> ResultColumn | None:
        for dimension in dimensions:
            distinct = self._distinct_count(dimension, rows, columns)
            if 1 < distinct <= self.max_grouped_series:
                return dimension
        return None

    def _distinct_count(self, column: ResultColumn, rows: tuple[tuple[Any, ...], ...], columns: tuple[ResultColumn, ...]) -> int:
        try:
            index = columns.index(column)
        except ValueError:
            return 0
        return len({row[index] for row in rows if index < len(row) and row[index] is not None})

    def _title(self, plan: AnalysisPlan) -> str:
        if plan.measures:
            measure_labels = ", ".join(measure.field.label for measure in plan.measures)
            return measure_labels
        return "Analysis Result"

    def _columns_by_role(self, columns: tuple[ResultColumn, ...], role: str) -> tuple[ResultColumn, ...]:
        return tuple(column for column in columns if column.role == role)

    def _first_column(self, columns: tuple[ResultColumn, ...], role: str) -> ResultColumn | None:
        for column in columns:
            if column.role == role:
                return column
        return None
