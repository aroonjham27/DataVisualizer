# Candidate Seed Evaluation

- Status: `pass`
- Passed checks: `39/39`
- Critical passed: `True`
- Non-critical pass rate: `1.0`
- Win rate: `0.4`

## Failing Checks

All configured checks passed.

## Profiling Outputs

### Counts By Segment

| segment | opportunity_count | share |
| --- | --- | --- |
| enterprise | 786 | 0.2895 |
| mid_market | 677 | 0.2494 |
| smb | 680 | 0.2505 |
| strategic | 572 | 0.2107 |

### Counts By Region

| sales_region | opportunity_count | share |
| --- | --- | --- |
| apac | 529 | 0.1948 |
| emea | 731 | 0.2692 |
| latam | 250 | 0.0921 |
| na | 1205 | 0.4438 |

### Deal Outcomes

| outcome | opportunity_count |
| --- | --- |
| lost | 1629 |
| won | 1086 |

### Contract Length Distribution

| contract_length_months | opportunity_count |
| --- | --- |
| 12 | 813 |
| 24 | 750 |
| 36 | 525 |
| 48 | 232 |
| 60 | 117 |

### Total Contract Value Distribution

| avg_tcv | stddev_tcv | p10_tcv | p50_tcv | p90_tcv |
| --- | --- | --- | --- | --- |
| 1291787.93 | 2056001.37 | 37420.42 | 347181.62 | 3711333.82 |

### Loss Reasons

| primary_loss_reason | opportunity_count |
| --- | --- |
| price | 306 |
| competitor | 225 |
| missing | 209 |
| no_decision | 186 |
| weak_champion_internal_politics | 176 |
| procurement_legal_friction | 139 |
| product_gap | 132 |
| budget | 130 |
| timing | 126 |

### Competitor Frequency

| competitor_name | capture_count |
| --- | --- |
| GlobalFlow | 777 |
| ShipChain Pro | 735 |
| TradeMatrix | 730 |
| RouteSphere | 625 |
| CustomsPilot | 581 |
| PortVision | 573 |

### Won vs Lost Completeness

| outcome | avg_completeness |
| --- | --- |
| lost | 0.4709 |
| won | 0.9198 |

### Discount and Competitor Pressure Patterns

| pressure_bucket | avg_final_discount | win_rate |
| --- | --- | --- |
| low | 9.92 | 0.6477 |
| medium | 15.06 | 0.3523 |
| high | 20.75 | 0.1921 |

### Renewal vs Net New vs Expansion

| lifecycle_type | win_rate | high_complexity_share |
| --- | --- | --- |
| expansion | 0.2438 | 0.4992 |
| net_new | 0.1204 | 0.4684 |
| renewal | 0.9631 | 0.3325 |

### Discount By Lifecycle

| lifecycle_type | avg_observed_discount |
| --- | --- |
| expansion | 16.0 |
| net_new | 14.82 |
| renewal | 13.6 |

## Human Sanity Check

### Sample Won Deals

| opportunity_external_id | account_name | segment | sales_region | lifecycle_type | contract_length_months | total_quote_amount | support_tier_requested | primary_win_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OPP-00366 | Bluewave Industrial | strategic | na | renewal | 60 | 12791021.44 | premium | Best workflow match for cross-border operations |
| OPP-00468 | Harbor Supply Co | strategic | latam | net_new | 48 | 12483627.44 | enterprise | Incumbent relationship and lower switching risk |
| OPP-00196 | Northstar Commerce Partners | strategic | apac | expansion | 60 | 11465661.8 | premium | Best workflow match for cross-border operations |
| OPP-00121 | Ironwood Distribution | strategic | na | expansion | 60 | 11143915.87 | premium | Best workflow match for cross-border operations |
| OPP-01410 | Summit Supply Co | strategic | na | renewal | 60 | 11019173.0 | enterprise | Global rollout fit and clear ROI case |

### Sample Lost Deals

| opportunity_external_id | account_name | segment | sales_region | lifecycle_type | contract_length_months | total_quote_amount | competitor_pressure_score | primary_loss_reason | loss_reason_detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OPP-00263 | Atlas Global Freight | enterprise | apac | net_new | 48 | 1584146.33 | 0.9 | timing | None |
| OPP-00302 | Apex Distribution | enterprise | emea | expansion | 36 | 1005152.91 | 0.9 | competitor | None |
| OPP-00381 | Northstar Distribution | enterprise | na | net_new | 24 | 1025871.26 | 0.9 | price | pricing came in above internal threshold after procurement review |
| OPP-01349 | Granite Global Freight | enterprise | na | net_new | 12 | 645592.52 | 0.9 | None | project paused after steering committee could not commit |
| OPP-01375 | Atlas Global Freight | enterprise | na | net_new | 36 | 2375583.04 | 0.9 | procurement_legal_friction | None |

