# Semantic Layer Bootstrap Spec

## Task Summary

Create a v0 semantic layer for the pilot pricing seed in `DataVisualizer` so a visualization agent can reason over business entities, facts, dimensions, joins, and drill paths without starting from raw SQL.

## Goals

- Define a reviewed semantic contract from the imported seed data.
- Keep the model lean, explicit, and easy to extend.
- Separate confident mappings from uncertain ones.
- Document the role of the semantic layer in the local system.

## Non-Goals

- Building query-generation logic
- Declaring the model final or production-ready
- Inventing business definitions not supported by the seed or its source schema
- Creating a denormalized warehouse layer

## Evidence Base

- `data/seed/*.csv`
- `data/seed/manifest.json`
- `data/seed/approval_manifest.json`
- `data/reports/candidate_evaluation.{json,md}`
- Source schema provenance from `../PricingProject/src/pricing_foundation/schema.py`
- Source table intent from `../PricingProject/docs/schema.md`

## Working Assumptions

- The imported CSVs are the pilot dataset and are the local source of truth for v0 semantics.
- The source pricing project schema and schema docs are acceptable provenance for interpreting the copied field names.
- Ambiguous fields should be labeled as review-needed rather than normalized into strong semantic claims.

## Proposed Deliverables

- `ARCHITECTURE.md`
- `configs/semantic_models/pilot_pricing_v0.yaml`
- `SEMANTIC_REVIEW.md`

## Candidate Semantic Scope

- Core business entities: accounts, products, opportunities, contracts, competitors
- Fact-like entities: opportunity_line_items, price_snapshots, contract_terms, usage_metrics, opportunity_competitors, win_loss_details
- Explicit joins and drill hierarchies rooted in the observed foreign keys
- A small golden question set to validate semantic usefulness

## Risks And Edge Cases

- The pilot data only contains closed opportunities even though the source schema allows `open`.
- `parent_account_id` exists but is not populated in the pilot seed.
- Some numeric fields are sparse or context-dependent, especially `total_quote_amount`, `transaction_fee_per_unit`, and `metric_value`.
- Duplicate-looking business attributes appear at multiple grains, such as segment and sales region on both accounts and opportunities.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Semantic model is grounded in actual local data fields | Match model entities and fields against `data/seed` CSV headers |
| Join paths reflect observed relationships | Use copied schema provenance from `schema.py` and table-level row coverage checks |
| Ambiguities are explicit | Review model and `SEMANTIC_REVIEW.md` for flagged fields and assumptions |
| Documentation explains the semantic layer's role | Review `ARCHITECTURE.md` for system placement and scope boundaries |
| Model supports concrete visualization questions | Confirm golden question set maps to entities, joins, measures, and time dimensions in the model |
