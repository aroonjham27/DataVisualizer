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
- [x] Phase 2 chat orchestration completed
- [x] Phase 3 first chat UI completed
- [x] Phase 4 explainability and inspection completed
- [x] Phase 4.5 governed fallback orchestration hardening completed

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

- [x] Add a chat orchestrator service
- [x] Register the governed tools the model can call
- [x] Route normal analytics questions to `/answer`
- [x] Route only eligible advanced cases to restricted SQL
- [x] Preserve conversational context across turns
- [x] Handle follow-ups such as:
  - [x] "go deeper"
  - [x] "just enterprise"
  - [x] "top 5"
  - [x] "show as table"
- [x] Add structured-output schemas for tool calls and results
- [x] Add provider configuration behind a small adapter
- [x] Keep API key in env only, never repo
- [x] Keep orchestration provider-agnostic so OpenRouter is a transport choice, not an app architecture choice

---

## Phase 3: Chat UI

**Live LLM required:** Yes

Goal: provide the user-facing chat experience that renders both data and visuals.

- [x] Build chat thread UI
- [x] Render table + chart + explanation in one response surface
- [x] Add chart interaction hooks
- [x] Send selected-member drill payloads back to backend
- [x] Show warnings and semantic ambiguity clearly

---

## Phase 4: Explainability and inspection

**Live LLM required:** No additional model dependency beyond Phase 2

Goal: make the system transparent and trustworthy.

- [x] Add a "what did the system do?" panel
  - [x] plan used
  - [x] query mode used
  - [x] SQL executed
  - [x] filters applied
  - [x] entities involved
- [x] Add user-visible warning banners
- [x] Add chart fallback explanations

---

## Phase 4.5: Governed fallback orchestration hardening

**Live LLM required:** Yes for fallback SQL generation, No for deterministic routing tests

Goal: make restricted SQL available as an invisible governed fallback for valid analytics requests that the standard planner cannot fully cover.

- [x] Keep compiled-plan `/answer` as the first/default chat lane
- [x] Detect compiled-plan insufficiency before fallback
  - [x] planner fallback semantic match
  - [x] unsupported or incomplete review-needed states
  - [x] requested semantic fields missing from the plan
  - [x] unsupported chart/table fallback metadata
- [x] Ask for restricted SQL only through the existing governed tool schema
- [x] Provide only semantic entities, fields, approved joins, and safety rules to the fallback prompt
- [x] Preserve restricted SQL validation and gateway execution
- [x] Return compiled-plan output with warnings when fallback validation fails
- [x] Add transparent alternate governed query path messaging
- [x] Show fallback reason, SQL, entities, and limit metadata in the inspector
- [x] Cover routing behavior with deterministic fake-LLM golden tests

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
- [x] Restricted SQL exists as a safe secondary lane
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

Phase 4.5 is complete. Move next to **Phase 5**, focused on the product evaluation harness:

- [ ] curated benchmark question set
- [ ] multi-turn drill-down evaluation
- [ ] routing and fallback-quality evaluation
