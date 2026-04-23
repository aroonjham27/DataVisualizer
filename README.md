# DataVisualizer

`DataVisualizer` is the workspace for the next project in this folder tree.

## Current state

This repository now contains:

- imported synthetic pricing seed data from `PricingProject` under `data/`
- a reviewed pilot semantic model under `configs/semantic_models/`
- a minimal Python semantic query planner runtime under `datavisualizer/`
- a deterministic plan-to-SQL compiler and DuckDB execution harness
- a standard-library test suite under `tests/`

## Running the project

Run the minimal planner API from the repository root:

```powershell
py -3 -m datavisualizer.api
```

Run the test suite:

```powershell
py -3 -m unittest discover -s tests -t .
```

The compiler is currently exposed as Python API, not as a standalone CLI:

```python
from datavisualizer import DuckDbSqlCompiler, SemanticPlanner, execute_compiled_query

planner = SemanticPlanner.from_default_model()
plan = planner.plan("How do quoted discount rates and annualized quote amounts vary by product family and line role?")
compiled = DuckDbSqlCompiler.from_default_model().compile(plan)
result = execute_compiled_query(compiled)
```

## Data

This repository includes the approved canonical synthetic seed copied from `../PricingProject/data/seed/` together with the evaluation reports referenced by the approval manifest.

- Read [data/README.md](data/README.md) for provenance and imported contents.
- The imported seed is synthetic demo data, not production customer data.

## Working in this repository

- Read [AGENTS.md](AGENTS.md) for short standing instructions for coding agents.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) for the change workflow and verification expectations used in this repo.
- Read [TESTING.md](TESTING.md) for the current validation workflow.

## Current layout

- [data/README.md](data/README.md): provenance and scope of the imported pricing seed
- `data/seed/`: approved canonical seed CSVs and manifests copied from `PricingProject`
- `data/reports/`: evaluation reports copied to preserve seed approval context
- `datavisualizer/`: semantic-model loader, typed planner contracts, planner logic, SQL compiler, execution harness, and minimal API
- `tests/`: stdlib planner and API tests
- [AGENTS.md](AGENTS.md): concise repository instructions for agents
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution workflow, planning discipline, and verification expectations
- [TESTING.md](TESTING.md): test commands and validation expectations
- [README.md](README.md): project status and documentation index
