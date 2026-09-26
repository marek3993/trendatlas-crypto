# Production recovery after power loss, 2026-09-26

Class C+B. This report records preparation for operator activation, not completed live reconciliation.

## FILES READ / SOURCE OF TRUTH

Read AGENTS.md, the full truth-first order (README, master_state, chat_roles, project_truth, export_contract, paths_registry, current_issues, canonical script/output registries and registry_workflow), pi_codex_runtime_workflow, the external 20260925 execution report, execution-reconciliation-20260925, production_execution_contract and production_asset_universe_contract. Inspected canonical orchestrator, fast dependency builder, active ETF adapter, freshness producer, systemd units, orchestrator/source-contract regressions and multi-account preflight.

Production Core remains strategy authority; fresh Hyperliquid reads remain account authority. The normative execution contract now explicitly identifies freshness as an adapter input and requires persistent scheduling through the same canonical service.

## Root cause and boot evidence

The timer already had Persistent=true. Pi uptime indicated boot at 2026-09-26 08:49:55 UTC. Its missed calendar event triggered the canonical service at 08:53:33 UTC. The retained no-submit override prevented exchange writes. The first run and two retries failed while building Production Core: freshness=2026-09-24, trend_status=2026-09-25. A further retry was interrupted during maintenance; its preserved RUNNING manifest is interruption evidence, not a success.

The 20260925 repair incorrectly classified verify_app_freshness as deferred presentation. The active adapter consumes that report and requires its closed day to match refreshed trend inputs, so every new-day build failed before execution. Restore the existing freshness producer before dependency materialization and Production Core build. Do not relax its checks or manually rewrite its report. The real-account performance ledger remains deferred and warning-only.

Journal retained on Pi only covers the current boot; its first timestamps precede clock synchronization. Full available service journal since September 25 is saved under /var/backups/trendatlas-recovery-20260926. This is not evidence that an earlier boot's journal was retained.

## Integration and runtime preservation

Fetched origin/main at af0b7586. Verified 8fdf0b03 is not its ancestor. Integrated main into the repair branch without conflicts, preserving all four newer authority commits. Merge commit: 430ef97e. Inherited data/outputs exactly match origin/main; none were manually edited. Main and the public deployment are unchanged.

Pi deployment must restore only changed code/contract/test/doc paths, never merged Git data/outputs. Backup contains original dirty tracked files, full status, manifests and 7,893 runtime file hashes. Preserve secrets, Supabase records, journals and encrypted credentials. Keep /etc/systemd/system/mrv1-production.service.d/90-no-submit-verification.conf until operator activation.

## Regression and validation

- Source contract validation before implementation: 7 passed.
- Regression reproduces a stale prior-day freshness report with an advanced target and requires PREFLIGHT_READY without orders after producer refresh.
- Invalid direct freshness must stop before Production Core or execution. Presentation-ledger failure remains warning-only after execution.
- Systemd regression asserts Persistent=true and the canonical service target.
- Relevant Python suite: 265 passed, 26 subtests passed.
- TypeScript suite: 211 passed across 15 suites, including 4 PGlite migration tests and forbidden execution-path checks.
- Typecheck, lint, Next.js production build, JSON parsing and changed-Python py_compile passed. Installed systemd service/timer verify returned 0.
- New-change git diff --check passed. Historical main authority CSV CRLF lines trigger whitespace warnings against the older repair parent; they are preserved verbatim. A pre-existing research report EOF warning appears in the full branch comparison, outside this patch.
- Final Pi no-submit, deployment preservation verification and current target/account evidence are recorded in the external final recovery receipt after deployment.

## Operator boundary

No financial order or cancellation is performed by this recovery task. The exact live plan must come from the final current-day no-submit run. After operator activation, verify terminal journal/CLOID recovery, no unwanted positions or conflicting orders, fresh wallet alignment or explicit terminal failure, authority publication only after exchange read-back, enabled/active timer and public dashboard agreement. Until those checks pass, recovery is not complete.

## Exact staging list

The merge inherited main's existing artifacts automatically. Explicit patch staging:

```text
git add -- source_of_truth/production_execution_contract.json source_of_truth/pi_codex_runtime_workflow.md scripts/execution/run_trendatlas_production.py tests/test_dynamic_execution_source_contract.py tests/test_single_production_orchestrator.py docs/production-recovery-20260926.md
```

Commit message: Fix production freshness ordering for persistent boot recovery.

## Work ledger

| Task | Owner | Status | Next action | Blocker |
| --- | --- | --- | --- | --- |
| Contract, integration and regressions | root | Implemented | Deploy validated patch without runtime overwrite | None |
| Pi same-service no-submit and current read-back | root | Pending deployment | Verify final current-day plan | None |
| Live reconciliation and authority/dashboard confirmation | operator | Not performed | Operator-controlled canonical service activation | Final operator action required |
