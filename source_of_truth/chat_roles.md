# Chat Roles - Market Regime v1

## MRV1 MASTER
Resi:
- current truth
- official winners
- baselines
- decisions
- next best step

Neresi:
- large scripts
- deep debugging
- downloader failures
- forensic audit in depth
- app implementation

## MRV1 CORE STRATEGY
Resi:
- core regime logic
- BTC-led / alt-led / cash
- phase61-63 style research
- leverage research in the core branch

Neresi:
- universe shortlist/governance
- app UI
- data infra
- final forensic approval

## MRV1 UNIVERSE
Resi:
- asset selection
- shortlist
- governance
- probation
- challenger layer
- add/remove asset mechanisms

Neresi:
- core regime logic
- app UI
- data downloaders
- final forensic audit

## MRV1 DATA
Resi:
- CoinGecko / Binance mapping
- downloader scripts
- cache
- manifests
- CSV integrity infra
- silent exit bugs
- deterministic input mapping
- source-of-truth file plumbing

Neresi:
- strategy logic decisions
- universe selection decisions
- app wording
- forensic approval

## MRV1 FORENSIC
Resi:
- lookahead checks
- same-day vs lag1 sanity
- paper CSV audit
- compare sanity
- robustness validation

Neresi:
- strategy ideation
- downloader infra
- app redesign
- MASTER bookkeeping

## MRV1 APP
Resi:
- `app.py`
- dashboard
- UI/UX
- copy
- export mapping
- live status export
- naming

Neresi:
- strategy research
- forensic validation
- downloader infra

## MRV1 AI LAB
Resi:
- AI research OS architecture
- experiment registry design
- agent orchestration
- autonomous research workflow

Neresi:
- standard debugging of one strategy
- app UI
- data bugs
- forensic audit of a concrete winner

## MRV1 ENGINEERING HYGIENE
Resi:
- repo structure cleanup
- `.gitignore`
- dependency hygiene
- packaging plan
- code health
- test skeleton
- CI-ready hygiene
- low-risk refactor plan

Neresi:
- winner decisions
- app wording/product framing
- forensic validation
- universe logic
- core strategy ideation

## Povinna disciplina
- If the problem belongs to another segment, the current chat must stop.
- The chat should immediately write the exact prompt for the correct segment chat.
- The chat should not ask for facts that already exist in source-of-truth.
- The chat should not mix its role with another segment.

## Repo-heavy / multi-step workflow
- If the task is repo-heavy / multi-step / file-edit heavy / validation-heavy, the preferred path is to prepare an exact prompt for Codex.
- Codex should be used for repo patching / execution.
- The local user should run heavy validations.
- The segment chat should interpret results and give the next exact step.

## Truth-sensitive workflow
- For truth-sensitive work, the acting chat must explicitly list which SSOT / README / export-contract files were actually read before the conclusion.
- For Pi authority/runtime/scheduler/publish-existing/tablet-dashboard work, the acting chat must also read `source_of_truth/pi_codex_runtime_workflow.md` before planning commands.
- Required response headers are:
  - `FILES READ`
  - `SOURCE OF TRUTH`

## Contract-first repo workflow
- Every non-trivial bug/task must be classified before patching:
  - `A` = wording/UI-only
  - `B` = runtime/data contract
  - `C` = execution/authority/scheduler
  - `D` = strategy math
- If the issue is `B`, `C`, or `D`, do not start with a UI patch.
- For `B`, `C`, and `D`, patch and validate the source contract first.
- Only then patch consumers, dashboards, or wording.
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
- Every recurring bug must get a regression test.
- A wording-only fix is allowed only when the issue is truly class `A`.

## Pi runtime coordination
- Pi runtime work must follow `source_of_truth/pi_codex_runtime_workflow.md`.
- Default Pi runtime posture is `publish-existing`, dry-run first, no full refresh by default, and no live order.
- Parallel Pi/runtime work must keep an explicit open-task list with:
  - `task name`
  - `owner`
  - `status`
  - `next action`
  - `blocker`

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

## Ked je dalsi krok jasny
- The chat should not wait unnecessarily for user confirmation.
- It should immediately provide:
  - exact next step
  - exact prompt for the correct segment chat
  - exact Codex prompt if needed
  - exact commands if needed
