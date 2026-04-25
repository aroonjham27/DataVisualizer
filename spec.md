# Phase 4.7 Trust Hardening Spec

## Task Summary

Fix two trust-critical orchestration bugs found during UI validation:

- restricted SQL fallback must canonicalize indexed filter values before execution
- new standalone analytics questions must not inherit stale analysis state from prior turns

## Goals

- Canonicalize low-cardinality restricted SQL filter values against governed seed values, not model casing.
- Reject unknown indexed restricted SQL filter values safely instead of returning misleading empty results.
- Detect explicit new standalone analytics requests when their requested measure or entity conflicts with the current analysis state.
- Preserve state for true follow-ups such as "go deeper", "top 5", "for enterprise only", and "plot the above".
- Constrain assistant prose with the returned governed payload so stale-state text cannot claim a different measure, filter, or chart type.
- Keep the existing Phase 4.6 visualization follow-up behavior intact.

## Non-Goals

- No LangGraph migration.
- No raw SQL input or SQL editor.
- No widening of the restricted SQL subset.
- No auth or permission model.
- No Phase 5 evaluation harness work.
- No broad UI redesign.

## Restricted SQL Value Policy

The restricted SQL gateway builds the same kind of low-cardinality value index used by the semantic planner. During validation it parses governed WHERE predicates, resolves the filtered field through the semantic entity or alias, and canonicalizes `=` and `IN` literals when the field is indexed.

Examples:

- `Enterprise`, `enterprise`, and `ENTERPRISE` all execute as the stored `enterprise` value.
- Indexed values such as `mid_market`, `analytics`, support tiers, regions, and pricing models are treated the same way.
- If a literal targets an indexed field but cannot be matched, validation rejects the SQL before execution.

## State Reset Policy

`/chat` still merges compact conversation state first. Before model tool selection, it now detects explicit standalone analytics requests and removes the current analysis plan and selected member from the active request state when the latest user message asks for a conflicting measure or entity.

Preserved as follow-up state:

- "Go one level deeper"
- "top 5"
- "for enterprise only"
- "show as table"
- "plot the above"

Reset as standalone analysis:

- current state is win rate on opportunities, latest request is line item count
- current state is opportunity win rate, latest request is contract count
- current state is a regional drill, latest request is analytics product line items

The prior result snapshot remains available for visualization follow-ups until a new governed result replaces it.

## Prose Consistency Policy

The model can still draft the final response, but the orchestrator checks the returned prose against the governed payload. If the text claims a measure, filter, or grouped-bar chart type not present in the payload, the orchestrator falls back to a deterministic payload-derived summary.

## Verification Plan

| Requirement | Proof Method |
|---|---|
| Restricted SQL `Enterprise`/`ENTERPRISE` filters return governed rows | Gateway and fake-LLM chat regression tests |
| Unknown indexed restricted SQL filter values reject before execution | Gateway validation regression test |
| New line-item question after win-rate drill does not reuse stale state | Fake-LLM multi-turn chat regression test |
| True "go deeper" follow-up still preserves mid-market state | Fake-LLM multi-turn chat regression test |
| "plot the above" still reuses prior restricted SQL result | Existing result-aware visualization regression test |
| Assistant prose cannot claim stale measure, filter, or chart type | Fake-LLM contradiction regression test |
