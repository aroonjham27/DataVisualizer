# Semantic Review

## Confident Mappings

- `accounts` is the primary customer dimension keyed by `account_id`.
- `products` is the product dimension keyed by `product_id`.
- `opportunities` is the main commercial fact table at one row per opportunity.
- `opportunity_line_items` is the quote-line fact joined to opportunities and products.
- `price_snapshots` is a versioned quote-history fact joined to opportunities.
- `contracts` and `contract_terms` represent signed commercial structure at header and term-sequence grain.
- `usage_metrics` is a post-contract usage fact keyed by account, contract, product, and metric period.
- `opportunity_competitors` is a many-to-many bridge between opportunities and competitors.
- `win_loss_details` is outcome detail keyed by `opportunity_id`.

## Uncertain Mappings

- `opportunities.total_quote_amount`: present and useful, but not guaranteed to reconcile to line-item or snapshot totals.
- `opportunities.segment` and `opportunities.sales_region`: likely deal-time snapshots, but they duplicate account attributes and need governance guidance.
- `opportunity_competitors.price_positioning`: the comparison baseline is not spelled out in the seed.
- `usage_metrics.metric_value`: aggregatable only within a fixed `metric_name` and `metric_unit`.
- `contract_terms.annual_subscription_fee`: clearly annualized at term grain, but not a direct whole-contract total.
- Text fields such as `primary_win_reason`, `loss_reason_detail`, `decision_process_notes`, `capture_notes`, and `service_level_notes` are useful for drill-through but weak as governed dimensions.

## Recommended Human Review Items

- Confirm whether opportunity-level segment and region should ever override account-level segment and region in dashboards.
- Decide whether `total_quote_amount` or `price_snapshots.total_contract_value` should be the preferred quote metric for executive views.
- Confirm the intended meaning of `price_positioning` in competitive analysis.
- Decide whether text-heavy fields should stay analyst-only or become searchable semantic attributes.
- Review whether open pipeline will be added later, since the current pilot seed only contains closed opportunities.
- Decide whether a curated metric taxonomy is needed for `usage_metrics` before broader agent automation.

## Golden Questions

1. What is win rate by close month, account segment, sales region, and lifecycle type?
2. How do quoted discount rates and annualized quote amounts vary by product family and line role?
3. Which competitors appear most often in lost enterprise opportunities, and how are they positioned on price?
4. How do signed annual subscription fees and support fees vary by contract status, billing frequency, support tier, and term sequence?
5. How do active users and processed transactions trend over time by product family and customer segment after contract start?
