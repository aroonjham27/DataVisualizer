from __future__ import annotations

from .contracts import AnalysisPlan, ChartSpec, ResultColumn


class ChartSpecGenerator:
    """Builds deterministic, renderer-agnostic chart metadata."""

    def generate(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...]) -> ChartSpec:
        chart_type = plan.chart_intent.chart_type if plan.chart_intent else "table"
        if chart_type == "line":
            return self._line(plan, columns)
        if chart_type == "bar":
            return self._bar(plan, columns)
        if chart_type == "grouped_bar":
            return self._grouped_bar(plan, columns)
        return self._table(plan, columns)

    def _line(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...]) -> ChartSpec:
        time_column = self._first_column(columns, "time")
        measure_columns = self._columns_by_role(columns, "measure")
        dimensions = self._columns_by_role(columns, "dimension")
        return ChartSpec(
            chart_type="line",
            title=self._title(plan),
            x=time_column.name if time_column else None,
            y=tuple(column.name for column in measure_columns),
            series=dimensions[0].name if dimensions else None,
            columns=tuple(column.name for column in columns),
            warnings=() if time_column else ("Line chart requested without a time column; renderer should fall back to table.",),
        )

    def _bar(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...]) -> ChartSpec:
        dimension = self._first_column(columns, "dimension")
        measure = self._first_column(columns, "measure")
        return ChartSpec(
            chart_type="bar",
            title=self._title(plan),
            x=dimension.name if dimension else None,
            y=(measure.name,) if measure else (),
            columns=tuple(column.name for column in columns),
            warnings=() if dimension and measure else ("Bar chart needs at least one dimension and one measure.",),
        )

    def _grouped_bar(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...]) -> ChartSpec:
        dimensions = self._columns_by_role(columns, "dimension")
        measure_columns = self._columns_by_role(columns, "measure")
        return ChartSpec(
            chart_type="grouped_bar",
            title=self._title(plan),
            x=dimensions[0].name if dimensions else None,
            y=tuple(column.name for column in measure_columns),
            series=dimensions[1].name if len(dimensions) > 1 else None,
            columns=tuple(column.name for column in columns),
            warnings=() if dimensions and measure_columns else ("Grouped bar chart needs dimensions and measures.",),
        )

    def _table(self, plan: AnalysisPlan, columns: tuple[ResultColumn, ...]) -> ChartSpec:
        return ChartSpec(
            chart_type="table",
            title=self._title(plan),
            columns=tuple(column.name for column in columns),
        )

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
