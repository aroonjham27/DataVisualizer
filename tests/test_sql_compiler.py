from __future__ import annotations

import unittest
from dataclasses import replace

from datavisualizer.contracts import DrillSelection, PlannedFilter
from datavisualizer.execution import SqlExecutionError, execute_compiled_query
from datavisualizer.planner import SemanticPlanner
from datavisualizer.sql_compiler import DuckDbSqlCompiler, SqlCompilationError


class SqlCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner = SemanticPlanner.from_default_model()
        cls.compiler = DuckDbSqlCompiler.from_default_model(default_limit=25)

    def test_compiles_win_rate_with_time_bucket_and_account_join(self) -> None:
        plan = self.planner.plan("What is win rate by close month, account segment, sales region, and lifecycle type?")

        compiled = self.compiler.compile(plan)

        self.assertIn("read_csv_auto", compiled.sql)
        self.assertIn('DATE_TRUNC(\'month\', "t0"."close_date") AS "opportunities_close_date_month"', compiled.sql)
        self.assertIn('LEFT JOIN "accounts" AS "t1" ON "t1"."account_id" = "t0"."account_id"', compiled.sql)
        self.assertIn("COUNT(DISTINCT CASE WHEN", compiled.sql)
        self.assertIn("GROUP BY", compiled.sql)
        self.assertIn("LIMIT 25", compiled.sql)

    def test_compiles_semantic_resolved_direct_win_rate_dimensions(self) -> None:
        plan = self.planner.plan("What is the win rate by close month, industry, and region for enterprise?")

        compiled = self.compiler.compile(plan)

        self.assertIn('"t1"."industry" AS "accounts_industry"', compiled.sql)
        self.assertIn('"t0"."sales_region" AS "opportunities_sales_region"', compiled.sql)
        self.assertIn('WHERE "t0"."segment" = \'enterprise\'', compiled.sql)
        self.assertIn('GROUP BY "t1"."industry", "t0"."sales_region", DATE_TRUNC', compiled.sql)

    def test_compiles_semantic_resolved_drill_target_dimension(self) -> None:
        initial = self.planner.plan("What is win rate by close month for enterprise?")
        follow_up = self.planner.plan("Go one level deeper to region", current_state=initial)

        compiled = self.compiler.compile(follow_up)

        self.assertIn('"t0"."sales_region" AS "opportunities_sales_region"', compiled.sql)
        self.assertIn('WHERE "t0"."segment" = \'enterprise\'', compiled.sql)
        self.assertIn('GROUP BY "t0"."sales_region", DATE_TRUNC', compiled.sql)

    def test_compiles_semantic_resolved_product_follow_up_dimension(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        follow_up = self.planner.plan("break it down by pricing model", current_state=initial)

        compiled = self.compiler.compile(follow_up)

        self.assertIn('"t1"."pricing_model" AS "products_pricing_model"', compiled.sql)
        self.assertIn('"products" AS "t1"', compiled.sql)
        self.assertIn('"t1"."pricing_model"', compiled.sql)

    def test_compiles_measure_local_filters_for_usage_metrics(self) -> None:
        plan = self.planner.plan(
            "How do active users and processed transactions trend over time by product family and customer segment after contract start?"
        )

        compiled = self.compiler.compile(plan, row_limit=10)

        self.assertIn("CASE WHEN", compiled.sql)
        self.assertIn('"t0"."metric_name" = \'active_users\'', compiled.sql)
        self.assertIn('"t0"."metric_name" = \'processed_transactions\'', compiled.sql)
        self.assertIn('LEFT JOIN "accounts"', compiled.sql)
        self.assertIn('LEFT JOIN "products"', compiled.sql)
        self.assertIn("LIMIT 10", compiled.sql)

    def test_compiles_selected_member_drill_filter(self) -> None:
        initial = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        selected_member = DrillSelection(field=initial.dimensions[0], values=("analytics",))
        drill_plan = self.planner.plan("Go one level deeper", current_state=initial, selected_member=selected_member)

        compiled = self.compiler.compile(drill_plan)

        self.assertIn('WHERE "t1"."product_family" = \'analytics\'', compiled.sql)
        self.assertIn('"t1"."product_name" AS "products_product_name"', compiled.sql)

    def test_executes_compiled_quote_mix_query(self) -> None:
        plan = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        compiled = self.compiler.compile(plan, row_limit=20)

        result = execute_compiled_query(compiled)

        self.assertGreater(len(result.rows), 0)
        self.assertIn("products_product_family", result.columns)
        self.assertIn("opportunity_line_items_annualized_amount", result.columns)

    def test_executes_compiled_win_rate_query(self) -> None:
        plan = self.planner.plan("What is win rate by close month, account segment, sales region, and lifecycle type?")
        compiled = self.compiler.compile(plan, row_limit=20)

        result = execute_compiled_query(compiled)

        self.assertGreater(len(result.rows), 0)
        self.assertIn("opportunities_win_rate", result.columns)

    def test_rejects_unsupported_filter_operator(self) -> None:
        plan = self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
        bad_filter = PlannedFilter(field=plan.dimensions[0], operator="contains", value="analytics")
        bad_plan = replace(plan, filters=(bad_filter,))

        with self.assertRaises(SqlCompilationError):
            self.compiler.compile(bad_plan)

    def test_rejects_unsupported_time_grain(self) -> None:
        plan = self.planner.plan("What is win rate by close month, account segment, sales region, and lifecycle type?")
        bad_plan = replace(plan, time_grain="week")

        with self.assertRaises(SqlCompilationError):
            self.compiler.compile(bad_plan)

    def test_executor_rejects_non_read_sql(self) -> None:
        compiled = replace(self.compiler.compile(self.planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")), sql="DROP TABLE accounts")

        with self.assertRaises(SqlExecutionError):
            execute_compiled_query(compiled)


if __name__ == "__main__":
    unittest.main()
