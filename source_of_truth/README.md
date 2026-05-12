# Market Regime v1 - Source of Truth

This folder is the central single source of truth layer for Market Regime v1.

## Human-readable files
- `master_state.md` = short official state snapshot
- `chat_roles.md` = role boundaries and workflow rules for segmented chats
- `current_issues.md` = open blockers and accepted current-state notes
- `pi_codex_runtime_workflow.md` = approved Pi/Codex runtime authority runbook for publish-existing, dry-run-first, and tablet/dashboard root boundaries

## Machine-readable files
- `project_truth.json` = main official project truth
- `live_truth.json` = live/source-of-truth layer for the current model state
- `export_contract.json` = official app/execution/dashboard export contract
- `paths_registry.json` = registry of important repo paths
- `decisions_log.jsonl` = decision audit trail
- `experiments_registry.csv` = experiments registry

## Required read order for truth-sensitive work
1. `source_of_truth/README.md`
2. `source_of_truth/master_state.md`
3. `source_of_truth/chat_roles.md`
4. `source_of_truth/project_truth.json`
5. `source_of_truth/export_contract.json`
6. `source_of_truth/paths_registry.json`
7. `source_of_truth/current_issues.md`

## Required add-on read for Pi/runtime authority work
- After the base truth read order above, read `source_of_truth/pi_codex_runtime_workflow.md` before any Pi authority, scheduler, publish-existing, recovery, or tablet/dashboard task.

## Repo-wide contract-first discipline
- Every non-trivial bug must be classified before patching:
  - `A` = wording/UI-only
  - `B` = runtime/data contract
  - `C` = execution/authority/scheduler
  - `D` = strategy math
- If the bug is `B`, `C`, or `D`, do not start with a UI patch.
- For `B`, `C`, and `D`, patch and validate the source contract first.
- Only after the source contract is validated may downstream consumers, dashboards, or wording be patched.
- Required normalized public/runtime contracts:
  - `real_account_state`
  - `model_signal_state`
  - `model_performance_state`
  - `authority_state`
  - `data_health_state`
- Forbidden semantic shortcuts:
  - do not use `actual_held_asset`, `current_asset`, or `effective_market_exposure` as real wallet exposure
  - do not use model equity or paper equity as real account PnL
  - do not show model exposure as real account exposure
  - do not let dashboards infer account state from model fields
- Every recurring bug must receive a regression test.
- A wording-only fix is allowed only when the issue is truly class `A`.
- Non-trivial Codex tasks must output:
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

## Rules
- If the official winner or baseline changes, update `project_truth.json` first.
- If the app/execution/dashboard export contract changes, update `export_contract.json` first.
- If official paths change, update `paths_registry.json`.
- Truth-sensitive app/execution/dashboard work must read `export_contract.json` before patching consumers.
- Pi authority/runtime work must follow `source_of_truth/pi_codex_runtime_workflow.md`.
- `master_state.md` should remain a short state snapshot, not a full history log.
- Chats must read this layer first and only then patch or interpret repo state.
