# DataVisualizer

`DataVisualizer` is the workspace for the next project in this folder tree.

## Current state

This repository now contains:

- imported synthetic pricing seed data from `PricingProject` under `data/`
- a reviewed pilot semantic model under `configs/semantic_models/`
- a minimal Python semantic query planner runtime under `datavisualizer/`
- a deterministic plan-to-SQL compiler and DuckDB execution harness
- an end-to-end compiled-plan answer pipeline with chart metadata
- a governed restricted-SQL gateway for future fallback tooling
- a provider-agnostic chat orchestrator with env-configured live LLM support
- a minimal single-page chat UI served by the existing Python backend
- a compact per-response inspection surface for query mode, plan, SQL, filters, entities, limits, warnings, and chart fallbacks
- a standard-library test suite under `tests/`

## Running the project

Run the minimal planner API from the repository root:

```powershell
py -3 -m datavisualizer.api
```

This starts both the API and the user-facing chat UI. Open `http://127.0.0.1:8000/` in a browser to use the SPA.

The server currently exposes:

- `GET /` for the minimal chat UI
- `POST /analysis-plan` for planning only
- `POST /answer` for the default compiled-plan answer path
- `POST /restricted-sql` for the separate governed restricted-SQL capability
- `POST /chat` for live-model orchestration over the governed backend tools

Every tool-facing endpoint returns a stable envelope with `ok`, `tool_name`, `data`, and `error`.

`/answer` returns explicit routing metadata, query mode, semantic result metadata, rows, true truncation status, structured warnings, and a renderer-agnostic chart spec. Chart specs are row-aware and may fall back to `table` when a visual shape is empty, sparse, too wide, or has too many categories. The UI inspector derives from this same payload rather than a separate debug endpoint.

`/chat` sits on top of the governed tools instead of replacing them. The orchestrator exposes:

- `answer` as the default analytics tool
- `restricted_sql` as a secondary governed tool when routing allows it and the request is clearly SQL-specific

The live provider adapter is env-configured and provider-agnostic. The current local setup supports an OpenRouter-backed OpenAI-compatible endpoint without hard-coding provider secrets into the repo.

The frontend stack is intentionally minimal:

- plain HTML, CSS, and browser JavaScript
- inline SVG rendering for `line`, `bar`, and `grouped_bar`
- grouped warning and fallback explanation rendering
- a collapsible "What did the system do?" inspector on each assistant answer
- no package manager
- no asset build step
- no separate frontend server

Run the test suite:

```powershell
py -3 -m unittest discover -s tests -t .
```

Run the env-gated live chat smoke tests only when live provider credentials are configured:

```powershell
$env:DATAVISUALIZER_RUN_LIVE_SMOKE="1"
py -3 -m unittest tests.test_chat.LiveChatSmokeTests
```

The answer pipeline is currently exposed through Python and the minimal HTTP API, not as a standalone CLI:

```python
from datavisualizer import AnswerService, ChatMessage, ChatOrchestrator, ChatRequest

service = AnswerService.from_default_model()
answer = service.answer("How do quoted discount rates and annualized quote amounts vary by product family and line role?")

orchestrator = ChatOrchestrator.from_env()
chat = orchestrator.chat_request(
    ChatRequest(messages=(ChatMessage(role="user", content="What is win rate by close month and account segment?"),))
)
```

The browser UI keeps the same governed flow:

1. user sends a message to `POST /chat`
2. `/chat` calls the live orchestrator
3. the orchestrator chooses governed backend tools
4. the UI renders assistant text, grouped warnings, chart spec, fallback reasons, result table, metadata, and inspector details
5. chart clicks send a selected-member drill payload back through `POST /chat`

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
- `datavisualizer/`: semantic-model loader, typed contracts, planner logic, SQL compiler, query gateway, answer service, execution harness, chart specs, LLM adapter, tool registry, chat orchestrator, UI contract and inspector helpers, static SPA assets, and minimal API
- `tests/`: stdlib planner, compiler, answer pipeline, restricted SQL, chat orchestration, UI contract, and API tests
- [AGENTS.md](AGENTS.md): concise repository instructions for agents
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution workflow, planning discipline, and verification expectations
- [TESTING.md](TESTING.md): test commands and validation expectations
- [README.md](README.md): project status and documentation index

## Query Safety

The default answer path is still `compiled_plan`: question -> `AnalysisPlan` -> deterministic SQL compiler -> execution. The restricted SQL gateway is a secondary governed capability for future LLM tooling. It accepts only a small validated `SELECT` subset over semantic-model entities and approved joins, enforces row limits, and rejects unsupported structure rather than repairing it.

`/answer` accepts explicit routing controls:

- `compiled_plan_only`
- `restricted_sql_allowed`

For this phase, `/answer` still selects the compiled-plan lane by default and reports that choice explicitly in the response.

The chat orchestrator preserves that posture. It uses live-model interpretation only to choose and parameterize governed tools. Tool execution itself remains deterministic and backend-controlled.

The user-facing SPA preserves the same posture. It renders governed results from `/chat`, displays warnings and fallback reasons clearly, shows active filters and SQL in a collapsible inspector, and uses selected-member drill payloads rather than any raw-query escape hatch.
