# Pi recovery and isolated evolution validation — 2026-09-20

## Outcome

Pi recovery is deployed and verified end to end. Production code is commit
`1bb2d0d64363d111d92e4257d0a7345b484b8532` on the existing
`production-multi-account` branch at `/opt/market_regime_v1`.
Research runs locally in the separate Windows worktree
`C:/Users/benda/Desktop/trendatlas_recovery_20260920`; it is not deployed to Pi.

## FILES READ

First: `docs/pi-outage-recovery-handoff.md` from the requested repair branch.
Then `AGENTS.md`, `source_of_truth/README.md`, `source_of_truth/master_state.md`,
`source_of_truth/chat_roles.md`, `source_of_truth/project_truth.json`,
`source_of_truth/export_contract.json`, `source_of_truth/paths_registry.json`,
`source_of_truth/current_issues.md`, `canonical/script_registry.json`,
`canonical/output_registry.json`, `canonical/registry_workflow.md`, and
`source_of_truth/pi_codex_runtime_workflow.md`. Large JSON registries/contracts
were inspected in their relevant runtime, authority, health and research sections.

Implementation and validation reads: `scripts/production/data_health_common.py`,
`scripts/execution/run_trendatlas_production.py`,
`tests/test_authority_outage_recovery.py`,
`tests/test_single_production_orchestrator.py`,
`tests/test_execution_authority_publish.py`, `.gitignore`,
`research_os/dev_only/specs/dev_only_production_core_btc_candidate_persistence_early_risk_compare.spec.json`,
the new evolution module and tests, and the read-only historical BTC CSV.

Pi reads: installed service/timer definitions and drop-ins; Git status and HEAD;
canonical production run manifests, authority snapshots, Production Core,
intent, gate, data health, account readback and publication checkout history.
No environment-file contents or private exchange credentials were printed.

## SOURCE OF TRUTH

Repository SSOT defines the execution and research boundaries. The actual Pi
service, canonical run manifests, exchange-backed account readback and published
authority artifacts establish the observed runtime state. Backtest SQLite/JSON
results are dev-only and non-authoritative; they establish no real-account PnL.

## Exact root cause

Class C: the former authority-advance helper rejected any previous successful
publication other than D-1 before checking current-run provenance. The Pi's last
success was 2026-09-05, while its current target was 2026-09-19. The real observed
failure was `VALIDATE_DATA_HEALTH` with
`execution_authority_latest_successful_snapshot:stale`.

Classes D/B: the handoff's uncommitted synthetic evolution controller was absent
from the fetched branch, all accessible local worktrees, and the Pi. Added a
self-contained research controller, historical adapter and persistence contract;
this is not an integration with an inaccessible controller or IML.

## Exact contract impact

The deployed repair permits an older predecessor only with all current-run,
current-day, intent, gate, production and account provenance checks intact.
Underlying input freshness still blocks. No snapshot date was manually changed.

The research-only SSOT addition authorizes ten candidates, six survivors, four
unseen one-gene mutations, immutable historical inputs, transactional results,
fixed train/validation/final-test dates and a sealed run after final testing.
Production strategy, account contracts and frontend are unchanged by research.

## Deployment evidence

- Password-authenticated SSH succeeded to `trendatlas@trendatlas.local`.
- Initial Pi HEAD: `d0935a00dbba9556edccfb0e4ae2315349074418`.
- Initial service had `MainPID=0`, `SubState=auto-restart`; no in-flight order
  process was killed. Timer/retry were stopped before applying the repair.
- Fast-forward applied exactly the seven files from repair commit `1bb2d0d6`.
- SHA256 comparison of 3,253 pre-existing modified/untracked files found zero
  changes from deployment; the record is `/tmp/trendatlas-recovery-predeploy-hashes.json`.
- A temporary `/run/systemd/system/mrv1-production.service.d/90-recovery-no-submit.conf`
  set the existing service's ExecStart to `--no-submit` and disabled retry. The
  installed user, working directory, environment file and hardening were retained.
- Preflight `prod_20260920T070904Z_347160`: `PREFLIGHT_READY`,
  `live_order_chain=NOT_INVOKED`, `real_order_sent=false`, one eligible account,
  `PREFLIGHT_ALIGNED`, current target CASH, current closed day 2026-09-19.
- The temporary drop-in was removed before the authorized canonical production run.
- Production `prod_20260920T071039Z_074762`: `SUCCESS`, authority `PASSED`,
  post-trade verification `NO_ACTION`, one aligned account, `real_order_sent=false`.
