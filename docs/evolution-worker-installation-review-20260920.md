# TrendAtlas Evolution Worker — READY FOR REVIEW, NOT INSTALLED

Implementation and synthetic Pi validation are complete. **STOP before permanent
installation**, as explicitly required by user requirement 20. Approval requested
only for this pinned release, dedicated service account and three research units
with an **empty historical-research queue**. No new historical study, production
strategy, live order, IML, AI API or paper-monitor installation is included.

## Exact release

Source commit: `2a2319cd4bd2a2655e3b999ffa75802bf2136020`.
Message: `Prepare isolated pinned Pi evolution worker for installation review`.
Branch: `fix/pi-authority-outage-recovery-20260920`.

Release SHA256:
`685659d6e069f96fade59096ea42e381bf0f1ba1418396550cdeb51a55445651`.
Archive SHA256:
`cf18d30d9812aaef13a99ca4405377c6f93e6af2dcd6b0bee5f844cb9bef8e1d`.
Local archive: `tmp/evolution-worker-release-v1.tar.gz` in the research worktree.
Pi staged archive: `/tmp/trendatlas-worker-review-2a2319cd/release.tar.gz`.

Twenty allowlisted files plus manifest.json; **77,992 bytes unpacked**, **26,135
bytes compressed**. No repository clone, .git, virtualenv, production modules,
historical generated outputs, API clients or credentials. The builder reads only
committed Git objects; the manifest pins every file and the aggregate release.
The result/audit commit containing this document does not change the release pin.

## Exact proposed paths and ownership

| Path | Owner / role |
|---|---|
| `/opt/trendatlas-research/releases/2a2319cd4bd2a2655e3b999ffa75802bf2136020/` | root:root; directories 0755, files 0444; pinned code |
| `/opt/trendatlas-research/input/BTCUSDT_1d.csv` | root-owned placeholder; service-private read-only bind of production OHLCV |
| `/var/lib/trendatlas-research/` | trendatlas-research:trendatlas-research, 0750; only persistent research write root |
| `/var/lib/trendatlas-research/queue/` | root:trendatlas-research, 0750; operator queue, additionally mounted read-only to worker |
| `/var/lib/trendatlas-research/queue/<job_id>/study.json` | operator-owned preregistered job, worker read only |
| `/var/lib/trendatlas-research/queue.sqlite3` | duplicate/admission/resume ledger |
| `/var/lib/trendatlas-research/worker.lock` | precreated trendatlas-research:trendatlas-research, 0640; both operator enqueue and worker lock it |
| `/var/lib/trendatlas-research/jobs/<job_id>/` | frozen accepted spec/input, report, audit and immutable seal |
| `jobs/<job_id>/outputs/research_os/dev_only/mean_reversion/<job_id>/research.sqlite3` | unchanged engine's transactional database, under the state root above |
| `/var/lib/trendatlas-research/staging/<job_id>/` | unpublished initialization only, safe restart cleanup |

Account: system user/group `trendatlas-research`, no home, shell
`/usr/sbin/nologin`, no production groups, sudo, key files or environment files.
Neither this account nor `/opt/trendatlas-research` has been created yet.

## Exact units to install, without production edits

The fully rendered files are in `tmp/evolution-worker-release-v1/units/` locally
and `/tmp/trendatlas-worker-review-2a2319cd/release/units/` on Pi. They reference
the full pinned release path above, not HEAD or a moving current symlink.

| New unit in /etc/systemd/system | Activation / purpose |
|---|---|
| `trendatlas-evolution-dispatch.timer` | the only enabled research unit; boot +10 min, then 15 min after dispatcher inactivity, jitter <=30 sec |
| `trendatlas-evolution-dispatch.service` | finite queue and admission check; read-only systemd queries |
| `trendatlas-evolution-worker.service` | indirect activation only; finishes one frozen queued study then exits |

Templates with exact directives:
`research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-worker.service.in`,
`trendatlas-evolution-dispatch.service.in`, `trendatlas-evolution-dispatch.timer`.
The sole template substitution is `@RELEASE@` to the pinned path above.

Production priority is enforced using research-only dependencies: worker
`Conflicts=mrv1-production.service`, `After=mrv1-production.service`,
`RefuseManualStart=yes`; dispatcher `After=mrv1-production.service`,
`OnSuccess=trendatlas-evolution-worker.service`,
`OnSuccessJobMode=ignore-requirements`. This admission mode retains ordering but
does not enqueue a stop of production when admitting research. A normal production
start stops the research cgroup before production's ExecStart. Research cleanup
is bounded by `TimeoutStopSec=2s`, then SIGKILL; no production lock is acquired.

