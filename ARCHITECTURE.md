# Architecture

## Role Of The Semantic Layer

The semantic layer is the contract between the imported pilot seed data and the future visualization agent.

Its job in this repository is to:

- name the business entities represented by the raw CSV files
- define safe measures, dimensions, time dimensions, and drill paths
- constrain which joins are allowed
- expose ambiguity explicitly so the agent does not treat guessed relationships as truth

It is not the final business model, a warehouse redesign, or a raw-SQL query implementation.

## System Placement

For the current repository, the system boundary is:

1. `data/seed/`
   The imported pilot dataset copied from `PricingProject`
2. `configs/semantic_models/pilot_pricing_v0.json`
   The reviewed semantic contract for that dataset
3. `datavisualizer.planner`
   The semantic query planner that maps user questions into structured analysis plans
4. `datavisualizer.sql_compiler`
   The deterministic compiler that maps supported analysis plans into read-only DuckDB SQL
5. `datavisualizer.execution`
   A minimal DuckDB execution harness for compiled read-only SQL
6. Future visualization layer
   Downstream components that should consume result data and chart intent rather than bypass the semantic model

The semantic layer and planner sit between raw data files and any automated analysis behavior. That keeps the first version reviewable by humans and reduces the risk of the agent inventing joins, measures, or drill paths.

## Design Choices For V0

- Entity-first, not SQL-first: the contract starts with grain, keys, measures, dimensions, and joins.
- Lean and extensible: only seed-backed tables and fields are modeled.
- Fact separation is preserved: opportunities, quote lines, price snapshots, contract terms, and usage are not collapsed into one reporting table.
- Ambiguity is surfaced: fields such as `total_quote_amount`, `metric_value`, and `price_positioning` are kept but marked for review.
- Planning is semantic-model-first: natural-language questions are resolved into analysis metadata before any SQL exists.
- Drill continuation carries semantic state, including the selected visual member when a follow-up is scoped to a clicked chart value.
- SQL compilation is plan-first: only supported `AnalysisPlan` shapes compile, and unsupported filters, grains, joins, or aggregations are rejected.

## Boundaries And Guardrails

- The semantic layer should prefer conformed dimensions such as `accounts` and `products` when possible.
- Quote-history facts (`price_snapshots`) and signed-contract facts (`contract_terms`) are both modeled, but they should not be mixed casually.
- Usage facts should flow through `contracts` or `accounts`, not be joined directly to opportunities.
- The pilot dataset is not treated as proof that every relationship is universal outside this seed.

## Review Model

This v0 layer is a bootstrap artifact. Human review is expected before the model becomes the long-term contract for a visualization agent or BI surface.