- The orchestrator ran `publish-existing --dry-run` before real publication.
- Published authority run `20260920_071151`: target 2026-09-19, success, current.
- Canonical intent and gate alignment checks both returned an empty error list.
- Account readback: CASH, exposure 0, position notional 0; account equity 83.186462 USD.
- Health: `block_app=false`, `block_execution=false`. Pre-existing research-only
  BTC derivatives staleness and optional provider warnings remain visible.
- Publication commit: `a9d414ed655dac6ae55be10f38eafe712fd6a4bb`.
- `mrv1-production.timer` is enabled and active; next run 2026-09-21 00:10 UTC
  (02:10 CEST). Production retry is restored to `on-failure`, 15 minutes; no drop-ins remain.

## Regression tests and validation commands/results

Pi, using `.venv/bin/python -m unittest discover -s tests -p <file> -q`:

| Test file | Passed |
| --- | ---: |
| test_authority_outage_recovery.py | 10 |
| test_single_production_orchestrator.py | 10 |
| test_execution_authority_publish.py | 17 |
| test_pi_fast_daily_authority_refresh.py | 13 |

The orchestrator tests cannot import Linux `fcntl` on Windows; they passed on Pi.
Windows also passed all ten focused outage regressions.

`python -m unittest discover -s tests -p test_evolution_research.py -v`:
15 tests passed, none skipped in the final run. The Windows link-escape test uses
a junction when symlink privileges are unavailable. Coverage includes prior-day
signals, future/holdout isolation, known net buy-and-hold accounting, input
validation, 10/6/4 lineage, persistence, interruption rollback, deterministic
resume, early/repeated final-test rejection, frozen code/input, time budget,
output escapes, protected production sentinels and report generation.

Changed JSON contracts parse successfully; `git diff --check` passes.
SQLite `PRAGMA integrity_check` returns `ok`.

## Executed historical research

Run: `btc_pilot_20260920`, seed 20260920, three predeclared generations,
15 bps one-way fees plus slippage assumption, sequential execution, 300 seconds
maximum per operation. Local input: 3,290 BTC daily bars, 2017-08-17..2026-08-19.
Original input SHA256:
`52a54850a11110a5f4cf00c0668645ab80e210f577a97427396b8721704b6b26`.
The input file remained unchanged after research.

Training: 2018-08-01..2022-12-31. Selection: 2023-01-01..2024-12-31.
Final test: 2025-01-01..2026-08-19 (596 days). The final test was evaluated only
after the champion was frozen. The database is now `SEALED`.

Eighteen unique candidates were evaluated across 30 generation slots. Four final
mutations are retained as unevaluated audit records. There are 38 stored period
evaluations, 43,402 daily curve rows and 17,829 simulated trades including the
final candidate and buy-and-hold benchmark.

Frozen champion: `d08666c8df9f56c53095`; fast/slow windows 40/60 days,
momentum 60 days, threshold 0, annualized volatility target 0.75, exposure cap 0.75.

| Final test | Net return | CAGR | Max drawdown |
| --- | ---: | ---: | ---: |
| Selected research candidate | +2.21% | +1.35% | -24.05% |
| BTC buy-and-hold | -26.13% | -16.94% | -52.97% |

These are simulated results from the new BTC research family, not production
strategy performance. The result does not authorize promotion. This run's
programmatic holdout is isolated, but already-viewed history is not claimed to
be globally untouched. Raw reports remain in the ignored research output root.

## Forbidden old path checked

No full-refresh, historical order replay, manual authority snapshot edits,
freshness bypass, competing production scheduler, extra canary trade, generated
runtime/data commit, frontend edit or production import from research. The
original Windows working tree was not switched, reset, stashed or cleaned.
Research code has no exchange/API client, subprocess, production module import,
IML requirement or publishing hook. Runtime output changes came only from the
canonical production/preflight producer. Research results are Git-ignored.

## Exact files changed / exact git add list

This continuation adds the following commit on top of the existing seven-file
repair commit. Only the repair was deployed to Pi.

```text
git add .gitignore canonical/output_registry.json canonical/script_registry.json source_of_truth/master_state.md source_of_truth/paths_registry.json source_of_truth/project_truth.json research_os/dev_only/evolution/CONTRACT.md research_os/dev_only/evolution/README.md research_os/dev_only/evolution/__init__.py research_os/dev_only/evolution/__main__.py research_os/dev_only/evolution/backtest.py research_os/dev_only/evolution/controller.py tests/test_evolution_research.py docs/pi-recovery-evolution-validation-20260920.md
```

## Commit message

`Add isolated evolution backtests with persistence and sealed final testing`

## Commit hash

Research/audit: the commit containing this document (exact hash reported in the
completion message). Deployed repair and producer-generated publication hashes
are recorded above. No generated research, `outputs/*` or `data/*` files are staged.
