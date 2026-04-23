# Contributing

This repository now contains a minimal Python runtime and a standard-library test workflow. Contributions should stay evidence-based, minimal, and explicit about what was and was not verified.

## Working principles

- Inspect before coding. Read the relevant files and existing docs before deciding on an approach.
- Choose simplicity first. Prefer the smallest change that solves the problem.
- Make surgical edits. Avoid unrelated refactors, cleanup, or new abstractions unless they are required.
- Verify before claiming success. Use the best available check for the current repo state and report the result honestly.
- Be clear about uncertainty. If something could not be tested, say so plainly.

## Default workflow

Use this workflow for non-trivial changes:

1. Restate the task and inspect the relevant repository context.
2. Decide the smallest viable approach before editing.
3. Create or update `spec.md` and `todo.md` when the work is complex enough to benefit from explicit planning and tracking.
4. Implement in small, reviewable steps.
5. Run the relevant checks before finishing.
6. Summarize what changed, what was verified, and any remaining uncertainty.

## Verification expectations

- Base verification on the tooling that actually exists in the repo.
- Document exact runnable commands in the repo docs when runtime or test workflows change.
- If no automated checks exist, record the manual validation performed instead of implying that the work was fully verified.

## Documentation maintenance

- Update existing docs before creating new ones.
- Keep `.gitignore` current when new local-only, generated, cache, build, or database artifacts appear.
- Keep `AGENTS.md` short and operational.
- Keep `TESTING.md` current when planner behavior, golden questions, or test commands change.
- Add `ARCHITECTURE.md` only when the codebase has enough structure or design tradeoffs to justify it.
