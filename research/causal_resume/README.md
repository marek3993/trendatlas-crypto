# Same-experiment checkpoint recovery

Class **C** (orchestration/scheduler), with a runtime-state contract correction.
This directory is deliberately outside `research/causal_evolution`: that entire
frozen directory, including its original orchestration files, remains unchanged.

## Source of truth

- Scientific design: the existing `research/causal_evolution/evolution_contract.json`
  and `anti_overfitting_contract.json` in engine commit
  `53b6a5336ca1f7ce35b481a017f7e82396f3613c`.
- Resume-only operational policy: [contract.json](contract.json).
- Experiment: `causal_nested_v1_20260927`; SQLite metadata is the runtime authority.
- Frozen fingerprint: `eeb244ea6a79ef396f8f607696eebe08115b4a3a3bb16d4e74d0d251df0d8385`.
- Frozen manifest SHA256: `1f92cd047b2d39cc071984f57485beaafbb560b935fd23109c9f121154af0abc`.

## Exact root cause

At 2026-09-27 12:33:19 UTC, the original `cli.py:64` called
`guard(force=True)` **inside** `except AwaitBroker`. The guard correctly raised
`PauseResearch('bounded_activation_checkpoint')` after 1800.506 seconds.
A sibling `except PauseResearch` cannot catch an exception raised in the preceding
handler. The outer generic exception handler therefore persisted `FAILED` and the
process exited 1. The next dispatcher rejected this terminal state with exit 255.

This was not a systemd timeout or signal death. The journal records
`code=exited,status=1/FAILURE`, `Result=exit-code`, not `timeout`. The original
Type=exec worker had RuntimeMaxSec=31min, TimeoutStopSec=2s and the default
TimeoutStartSec=90s. Its normal 30-minute deadline caused the failure while waiting
for the broker. Broker and maintenance had successful runs and effective oneshot
TimeoutStartSec limits of 60s and 10min. Their legacy RuntimeMaxSec settings are
ineffective for oneshot units, but those existing TimeoutStartSec drop-ins remain.

## Contract impact and boundaries

The new entrypoint invokes the unchanged frozen `Evaluator`, controller, guard,
store, statistics, proposal and reporting modules. It does not patch their methods
or the fingerprint function. Every admission and locked resume hashes the entire
original package and raw inputs and validates the original manifest plus SQLite
experiment ID/fingerprint. Missing state is refused, never initialized.

The cooperative handler surrounds the entire activation, including broker waits.
Deadline exits commit `CHECKPOINTED`; SIGTERM/resource/production pauses commit
`PAUSED_WAITING_RESUME`; genuine exceptions still commit `FAILED`. The dispatcher
admits only RUNNING/CHECKPOINTED/PAUSED_WAITING_RESUME. Sealed and failed states
remain closed. SQLite controls admission even if a crash leaves stale status JSON.

At most one abandoned RUNNING attempt is transactionally changed to INTERRUPTED.
It is retained in the original 20,000-attempt ceiling. Completed cache rows are
never removed or recalculated. No candidate/API/time/storage ceiling is increased.
The existing controller remains solely responsible for nomination freeze and OOS
opening. This entrypoint exposes no new-cycle or reset command.

Recovery itself is a separate explicit operation, restricted to the evidenced
PauseResearch/deadline failure with 420 results and unopened OOS. It verifies a
backup-API snapshot, integrity and byte-for-byte equality of all existing result,
attempt, candidate, population, score, finalist and lineage rows before changing
only recovery/status metadata. The original failure remains in the recovery audit.
Repeated recovery is idempotent. Backups use immutable read-only SQLite connections
only because they are closed backup-API copies; live WAL databases never do.

## systemd deployment

Only these research drop-ins are installed:

- `/etc/systemd/system/trendatlas-evolution-worker.service.d/50-causal-resume.conf`
- `/etc/systemd/system/trendatlas-evolution-dispatch.service.d/50-causal-resume.conf`

Entrypoint directory:
`/opt/trendatlas-research/orchestration/causal-resume-20260927-v2`.
Frozen release stays at its original commit directory.

|Setting|Final value|
|---|---|
|Cooperative deadline|1680 seconds (28 minutes)|
|Worker RuntimeMaxSec|1800 seconds (30 minutes), retained hard failsafe|
|Worker TimeoutStopSec|20 seconds|
|Worker/dispatcher TimeoutStartSec|60 seconds for admission hashing|
|Worker Restart|Inherited `no`; existing dispatcher admits continuation|
|Dispatcher timer|Original 15-minute cadence, unchanged|
|Production priority|Original gate, Conflicts, After, RefuseManualStart and OnSuccessJobMode retained|
|Worker isolation|Original network denial, filesystem boundaries and resource limits retained|

The dispatcher additionally allows writes only to the research cycles directory
for SQLite WAL/SHM coordination. Its database connection remains `mode=ro`.
All admission errors return **255**: systemd can run OnSuccess after an
ExecCondition 1..254 skip, so a generic exit 1 must never authorize a worker.
This edge case was discovered and regression-tested during supervised deployment.

