# DataVisualizer

`DataVisualizer` is the workspace for the next project in this folder tree.

## Current state

At the time this bootstrap documentation was written, this directory contains no application source, package manager files, test setup, build scripts, or Git metadata. It now does include imported synthetic pricing seed data from `PricingProject` under `data/`. The repository documentation therefore stays intentionally minimal and only describes workflows that are supported by the files currently present.

## Running the project

Run and setup instructions are not documented yet because no executable project structure or toolchain exists in this directory. Add stack-specific commands here once the project includes real runtime, build, or test configuration.

## Data

This repository includes the approved canonical synthetic seed copied from `../PricingProject/data/seed/` together with the evaluation reports referenced by the approval manifest.

- Read [data/README.md](data/README.md) for provenance and imported contents.
- The imported seed is synthetic demo data, not production customer data.

## Working in this repository

- Read [AGENTS.md](AGENTS.md) for short standing instructions for coding agents.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) for the change workflow and verification expectations used in this repo.

## Current layout

- [data/README.md](data/README.md): provenance and scope of the imported pricing seed
- `data/seed/`: approved canonical seed CSVs and manifests copied from `PricingProject`
- `data/reports/`: evaluation reports copied to preserve seed approval context
- [AGENTS.md](AGENTS.md): concise repository instructions for agents
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution workflow, planning discipline, and verification expectations
- [README.md](README.md): project status and documentation index
