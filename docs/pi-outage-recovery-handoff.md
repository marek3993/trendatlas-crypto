# Pi outage recovery handoff
Class C: execution/authority recovery. Prepared against the observed Pi commit d0935a00dbba9556edccfb0e4ae2315349074418.

## Evidence / exact root cause
User's Pi latest successful snapshot targets 2026-09-05. Current attempt targets 2026-09-19 and fails VALIDATE_DATA_HEALTH with execution_authority_latest_successful_snapshot:stale.
same_run_new_closed_day_is_proven rejected every gap other than exactly one day before checking current-run provenance. This prevents recovery after missed daily publications.

## Contract impact
The older successful publication may predate the current target by any positive number of days. All existing same-run attempt, intent, production and gate/account fingerprint checks remain mandatory, as do normal source freshness checks. Same-day/future/malformed predecessor dates do not qualify.
No old snapshot edits, no historical order replay, no authority success before execution verification. This changes the source contract explicitly in project_truth, export_contract, master_state and Pi runbook.

## FILES READ / SOURCE OF TRUTH
AGENTS.md; source_of_truth/README.md, master_state.md, chat_roles.md, project_truth.json, export_contract.json, paths_registry.json, current_issues.md, pi_codex_runtime_workflow.md; canonical/script_registry.json, output_registry.json, registry_workflow.md; scripts/production/data_health_common.py; tests/test_single_production_orchestrator.py.
Registry/export reads focused on relevant authority/runtime sections. User-provided Pi status and reports are the observed runtime truth; repository metadata does not establish current exchange state.

## Files changed / exact git add list
git add scripts/production/data_health_common.py source_of_truth/pi_codex_runtime_workflow.md source_of_truth/project_truth.json source_of_truth/export_contract.json source_of_truth/master_state.md tests/test_authority_outage_recovery.py docs/pi-outage-recovery-handoff.md

## Validation
python -m unittest discover -s tests -p 'test_authority_outage_recovery.py' -v
10 tests PASS. Real file fixtures and SHA256 fingerprints; no exchange access.
Covers 14-day and normal one-day recovery; failed attempt; wrong run/day; changed production/account fingerprints; failed gate alignment; missing gate; missing permission; invalid/same/future dates.
These are focused helper regressions, not a full end-to-end production validation. Current-source freshness logic was not changed.
Forbidden old paths checked: no generated outputs/data edits; no full-refresh; no additional scheduler; no order calls or authority snapshot fabrication.

## Deployment status and next steps for local Codex
NOT deployed to Pi. No live order submitted by this work.
Use SSH to trendatlas@trendatlas.local if reachable; do not assume this cloud session can reach Pi.
1. Read repo policy and actual installed systemd unit/drop-ins, git status, latest run state. Preserve runtime data, journals, credentials and unrelated user edits.
2. Before modifying runtime code, prevent timer/retry overlap and let any in-flight execution finish or reconcile it safely. Do not blindly kill a potentially submitting process.
3. Fetch this repair branch, review exact diff against Pi's observed base and apply only this repair. Do not switch the Pi to main or discard runtime files.
4. Run focused regressions and relevant existing authority/health tests in the full repo.
5. Run canonical orchestrator with --no-submit in the installed service environment, preserving its user, paths and environment file. This is a refresh/preflight, not a successful authority publication. Verify PREFLIGHT_READY, live_order_chain=NOT_INVOKED, real_order_sent=false, eligible accounts, current input dates and provenance.
6. If any other blocker appears, diagnose it without skipping guards. Only after this validation proceed with the already authorized single-executor production recovery and verify terminal run, exchange readback, authority publication and next timer. Do not invent an additional live canary trade.
7. Report real status; do not call this repaired on Pi until its end-to-end result is verified.

## Evolution task
Local pure controller exists with 9 passing synthetic tests under research_os/dev_only/evolution. It is not part of this repair commit and was not deployed or committed by this work. Real backtest adapter, persistence, holdout evaluation and resource-limited Pi deployment remain pending. IML is optional and has no proven benefit. Research must stay separate from production execution.

## Commit message
Recover authority advancement after missed daily runs
Commit hash: refer to the commit containing this report.
