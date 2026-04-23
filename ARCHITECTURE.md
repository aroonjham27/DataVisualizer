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
6. `datavisualizer.query_gateway`
   The governed execution boundary with a default compiled-plan path and a restricted-SQL fallback service
7. `datavisualizer.answer`
   The end-to-end answer service that plans, compiles, executes, shapes results, and emits chart metadata
8. `datavisualizer.llm_client`
   A provider-agnostic live-model adapter plus a fake test client for deterministic orchestration tests
9. `datavisualizer.tool_registry`
   Explicit governed tool definitions and schemas for the default answer tool and the restricted-SQL tool
10. `datavisualizer.chat_orchestrator`
   The chat-layer coordinator that maintains conversation state, exposes governed tools to the model, executes tool calls deterministically, and returns structured assistant responses
11. `datavisualizer.api`
   The tool-facing HTTP boundary that exposes stable success/error envelopes for planning, default answer generation, restricted SQL, and chat orchestration
12. Future visualization layer
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
- Answers default to `compiled_plan` mode. Restricted SQL is a governed secondary boundary for future LLM tooling, not the primary route.
- The tool boundary is explicit: `/answer` is the default governed analytics tool, while restricted SQL is a separate governed capability.
- Tool requests carry explicit routing controls so a future orchestrator does not need to infer lane permissions.
- Chart specs are deterministic metadata for `line`, `bar`, `grouped_bar`, and `table`; rendering remains outside this repository. The generator inspects returned rows and falls back to tables for weak chart shapes.
- Restricted SQL is intentionally narrow: tokenized `SELECT` validation, semantic-model entities only, approved join edges only, read-only statements only, no direct file access, and gateway-enforced row limits.
- Query execution uses one-extra-row probing so answer metadata distinguishes returned rows from true truncation.
- API success and error envelopes are machine-friendly and stable for future tool-calling integration.
- The live-model layer is adapter-based: provider configuration comes from environment variables, the transport uses an OpenAI-compatible tool-calling shape, and OpenRouter is treated as a deploy-time endpoint choice rather than an architecture dependency.
- Tool registration is explicit: the model sees the governed `answer` tool and only sees `restricted_sql` when routing allows it and the user request is clearly SQL-oriented.
- Orchestration remains deterministic around tool execution: the model may choose among offered tools, but argument enrichment, execution, state updates, and response shaping stay backend-controlled.
- Conversation state is first-class: the orchestrator carries forward prior analysis context so follow-ups such as `go deeper`, `just enterprise`, `top 5`, and `show as table` can reuse governed state instead of reinterpreting the full task from scratch.

## Boundaries And Guardrails

- The semantic layer should prefer conformed dimensions such as `accounts` and `products` when possible.
- Quote-history facts (`price_snapshots`) and signed-contract facts (`contract_terms`) are both modeled, but they should not be mixed casually.
- Usage facts should flow through `contracts` or `accounts`, not be joined directly to opportunities.
- The pilot dataset is not treated as proof that every relationship is universal outside this seed.
- Restricted SQL should not be used when the compiled-plan path already supports the request.
- Restricted SQL does not support CTEs, subqueries, comma joins, cross joins, unions, arbitrary operators, or direct table-function/file access.
- Validation, unsupported-shape, and execution failures are normalized into distinct backend error types.
- Missing live-model credentials should fail gracefully at the orchestration boundary rather than crashing the backend or exposing secrets.

## Review Model

This v0 layer is a bootstrap artifact. Human review is expected before the model becomes the long-term contract for a visualization agent or BI surface.
