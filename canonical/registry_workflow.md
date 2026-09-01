# Registry Workflow

This file defines how segmented chats should read the repo, outputs, and source-of-truth layer.

## Goal
- Chats must not work from memory only.
- Chats must orient from the repo and the central truth registry.
- Repo-wide workflow is now contract-first and regression-locked.

## Required read order
Every chat should use this order for execution / analysis / validation work:

1. `source_of_truth/README.md`
2. `source_of_truth/master_state.md`
3. `source_of_truth/chat_roles.md`
4. `source_of_truth/project_truth.json`
5. `source_of_truth/export_contract.json`
6. `source_of_truth/paths_registry.json`
7. `source_of_truth/current_issues.md`
8. `canonical/script_registry.json`
9. `canonical/output_registry.json`
10. only then the concrete `scripts/`, `outputs/`, `tests/`, and other repo files

For Pi authority/runtime/scheduler/publish-existing/recovery/tablet-dashboard work, read `source_of_truth/pi_codex_runtime_workflow.md` immediately after the base truth order and before opening concrete scripts, outputs, or runtime commands.

## Layer interpretation

### Repo
- The repo contains code, outputs, tests, manifests, and support files.
- The repo by itself is not automatically official truth.

### `source_of_truth/`
- `source_of_truth/` is the only official SSOT.
- If raw output conflicts with `source_of_truth/`, official truth is `source_of_truth/`.
- A change in `source_of_truth/` must never happen silently or implicitly.
- Not every report, output, or forensic verdict is official truth.

### `canonical/`
- `canonical/` is the navigation layer between repo code and truth.
- It is used to discover which script does what, which outputs matter, and which artifacts are active, legacy, or deprecated.
- `canonical/` is not a replacement for `source_of_truth/`.

### `automation/`
- `automation/` is the execution and patch orchestration layer.
- It may create runs, logs, reports, screenshot manifests, pending truth patches, and approval records.
- It must not keep a parallel truth layer.
- It must not write silently into `source_of_truth/`.

## Contract-first patch workflow
- Every non-trivial bug must be classified before patching:
  - `A` = wording/UI-only
  - `B` = runtime/data contract
  - `C` = execution/authority/scheduler
  - `D` = strategy math
- If the bug is `B`, `C`, or `D`, do not start with a UI patch.
- For `B`, `C`, and `D`, the required order is:
  1. patch the source contract
  2. validate the source contract
  3. patch downstream consumers
  4. patch wording/UI only after the contract path is correct

## Pi authority runtime add-on
- Pi runtime work must follow `source_of_truth/pi_codex_runtime_workflow.md`.
- The only automatic production entrypoint is `scripts/execution/run_trendatlas_production.py`.
- `publish-existing` remains an internal authority primitive, with dry-run before real publish.
- `--mode full-refresh` requires explicit approval.
- `--no-submit` verification must include `live_order_chain=NOT_INVOKED` and `real_order_sent=false`.
- Focused refresh, publish, planner, gate, and submit scripts must not be enabled as competing automatic schedulers.
- Durable journals under `outputs/execution/execution_journal/` are recovery evidence and never replace Production Core, canonical intent/gate, account snapshot, or authority truth.

## Required normalized public/runtime contracts
- `real_account_state`
- `model_signal_state`
- `model_performance_state`
- `authority_state`
- `data_health_state`

## Forbidden semantic shortcuts
- Do not use `actual_held_asset`, `current_asset`, or `effective_market_exposure` as real wallet exposure.
- Do not use model equity or paper equity as real account PnL.
- Do not show model exposure as real account exposure.
- Do not let dashboards infer account state from model fields.

## How to read code and outputs
When a chat needs to understand a concrete script or output, it should:

1. check `canonical/script_registry.json` to see whether the script is active and what it generates
2. check `canonical/output_registry.json` to see whether the output is decision-relevant or support-only
3. only then open the concrete script and concrete outputs
4. clearly distinguish in the answer:
   - raw output
   - report
   - pending truth
   - official truth

## How to record findings

### If the result is only a working artifact
- create a report, manifest, execution note, forensic verdict, or registry update

### If the result is a candidate for official truth
- create a pending truth patch

### If the result should become official truth
- it must pass an approval loop
- it must then pass a separate apply step

## What must not be confused
- `raw output` = technical script result
- `report` = summary or audit artifact
- `pending truth patch` = proposed truth-layer change
- `approved patch` = allowed candidate for apply
- `applied truth` = executed write into `source_of_truth/`
- `official truth` = current state in `source_of_truth/`

## Regression-locked rule
- Every recurring bug must receive a regression test.
- A wording-only fix is allowed only when the issue is truly class `A`.

## Required Codex output for non-trivial tasks
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

## Default decision rule
- If a chat is unsure whether something is official truth, assume it is not.
- Treat it only as an artifact / report / candidate input until it is explicitly reflected in `source_of_truth/`.

## Practical goal
- Any new or segmented chat should be able to quickly find relevant code, understand which outputs matter, separate reports from official truth, prepare the next decision step, and continue without relying on undocumented memory.
