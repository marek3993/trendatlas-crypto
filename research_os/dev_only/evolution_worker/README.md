> Current authorization (2026-09-22): see [CAMPAIGN_CONTRACT.md](CAMPAIGN_CONTRACT.md).
> The historical installation-only/empty-queue restrictions below describe v1; the
> explicit bounded campaign authorization supersedes those restrictions for v3 only.

# TrendAtlas local Evolution Worker

Installation is pending the user's explicit review. This package does not call an
AI API or spend AI credits at runtime. It uses Python 3.12+ standard library and
the unchanged BTC mean-reversion backtest/controller. It is not a production
strategy and cannot submit orders. No IML or pip installation is needed.

The old historical REJECT studies cannot be requeued, including by renaming the
mean-reversion study. This task validates synthetic prices only. A new historical
job needs its own operator-supplied preregistration and pinned input hash. This
version supports the existing mean-reversion engine; adding another strategy
family requires a separately reviewed release and preregistration.

## Fixed boundaries

- Code: `/opt/trendatlas-research/releases/<source_commit>/`, root-owned read-only.
- Data alias: `/opt/trendatlas-research/input/BTCUSDT_1d.csv`, a service-private
  read-only bind of the production historical CSV. The production tree is hidden.
- State: `/var/lib/trendatlas-research`, owned by `trendatlas-research`.
- Queue: `queue/<job_id>/study.json`, root-owned, readable but not writable by worker.
- Ledger: `queue.sqlite3`; one `worker.lock` covers admission and execution.
- Accepted job: `jobs/<job_id>/accepted.json`; frozen data: `input.csv` beside it.
- Engine DB: `jobs/<job_id>/outputs/research_os/dev_only/mean_reversion/<job_id>/research.sqlite3`.
- Final files beside accepted.json: `report.json`, `audit.json`, `SEALED.json`;
  only if qualified, `paper-monitor-proposal.json`. A proposal is not executable.
- `staging/<job_id>/` holds uncommitted initialization only. It may be rebuilt
  after a crash; published job roots and SEALED artifacts are never overwritten.

New queue records use this schema (placeholders are not an executable study):

```json
{
  "schema_version": 1,
  "job_id": "NEW_PREREGISTERED_ID",
  "mode": "research",
  "engine": "btc_mean_reversion_v1",
  "preregistration_commit": "FULL_40_HEX_COMMIT",
  "release_sha256": "REVIEWED_RELEASE_SHA256",
  "input_name": "BTCUSDT_1d.csv",
  "input_sha256": "PREREGISTERED_DATA_SHA256",
  "study": "REPLACE_WITH_COMPLETE_PREREGISTERED_STUDY_OBJECT"
}
```

The study has exactly the existing engine's domains, seed, five-generation
10/6/4 budget, costs, turnover limit, ranking and historical-only outcome rules.
Only experiment ID, historical data hash, folds and base commit may differ before
admission. They cannot differ on resume. The worker does not look up GitHub to
validate a preregistration: the local operator is responsible for admitting a
reviewed committed specification. Code identity is independently pinned and
verified before imports. Queue records cannot carry code, import names or paths.

Operator enqueue (only after installation and separate study authorization):

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent \
  /usr/bin/python3 -I -B /opt/trendatlas-research/releases/COMMIT/research_os/dev_only/evolution_worker/bootstrap.py \
  enqueue --job-file /path/to/reviewed/study.json