The dispatcher is the **only** indirect worker activation source. It rejects an
active/activating/deactivating worker or any pending worker job. This guard is
essential: repeated dispatch must never replace the worker's pending stop during
production preemption. The worker independently requires production inactive
after a successful completed pass, production timer enabled/active and no pending
production job. Failure/auto-retry and the period before the first successful
production pass after boot block research. No production unit or drop-in is edited.

This uses the documented [systemd 257 unit dependencies and OnSuccess job modes](https://github.com/systemd/systemd/blob/v257/man/systemd.unit.xml)
and was exercised on isolated dummy units on this Pi. It is a constrained
single-dispatcher design; do not add another Wants/Requires/timer/start path.

## Security and resource boundaries

- Runtime is local Python standard library: no OpenAI API or AI-credit usage,
  networking, IML, exchange/order adapters or production strategy imports.
- `env -i`, `python3 -I -B`, no EnvironmentFile or LoadCredential. Dedicated UID,
  inaccessible production checkout, home, `/etc/default`, credential stores and
  `/run/credentials`; invisible other-user processes. Production environment
  and Hyperliquid/Supabase secret paths are unavailable to the research process.
- `PrivateNetwork=yes`, AF_UNIX only, `IPAddressDeny=any`, empty capabilities,
  NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateDevices/PrivateTmp,
  protected kernel/control groups/proc, restricted syscalls, no executable writable
  memory. Read-only production CSV bind; only research state is persistently writable.
- Nice **19**, idle IO class (`IOSchedulingClass=idle`, equivalent to ionice class 3),
  CPUQuota **20% of one CPU**, CPUWeight/IOWeight 1, MemoryHigh **256 MiB**,
  MemoryMax **384 MiB**, MemorySwapMax 0, TasksMax 16, per-file limit 128 MiB.
  Dispatcher: CPUQuota 5%, MemoryMax 64 MiB, 15-second startup timeout.
- Worker activation runtime limit 35 minutes, each frozen engine generation still
  limited to 300 seconds. Limits never expand the experiment or change its budget.
- Free-space guard: at least **1 GiB + 64 MiB headroom** before work and each
  generation. **512 MiB state budget is a pre-generation software guard, not a
  filesystem quota**; one operation can cross that threshold and subsequent work
  pauses. The OS separately caps each file at 128 MiB. No automatic result deletion.
- Prior real historical DB size was about **20 MiB**. Reserve **64 MiB per similar
  study** including rollback journal/input/report. Synthetic fixture used **1,880,952
  bytes**. Pi had **2,021,085,184 bytes (~1.88 GiB) available** on / before/after
  validation. Release itself is below 0.1 MiB plus filesystem allocation overhead.

The current engine accepts its already-frozen domain/seed/budget/cost/ranking
contract. A separately preregistered ID, input hash, date folds and base commit
can be admitted before a run. Unknown engines or changed semantics are rejected.
No arbitrary script/import/command can be supplied in a queue record. Existing
SEALED IDs and a renamed copy of the rejected mean-reversion specification are
denied. A new strategy family requires another reviewed release and preregistration.

HISTORICAL_REJECT -> SEALED and STOP. HISTORICAL_QUALIFIED_AWAITING_FORWARD ->
frozen candidate genes/hash and **JSON proposal only** for read-only monitoring;
no automatic installation or production PASS. After completion, another job can
run only if an operator explicitly preregistered and queued it. Empty queue is idle.

## Validation completed before this approval request

`python -m unittest tests.test_evolution_worker tests.test_mean_reversion_research tests.test_evolution_research -q`:
**60 tests passed** (17 worker + 43 existing), final run 20.578 seconds.

Worker regressions cover real synthetic five-generation runs; exact 10/6/4;
reboot/interruption resume matching uninterrupted results; interrupted atomic
initialization; a child killed with an open SQLite transaction and hot-journal
recovery; changed queue/code/input rejection; frozen-input use after source changes;
duplicate study rejection; SEALED immutability and idle replay; qualified proposal
only; no-queue idle; fixture admission restriction; credential-env rejection;
disk pause; single worker lock; immutable atomic files; production/link path denial;
production/worker pending-job guards; systemd boundary directives.

Pi: aarch64, Python **3.13.5**, systemd **257.9-1~deb13u1**. `systemd-analyze verify`
accepted all three rendered research units without installing them.

`tests/pi_evolution_arbitration_fixture.py` ran random dummy units in the **user**
manager, never real production: manual worker start refused; dispatcher did not
stop dummy production; worker terminated before production; re-dispatch during a
deliberately delayed stop caused no overlap; **12 admission races without overlap**.
It removed its temporary unit files. Initial fixture iterations exposed an unsafe
re-dispatch case, now guarded, and systemctl 257's non-JSON list-jobs output, now
strictly parsed. The final fixture passed. Real production was never started,
stopped, restarted or reloaded for these tests.

One **new synthetic fixture**, not historical research, ran in the transient
`ta-evo-review-2a2319cd.service` sandbox with UID 65534 (nobody), no production
groups, the core worker mount/credential/network/resource boundaries, temporary
code/state bind mounts and a read-only BTC file alias. It executed 5 generations,
26 evaluated candidates, sealed the expected flat-price HISTORICAL_REJECT, then
verified a second invocation was IDLE without changing sealed artifacts.
Sandbox assertions confirmed production hidden, secret paths denied, input mount
read-only, AF_INET socket creation denied, and Nice 19. Systemd reported success,
**4.978 seconds wall time**, **1.011 seconds CPU time**. The real service account,
permanent state paths and timer have not yet been installed or exercised.

Fixture audit:
`/tmp/trendatlas-worker-review-2a2319cd/state/jobs/fixture_flat_prices_v1/audit.json`.
Local captured evidence: `tmp/evolution-worker-pi-fixture.json`,
`tmp/evolution-worker-pi-fixture-systemd.log`, `tmp/evolution-worker-pi-preservation.json`.
Temporary /tmp artifacts can disappear after reboot; the committed review retains
the results and the pinned builder can reconstruct code. No fixture is enqueued
into the proposed permanent queue.

## Production preservation evidence

Before/after production HEAD: `1bb2d0d64363d111d92e4257d0a7345b484b8532`.
125 existing dirty entries preserved; git status porcelain SHA256 unchanged:
`656adf7c7372ff9721a977e75b56fbf10adc6e583240bc8b01bbad09934e5167`.
No diffs in production `config`, `configs` or `scripts`. No reset, stash, fetch,
pull, checkout, production snapshot edit, runtime-data cleanup or deployment.

| Unchanged file | SHA256 |
|---|---|
| `/etc/systemd/system/mrv1-production.service` | d61d44e83e8ebd1703ac1904bdeb5357a54aa0f8cc1b36aec05bfdd148570624 |
| `/etc/systemd/system/mrv1-production.timer` | 910fe5499e14af959b2de9ace5cd4195361eadcc919a86bcf83b03648495bb2f |
| `/etc/default/trendatlas-multi-account` | 62f51063bedd9f774fc9955adef69ff0ebe4b3c9cf934201350fe29762cd7165 |

The environment file was hash checked only, never printed or copied. Research
processes could not access it. Production remained inactive/success since
2026-09-20 09:12:12 CEST; `mrv1-production.timer` remained **enabled and active**,
next scheduled for 2026-09-21 02:10:00 CEST. There are no installed
`trendatlas-evolution-*` unit files and no `trendatlas-research` account.

Old local historical databases retained their recorded SHA256:
pilot `e4b62b383bc2a6195574351902d48b54c25a93838ad281b7972f3e86f0bf94ce`;
v2 `1e0446bad7cf09965c7674aa9c3471f4d9db72c3e46b1f9fc2441eaa743a35fe`;
mean-reversion `1724fbd2fe1b5cf9b28bfa263c8a1e35ec0731adac7b8b9f912ea3d9e6a373ce`.
Neither frozen engine, either original test suite nor their contracts were edited.

## Installation actions proposed only after approval

1. Recheck production commit/status/unit/config hashes, timer enabled and disk reserve.
2. Verify the staged archive SHA256 above; recreate staging from the pinned Git
   commit if /tmp was cleared. Extract **only** into the new exact release directory.
3. Create dedicated account; set root-owned read-only release and input placeholder;
   create research state and root-owned empty queue. No production directories change.
4. Install only the three rendered research units; verify them, reload systemd,
   and enable/start only the dispatcher timer. Do not start production or directly
   start the RefuseManualStart worker. Keep historical queue empty.
5. Recheck production preservation, research permissions/units and idle behavior.
   Admit no new historical study without a separately reviewed preregistration.

Exact shell outline for review (NOT executed):

```sh
research_release=/opt/trendatlas-research/releases/2a2319cd4bd2a2655e3b999ffa75802bf2136020
research_archive=/tmp/trendatlas-worker-review-2a2319cd/release.tar.gz
printf '%s  %s\n' cf18d30d9812aaef13a99ca4405377c6f93e6af2dcd6b0bee5f844cb9bef8e1d "$research_archive" | sha256sum -c -
sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin trendatlas-research
sudo install -d -m 0755 "$research_release" /opt/trendatlas-research/input
sudo tar -xzf "$research_archive" -C "$research_release" --no-same-owner
sudo chown -R root:root "$research_release"
sudo find "$research_release" -type d -exec chmod 0755 {} +
sudo find "$research_release" -type f -exec chmod 0444 {} +
sudo install -m 0444 /dev/null /opt/trendatlas-research/input/BTCUSDT_1d.csv
sudo install -d -o trendatlas-research -g trendatlas-research -m 0750 /var/lib/trendatlas-research
sudo install -o trendatlas-research -g trendatlas-research -m 0640 /dev/null /var/lib/trendatlas-research/worker.lock
sudo install -d -o root -g trendatlas-research -m 0750 /var/lib/trendatlas-research/queue
sudo install -m 0644 "$research_release/units/trendatlas-evolution-worker.service" /etc/systemd/system/
sudo install -m 0644 "$research_release/units/trendatlas-evolution-dispatch.service" /etc/systemd/system/
sudo install -m 0644 "$research_release/units/trendatlas-evolution-dispatch.timer" /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/trendatlas-evolution-worker.service /etc/systemd/system/trendatlas-evolution-dispatch.service /etc/systemd/system/trendatlas-evolution-dispatch.timer
sudo systemctl daemon-reload
sudo systemctl enable --now trendatlas-evolution-dispatch.timer
systemctl is-enabled mrv1-production.timer
```

Precreate worker.lock with the dedicated user's ownership before the first root
enqueue; otherwise a first root enqueue could create a root-owned lock the worker
cannot open. The outline is for the verified absent/new installation, not a command
to overwrite an existing lock or release during an upgrade.

Rollback: disable/stop only `trendatlas-evolution-dispatch.timer`, stop the
research dispatcher and worker, leave all research state/releases for audit.
No production stop, timer disable, checkout operation or strategy change is needed.

## Required repository audit

**FILES READ:** AGENTS.md; source_of_truth README/master_state/chat_roles,
relevant project_truth/export_contract/paths_registry, current_issues; canonical
script/output registries and registry_workflow; complete Pi runtime runbook;
Research OS v2 and run-folder contracts; evolution and mean_reversion contracts,
controllers/backtests, v2 and mean-reversion result audits; new worker contract,
implementation, units, builder/tests; systemd 257 primary documentation. Pi reads
were limited to environment/platform metadata, status, file modes and hashes;
no credential values were requested or exposed.

**SOURCE OF TRUTH:** user-authorized B/C worker scope and new
`local_evolution_worker` SSOT entry; existing production authority/export contracts
remain authoritative. New worker CONTRACT.md was written and validated before
implementation. Research artifacts remain non-authoritative historical evidence.

**Root cause / contract impact:** prior controllers needed manual local generation
calls and lacked a Pi-specific finite queue, secure release, admission priority and
crash-safe host lifecycle. This adds those infrastructure boundaries around the
unchanged engine; it does not change strategy math, rejected studies, production
configuration or Research OS v2 run-folder lifecycle enums.

**Forbidden old paths checked:** `/opt/market_regime_v1`, `/opt/home_automation`,
production/authority outputs, keys/environment and old SEALED artifacts were not
written. Only temporary fixture artifacts and temporary dummy user/transient test
units existed on Pi; no permanent research install occurred.

**Exact changed files / git add list for implementation commit:**

```text
git add canonical/script_registry.json canonical/output_registry.json source_of_truth/project_truth.json source_of_truth/paths_registry.json research_os/dev_only/evolution_worker/CONTRACT.md research_os/dev_only/evolution_worker/README.md research_os/dev_only/evolution_worker/__init__.py research_os/dev_only/evolution_worker/runtime.py research_os/dev_only/evolution_worker/bootstrap.py research_os/dev_only/evolution_worker/fixture.py research_os/dev_only/evolution_worker/gate.py research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-worker.service.in research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-dispatch.service.in research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-dispatch.timer scripts/research/build_evolution_worker_release.py tests/test_evolution_worker.py tests/pi_evolution_arbitration_fixture.py
```

Review-only commit add list:
`git add docs/evolution-worker-installation-review-20260920.md`.
Message: `Record Pi worker validation and stop for installation approval`.
Its hash is reported in the completion response; it does not alter the pinned
implementation release. JSON contracts and `git diff --check` passed. Build/fixture
artifacts remain ignored and no generated production/data outputs are committed.