The first supervised activation used a shorter 120-second deadline to exercise a
real checkpoint without waiting 28 minutes. Data loading is not interruptible at
every instruction; its next guard ran at 143.403 seconds. The worker then exited 0
with CHECKPOINTED at 15:49:05 UTC. One in-flight attempt (421) was retained as
INTERRUPTED. The next activation uses the normal 1680-second deadline.

## Backup and evidence

Before any repair, both worker/broker locks were held and Python SQLite backup API
captured both databases, including committed WAL. Both integrity checks returned
`ok`. No open database was copied as a raw file.

Backup directory:
`/var/lib/trendatlas-research/causal-v1/recovery-backups/20260927T153203Z`.

- candidates.sqlite SHA256: `c33aa1a427a22ef5a55d95fc0439811136c9241565108f0a1e46b1b2c564a710`
- mailbox/proposals.sqlite SHA256: `bc3489369dc4818bef68ddbda67234abc936bbe148ffedc67550215b7d5c12b1`

[before.json](evidence/before.json), [backup.json](evidence/backup.json) and
[checkpoint.json](evidence/checkpoint.json) record the original failure, backup
and actual successful checkpoint. The final verification is recorded in
[after.json](evidence/after.json). Database backups are retained on Pi, not committed.

At the captured post-resume checkpoint (15:52:35 UTC), the same experiment was
RUNNING with **436 completed evaluations**, 438 attempts (436 COMPLETE, one
INTERRUPTED, one RUNNING), zero duplicate completed cache keys, zero finalists
and `outer_opened=false`. All original 420 evaluation/attempt rows, 104 candidates,
255 lineage rows, 21 populations and 180 score rows remained byte-for-byte intact.
The worker's successful checkpoint at 15:49:05 UTC was followed by a successful
dispatcher admission at 15:50:50 UTC and RUNNING at 15:51:03 UTC. No failure was
recorded after that transition.

Production HEAD remained `5ee031cef7de9c385056cec22f6511391d3e4f4f`, its dirty
working-tree inventory and unit/account/journal hashes were unchanged, and the
production timer stayed active. An unsigned read-only Hyperliquid `/info` check
also confirmed unchanged position quantities/entry prices/leverage and open orders
(zero), with no fills, funding events or non-funding ledger events since the
pre-repair backup. **The live USDC total/hold differs from the saved 00:11 UTC
snapshot**, which predates the repair by over 15 hours; constant marked account
balance is not claimed. See [account_check.json](evidence/account_check.json).
No signing credential or exchange mutation was used.

## Validation commands

Use an archive/checkout of the exact frozen engine outside any directory named
`local_state`, because the original fingerprint excludes paths containing that
component. Tests create temporary **synthetic** states only.

```text
python -I -B research/causal_resume/test_resume.py --engine <frozen-release> -v
python -I -B -c "import sys,unittest; sys.path.insert(0,'<frozen-release>'); unittest.main(module=None,argv=['tests','research.causal_evolution.tests','research.causal_evolution.vendor.test_research','-v'])"
sudo python3 -B research/causal_resume/preemption_probe.py
systemd-analyze verify trendatlas-evolution-worker.service trendatlas-evolution-dispatch.service
git diff --check
```

17 new tests pass on Windows and Pi, plus all 45 unchanged frozen-engine tests.
Coverage: cooperative deadline/hard margin, the exact broker-handler regression,
three activations using actual synthetic evaluations, SIGTERM, real process crash
after reservation, transactional interruption, duplicate process lock, idempotent
recovery/sealed runs, retained results/lineage/budgets, closed OOS, real FAILED,
identity rejection, stale status JSON, systemd exit-255 admission, and production
gate/job races. The isolated systemd probe also proved cooperative SIGTERM under
fake-authority preemption, blocked admission without stopping that authority,
resume after it stops, and a genuine hard timeout. Real production was never invoked.

## FILES READ

Repository AGENTS.md; source_of_truth README, master_state, chat_roles,
project_truth, export_contract, paths_registry, current_issues,
pi_codex_runtime_workflow; canonical script_registry, output_registry,
registry_workflow; research/causal_evolution README, REPORT, evolution_contract,
protocol, cli, resources, bootstrap, store, mailbox, controller, evaluator,
locking, gate, deployment, install_release, tests, vendor/common, and
ops/checkpoint_export and ops/preemption_probe. Also the existing local Pi helper,
Pi status/manifest/SQLite metadata, installed units/drop-ins and relevant journals.

## Forbidden old paths checked

No changes/imports into production scripts, account/order adapters, old continuous
research evaluator, legacy model/PnL streams, authority snapshots, outputs/* or
data/*. No production checkout pull, refresh, publish, order submission, new
experiment, manifest rewrite or database reset. Original production HEAD, unit
hashes, account snapshot and all execution-journal hashes are checked against the
pre-repair baseline. No frontend files are involved.