```

One activation finishes the remaining frozen budget, unless preempted or blocked.
REJECT is SEALED and stops. Qualification only writes a frozen candidate and a
paper-monitor proposal. The next timer tick can process another explicitly queued
study; it cannot create one. No queued/admitted work means idle. BLOCKED jobs need
operator review; low disk pauses without changing the specification. A running
job can resume from its accepted copy even if its queue record is removed.

## Production priority

The three research units are `trendatlas-evolution-dispatch.timer`,
`trendatlas-evolution-dispatch.service`, `trendatlas-evolution-worker.service`.
Only the dispatcher timer is enabled. It checks at boot +10 minutes and every
15 minutes after dispatcher inactivity, with up to 30 seconds jitter.

The dispatcher checks pending work, successful completed production, active/enabled
production timer, no production job, and no active/activating/deactivating worker
or queued worker job. OnSuccessJobMode=ignore-requirements admits the worker
without stopping an already-started production unit; ordering is retained. The
worker independently rechecks admission. Its Conflicts/After relation makes a
normal production start stop the complete research cgroup before production's
ExecStart. TimeoutStopSec=2s bounds cleanup before SIGKILL. SQLite resumes safely.
RefuseManualStart prevents an accidental direct worker start from stopping
production. There are no production unit/drop-in edits or production lock writes.

The single-dispatcher idle/pending-job guard is essential: without it, repeated
dispatch during preemption could replace a pending worker stop job. The isolated
Pi arbitration fixture exercises that regression explicitly. Do not add another
timer, Wants, Requires, OnSuccess or manual activation path to the worker.

The worker only starts after a successful production pass since boot. A failed or
auto-retrying production pass blocks research. This favors production recovery
over prompt research resume. Scheduled production retains its enabled timer.

## Resources and isolation

Nice 19, idle IO scheduling, 20% of one CPU (not 20% of all Pi CPUs), 384 MiB
MemoryMax, 256 MiB MemoryHigh, no swap, 16 tasks, 128 MiB file limit. Require at
least 1 GiB free plus 64 MiB headroom; stop at a 512 MiB research-state budget.
Check before admission and every generation. Data limited to 5 MiB/10,000 bars.
The previous real historical study used about 20 MiB for its DB; budget 64 MiB
per comparable job including rollback journal and metadata. No automatic deletion
of old results. An operator must review/archive research data when its budget fills.

Fresh `env -i`, Python `-I -B`, dedicated account without production groups,
PrivateNetwork, AF_UNIX only, ProtectSystem=strict, read-only queue/data, inaccessible
production/home/secret paths, protected proc and empty capabilities. The gate's
only subprocess calls are read-only systemctl queries; strategy execution has no
subprocess or exchange access. There is no production environment file or loaded
credential in either research service. No runtime package downloads or network.

## Build and validation

```powershell
python -m unittest tests.test_evolution_worker tests.test_mean_reversion_research tests.test_evolution_research -q
python scripts/research/build_evolution_worker_release.py --commit HEAD --destination tmp/evolution-worker-release
```

The builder reads a fixed allowlist from Git objects, renders exact pinned unit
paths, emits file/release/archive SHA256 and refuses overwrite. No whole repository,
venv, production modules, data or credentials are packaged. Generated build files
are under ignored tmp/. Actual Pi fixture runs under a temporary, unprivileged
sandbox; no real worker units or timers are installed before approval.

The final installation review document records the exact commit, paths, package
size/hashes, units, validation evidence, installation commands and rollback. Approval
must precede service-account creation, copying the release to /opt, real systemd
unit installation or enabling the research timer.


## Bounded campaign v3 (authorized 2026-09-22)

The new pinned release includes campaign_v3.json: ten predeclared rolling windows,
five generations each, distinct fixed seeds and a later frozen-candidate assessment.
This is a retrospective study of the existing pure mean-reversion family, not a
restart of its rejected v1 study or the old trend/cash v2 run. Every date is seen /
exploratory. No historical production PASS, API calls or automatic monitor install.

Operator activation after release verification (full paths pinned to COMMIT):

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent /usr/bin/python3 -I -B /opt/trendatlas-research/releases/COMMIT/research_os/dev_only/evolution_worker/bootstrap.py activate-campaign --preregistration-commit 8ade6f8992b6d89a63109d621d1a78f6046823fa
sudo /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent /usr/bin/python3 -I -B /opt/trendatlas-research/releases/COMMIT/research_os/dev_only/evolution_worker/bootstrap.py enqueue --job-file /var/lib/trendatlas-research/first-job.json
sudo systemctl start trendatlas-evolution-dispatch.service
```

Never manually start the RefuseManualStart worker. The existing dispatcher and
worker gate preserve production priority. Its timer resumes committed SQLite
periods after preemption/reboot; one activation can process the finite remaining
campaign budget. Existing root queue remains read-only. campaign_queue is writable
only inside research state and every record must match the exact pinned definition.
BLOCKED anywhere prevents further campaign advancement. Expiry is not a fake REJECT.

Read-only status (no worker start, no SQLite writes):

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent /usr/bin/python3 -I -B /opt/trendatlas-research/releases/COMMIT/research_os/dev_only/evolution_worker/bootstrap.py status
```

Atomic status is /var/lib/trendatlas-research/status.json. Raw committed evidence:
queue.sqlite3; jobs/JOB/research.sqlite3 tables candidates, evaluations, populations,
generations, meta; immutable report.json/audit.json/SEALED.json at completion.
No large/sensitive logs are shown. Status distinguishes completed generation from
current generation and unique evaluated candidates from total period evaluations.
A checkpointed candidate can have only part of its folds complete; generation
selection always requires every fold. CPU seconds are for the current service
activation, not a fabricated cumulative value across reboots. systemd CPU accounting
is also returned when available. Timer admission can take up to 15 minutes plus jitter.

Temperature >75 C pauses; a persisted thermal latch clears only below 68 C. Sensor
failure pauses. Disk, 7200-second elapsed job deadline (including pauses), seven-day
campaign deadline and ten-experiment budget are fixed before execution. No automatic
deletion or widening. After all ten seal, the timer can safely remain idle: the finite
budget is exhausted, with a recorded reason. Next campaign requires new authorization.
