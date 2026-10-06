# Phase 2 v2 live recovery — 2026-10-06

## SOURCE OF TRUTH

Research: live read-only SQLite, immutable selections/books/events, installed isolated research systemd units, native DeepSeek response receipts. Normative contracts: phase2_v2_contract.json plus the explicit research-only phase2_v2_recovery_contract.json. No production strategy authority changes.

## Exact root cause / contract impact

Class B/C. The frozen origin 4 selection (candidate 37247fb523b9c1a4dd827c07926ca88e1e86c9e80ac177441cd356e17ab0ce47, frozen 2026-10-05T18:35:48.741128Z) encountered missing_held_asset_price:2022-05-13:LUNAUSDT@original. The uncaught deterministic ValueError in test_selected repeatedly failed the worker every timer tick. It remained at 879 evaluations and four valid books for over 22 hours; status.json incorrectly still claimed active evolution without showing the failure.

The new source recovery contract makes that selected-book failure terminal and append-only. It invalidates the entire continuous selected portfolio. Later test folds cannot carry a valid book and receive NOT_EVALUABLE_CONTINUITY_LOST receipts; their unchanged past-only training and frozen selection continue. No liquidation, cash reset, new market price, shortened headline CAGR, candidate/selection rewrite or strategy change occurs. Valid completed test books remain separate from processed origins. Four valid prefix folds are not a valid full-horizon result.

The standalone continuation coordinator imports the exact unchanged evaluator and retains its original engine/contract/input binding. A separate coordinator/policy binding is recorded in an append-only event. The existing development timer invokes the coordinator through a research-only drop-in; worker isolation, credentials separation, resources and broker are unchanged. Timers remain enabled continuously, including after reboot, until the finite 14 authorized origins are processed. Completion does not restart the same search or grant an extra API budget.

## Live proof

- Cycle unchanged: phase2_v2_20261005T175209Z_47661557.
- Before repair: 879 evaluations; 4 valid books; origin 4 generation 10 FROZEN in live DB; stale status.json still had generation 9 ADVANCED.
- Automatic successful worker passes: 903 → 927 → 939 → 987 evaluations. No manual worker run was used. Transient WAITING is the normal bounded broker mailbox handoff, not the old deterministic restart loop.
- Checkpoint C: 2026-10-06T17:15:23.366027Z read snapshot; 987 evaluations (+486 vs 501), origin 6 generation 1 WAITING; last evaluation 17:15:21.157640Z and durable event 17:15:21.157825Z. 4/14 valid completed books; 6/14 processed origins, including two explicitly invalid test outcomes.
- SQLite integrity ok; append-only hash chain valid; duplicate genes/evaluation keys zero. All original 261 candidates, 879 evaluations, 5 selections, 4 books and 1191 audit events compare exactly against the pre-recovery SQLite backup.
- Backup: /var/lib/trendatlas-research-v2/recovery-checkpoint-25c3e61f95085e6c.sqlite. Coordinator release: /opt/trendatlas-research/phase2-v2/releases/continuation-25c3e61f95085e6c.
- Last real DeepSeek response: 2026-10-06T17:12:07.170547Z; request began 17:12:03.665639Z; 2004 input + 571 output = 2575 tokens; error null. Total 34 provider calls / 91689 reported tokens. The latest broker response at 17:14:59.482216Z was an explicit input_token_ceiling fallback with no provider call or billed tokens; deterministic training continued. No API limit was enlarged.
- Prospective OOS LOCKED and forward 2027 SEALED remain unchanged. No retrospective independent OOS claim.

## FILES READ

AGENTS.md; ordered source_of_truth/README.md, master_state.md, chat_roles.md, project_truth.json, export_contract.json, paths_registry.json, current_issues.md; canonical/script_registry.json, output_registry.json, registry_workflow.md; pi_codex_runtime_workflow.md (local only); phase2_v2_contract.json; research/phase2_v2 README, runtime.py, engine.py, broker.py, audit.py, deploy.py, dispatch_condition.py, run.py; tests/test_phase2_v2.py; original docs/phase2-v2-20261005/REPORT.md. New recovery source/contract/tests were read during validation. Live VPS reads: unit definitions/state, research-only journal/status/mailbox, read-only SQLite and backup. Production evidence is separately documented on its existing production audit branch.

## Regression test added / validation commands and results

- tests/test_phase2_v2_continuation.py: four regressions for terminal/idempotent missing-price recovery, immutable checkpoint/selection preservation, propagation of unknown programming errors, unchanged next-origin past-only training, and distinct valid/invalid completion without a new cycle.
- python -m unittest tests.test_phase2_v2_continuation tests.test_phase2_v2 -q: local 20/20 PASS. Against the deployed frozen release test suite plus four new tests: 17/17 PASS (its retained original test file contains 13 tests).
- Recovery contract parsed/validated before coordinator implementation/deployment. Registry and evidence JSON parse PASS; coordinator/deployer Python compilation PASS; git diff --check PASS.
- Versioned deployment proves byte-identical runtime.py, engine.py, market.py, contract.py and original phase2_v2_contract.json, then exact SQLite binding and pre-recovery table hashes. No evaluator binding migration.
- audit_readonly.py, piped over SSH to Python, validates a coherent read snapshot, preserved rows, chain, duplicate counts and native usage. Evidence: checkpoint-A/B/C.json, deployment.json, systemd.txt.

## Forbidden old path checked

No Pi contact, LeadPilot control, production unit control, order/cancellation, production run, full-refresh, production source edit, generated outputs/data staging, manual authority snapshot edit, sealed input access or legacy v1 restart. Original development timer and broker remain the only v2 research scheduling path. No strategy formulas, genes, costs, budgets, inputs or evaluation results changed.

## Exact files changed / exact git add list

See GIT_ADD.txt; every listed file is research code/contract/navigation or audit documentation. No generated outputs/data included.

## Commit message

Resume Phase 2 v2 training after terminal selected-book failure

## Commit hash

Reported in the final chat response after committing; use git log -1 on codex/phase2-v2-20261005. Original requested commit 1465a4a044e0a68bb3d93fa51789e1d6d3d36e24 was independently verified on the remote branch before this follow-up. No merge into main.
