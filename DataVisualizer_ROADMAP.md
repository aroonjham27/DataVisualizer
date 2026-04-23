# DataVisualizer Roadmap

This roadmap tracks the path from the current pilot backend to a chat-first visualization agent.

## Current completion status

- [x] Repo bootstrap and working docs
- [x] Pilot seed data imported and documented
- [x] v0 semantic layer created
- [x] Deterministic semantic planner created
- [x] Drill continuation and selected-member drill context added
- [x] Deterministic DuckDB SQL compiler created
- [x] Read-only execution harness added
- [x] End-to-end `/answer` pipeline added
- [x] Deterministic chart spec generation added
- [x] Governed restricted SQL gateway added
- [x] Truncation detection improved with one-extra-row probing
- [x] Tests covering planning, compilation, execution, answer generation, restricted SQL, and HTTP round-trips added
- [x] Stable tool-facing success/error envelopes added
- [x] Explicit routing controls added
- [x] Phase 1 tool boundary completed

---

## Phase 1: LLM-facing tool boundary

**Live LLM required:** No

Goal: make the backend clean and stable for future model tool-calling.

- [x] Define a clean tool contract for the future model-facing layer
  - [x] `/answer` as the default governed analytics tool
  - [x] restricted SQL as a separate governed capability
- [x] Add a first-class error contract
  - [x] validation error
  - [x] unsupported query shape
  - [x] execution failure
- [x] Add explicit routing flags
  - [x] compiled-plan only
  - [x] restricted-SQL allowed
- [x] Normalize answer payloads for model consumption
  - [x] stable field names
  - [x] stable warnings
  - [x] stable chart spec contract

---

## Phase 2: Chat orchestration layer

**Live LLM required:** Yes  
**This is where live LLM usage starts.**

Goal: let the model interpret user intent, choose governed tools, and manage multi-turn analytics conversation.

- [ ] Add a chat orchestrator service
- [ ] Register the governed tools the model can call
- [ ] Route normal analytics questions to `/answer`
- [ ] Route only eligible advanced cases to restricted SQL
- [ ] Preserve conversational context across turns
- [ ] Handle follow-ups such as:
  - [ ] "go deeper"
  - [ ] "just enterprise"
  - [ ] "top 5"
  - [ ] "show as table"
- [ ] Add structured-output schemas for tool calls and results
- [ ] Add provider configuration behind a small adapter
- [ ] Keep API key in env only, never repo
- [ ] Keep orchestration provider-agnostic so OpenRouter is a transport choice, not an app architecture choice

---

## Phase 3: Chat UI

**Live LLM required:** Yes

Goal: provide the user-facing chat experience that renders both data and visuals.

- [ ] Build chat thread UI
- [ ] Render table + chart + explanation in one response surface
- [ ] Add chart interaction hooks
- [ ] Send selected-member drill payloads back to backend
- [ ] Show warnings and semantic ambiguity clearly

---

## Phase 4: Explainability and inspection

**Live LLM required:** No additional model dependency beyond Phase 2

Goal: make the system transparent and trustworthy.

- [ ] Add a "what did the system do?" panel
  - [ ] plan used
  - [ ] query mode used
  - [ ] SQL executed
  - [ ] filters applied
  - [ ] entities involved
- [ ] Add user-visible warning banners
- [ ] Add chart fallback explanations

---

## Phase 5: Product evaluation harness

**Live LLM required:** Yes for orchestration evaluation, No for deterministic backend checks

Goal: measure correctness, routing quality, and conversational stability.

- [ ] Curated benchmark question set
- [ ] Multi-turn drill-down evaluation
- [ ] Routing evaluation
  - [ ] compiled-plan chosen correctly
  - [ ] restricted SQL chosen only when justified
- [ ] Empty-result and ambiguous-question evaluation
- [ ] Regression suite for chat answers and charts

---

## MVP completion criteria

MVP is complete when all of the following are true:

- [ ] User can ask a business question in chat
- [ ] System returns governed data + chart + explanation
- [ ] User can drill by chat or chart click
- [ ] Compiled-plan is the default reliable path
- [ ] Restricted SQL exists as a safe secondary lane
- [ ] Core flows are tested and demo-stable

---

## Post-MVP: production completion

### Data and semantic expansion

- [ ] Semantic layer v1 refinement
- [ ] Better synonyms and business definitions
- [ ] Richer chart hints
- [ ] Semantic onboarding flow for new datasets

### Connector expansion

- [ ] Move beyond DuckDB/CSV pilot execution
- [ ] Add real backend connector abstraction
- [ ] Preserve the same answer/tool contract

### Governance and security

- [ ] Auth and user/session model
- [ ] Data-source permissions
- [ ] Query-mode permissions
- [ ] Audit logging
- [ ] Stronger restricted-SQL validation boundary

### Performance and operations

- [ ] Caching
- [ ] Latency monitoring
- [ ] Failure monitoring
- [ ] Deployment pipeline
- [ ] Rollback and support playbooks

---

## Suggested immediate next task

Phase 1 is complete. Move next to **Phase 2**, where the live LLM begins:

- [ ] chat orchestrator service
- [ ] governed tool registration
- [ ] safe routing between compiled-plan and restricted SQL
