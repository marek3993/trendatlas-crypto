# Repo Agent Rules

## Truth-First Read Order
Before any truth-sensitive repo task, read in this order:
1. `source_of_truth/README.md`
2. `source_of_truth/master_state.md`
3. `source_of_truth/chat_roles.md`
4. `source_of_truth/project_truth.json`
5. `source_of_truth/export_contract.json`
6. `source_of_truth/paths_registry.json`
7. `source_of_truth/current_issues.md`
8. `canonical/script_registry.json`
9. `canonical/output_registry.json`
10. `canonical/registry_workflow.md`

If the task touches Pi authority, execution runtime, scheduler, publish flow, or tablet/dashboard deployment, read `source_of_truth/pi_codex_runtime_workflow.md` before planning commands or edits.

## Contract-First Workflow
- Classify every non-trivial issue before patching:
  - `A` = wording/UI-only
  - `B` = runtime/data contract
  - `C` = execution/authority/scheduler
  - `D` = strategy math
- For classes `B`, `C`, and `D`, patch and validate the source contract first.
- Only after source validation may downstream consumers, dashboards, or wording be patched.
- Every recurring bug requires a regression test.
- A wording-only fix is allowed only for class `A`.

## Required Output
For non-trivial tasks, output:
- `FILES READ`
- `SOURCE OF TRUTH`
- exact root cause
- exact contract impact
- exact files changed
- regression test added/updated
- forbidden old path checked
- validation commands/results
- exact git add list
- commit message
- commit hash

If no commit was created, say so explicitly under `commit hash`.

## Semantic Guardrails
- Do not use `actual_held_asset`, `current_asset`, or `effective_market_exposure` as real wallet exposure.
- Do not use model equity or paper equity as real account PnL.
- Do not show model exposure as real account exposure.
- Do not let dashboards infer account state from model fields.

## Runtime and Commit Safety
- Pi repo root is `/opt/market_regime_v1`.
- `/opt/home_automation` is the home dashboard root for tablet/dashboard tasks only.
- Do not run long/full refresh unless explicitly approved.
- Do not run `--mode full-refresh` unless explicitly approved.
- Do not live order unless explicitly approved.
- Do not manually edit authority snapshots.
- Do not manually edit or commit generated `outputs/*` or `data/*` unless explicitly approved.
- For Pi authority work, follow only `source_of_truth/pi_codex_runtime_workflow.md`.
- On approved Pi publish work, always dry-run the `publish-existing` path before any real publish.
