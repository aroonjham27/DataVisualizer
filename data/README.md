# Data

This directory contains the synthetic pricing dataset imported from `../PricingProject`.

## Imported contents

- `seed/`: the approved canonical CSV seed and its manifests copied from `PricingProject/data/seed/`
- `reports/`: the candidate evaluation reports copied from `PricingProject/data/reports/` because `seed/approval_manifest.json` references them

## Seed summary

The copied canonical seed preserves the source manifest values:

- dataset version: `module3_seed_v1`
- generation seed: `20260414`
- accounts: `1000`
- opportunities: `2715`
- contracts: `1060`
- products: `10`

See `seed/manifest.json` for the full row-count manifest.

## Scope notes

- The copied data is synthetic demo data from the pricing project, not production data.
- The development-only candidate dataset was not copied because the approved canonical seed is the stable dataset the source project uses for normal setup.
- The source project also uses DuckDB artifacts, but no database file was copied into this repository.
