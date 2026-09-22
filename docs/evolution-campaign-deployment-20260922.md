# Bounded evolution campaign: all ten real Pi studies completed

Final observation 2026-09-22T21:17:54+02:00; branch `codex/bounded-evolution-campaign-20260922`.
The finite campaign completed naturally while deployment verification continued. All ten studies are SEALED HISTORICAL_REJECT. No historical qualification or production PASS is claimed.

## Final completion verified 2026-09-22T21:17:54+02:00

**10/10 experiments SEALED, all HISTORICAL_REJECT.** Every experiment completed
all five generations: 50 completed generations, 500 evaluated population slots,
260 candidate instances with backtests across experiments (250 globally distinct
gene hashes), and 1,430 persisted candidate/benchmark period evaluations.
Survivors reused immutable evaluations; these are not 500 independent candidates.
The tenth job is `btc_walk_forward_evolution_v3_20260922_w10`, generation 5 complete.

The worker is now inactive, PID 0, because `campaign_budget_exhausted` is recorded.
The timer remains enabled/active and will not fabricate extra work after its approved
finite budget. Earlier RUNNING evidence below proves real autonomous execution;
completion does not justify extending the campaign merely to keep a process busy.
No experiment was requeued, and no candidate qualified for a paper-monitor proposal.

Final temperature 47.4 C; state 53557834 bytes (~51.1 MiB),
free disk 1946746880 bytes (~1.81 GiB). Final interpreter CPU checkpoint
55.377 seconds covers its second activation only. Actual running memory/CPU evidence
and the thermal/memory correction are documented below. All ten SEALED manifests,
original release SHA256 and final resource-guard hashes were verified. All 447
production files/inventory, production controls, checkout HEAD and dirty status
again matched preflight. Both timers remain enabled/active.

Cash is 0% nominal return in every window. Table values are the frozen leader's
later retrospective assessment only; outcome gates also include all selection
folds and their continuous diagnostic, so a positive assessment alone cannot qualify.

| Experiment | Later assessment (seen/retrospective) | Candidate net return | Candidate fitness | BTC net return | Outcome |
|---|---|---:|---:|---:|---|
| 01 | 2021-07-01..2021-12-31 | +4.855% | +1.310% | +34.055% | HISTORICAL_REJECT |
| 02 | 2022-01-01..2022-06-30 | -3.274% | -13.221% | -56.590% | HISTORICAL_REJECT |
| 03 | 2022-07-01..2022-12-31 | +0.000% | +0.000% | -16.971% | HISTORICAL_REJECT |
| 04 | 2023-01-01..2023-06-30 | +4.142% | +8.306% | +83.512% | HISTORICAL_REJECT |
| 05 | 2023-07-01..2023-12-31 | -7.172% | -28.738% | +37.878% | HISTORICAL_REJECT |
| 06 | 2024-01-01..2024-06-30 | +0.000% | +0.000% | +43.800% | HISTORICAL_REJECT |
| 07 | 2024-07-01..2024-12-31 | +3.362% | +0.671% | +47.381% | HISTORICAL_REJECT |
| 08 | 2025-01-01..2025-06-30 | +4.521% | +3.869% | +15.449% | HISTORICAL_REJECT |
| 09 | 2025-07-01..2025-12-31 | -0.326% | -15.923% | -17.664% | HISTORICAL_REJECT |
| 10 | 2026-01-01..2026-06-30 | -1.290% | -8.376% | -31.454% | HISTORICAL_REJECT |

Final evidence: `tmp/campaign-pi-completed.json`. Next step is review of the rejected
family/campaign, not another unregistered search or production propagation.

## Authorization and exact root cause

The 2026-09-20 installation approval allowed only an empty queue. Consequently the
installed timer correctly stayed IDLE and did no historical computation. The user's
2026-09-22 request explicitly authorizes new preregistration, enqueue, real offline
Pi research and a finite follow-on campaign. That supersedes only the old empty-queue
restriction. It does not permit production edits, orders or automatic promotion.

A second host-specific finding was discovered during the live process check: the Pi
kernel has no memory cgroup controller (`cpuset cpu io pids` only). MemoryMax and
MemorySwapMax were configured but not enforced. Research alone was paused. An
independently pinned launch guard now enforces RLIMIT_AS=384 MiB and unprivileged
mlockall(CURRENT|FUTURE) before entering the original engine. The kernel, boot config,
production, swap device and credentials were not changed; no reboot was required.
The brief initial execution had observed RSS 29 MiB; its accepted input/code/criteria
and genuine results were preserved, not restarted or discarded.

## Frozen scientific scope and campaign

- Campaign `btc_walk_forward_campaign_v3_20260922`; first job
  `btc_walk_forward_evolution_v3_20260922`.
- Ten predeclared rolling experiments, 2019-07 through 2026-06 across their windows.
  Each selects on four consecutive six-month folds then freezes one champion before
  evaluating the following six months. Continuous selection diagnostics also gate
  turnover and cash performance. Assessment never enters selection or mutations.
- BTC short-horizon long-only mean-reversion pure math is unchanged from its prior
  implementation. The old eight-fold rejected study is not resumed. New rolling
  studies have explicitly fixed distinct seeds and new IDs, not renamed SEALED jobs.
- Exactly five generations, 10 candidates / 6 eligible survivors / 4 unseen adjacent
  one-gene mutations. A shortage of six eligible survivors fails closed. No extra
  generations or revised seed/domains after outcomes. Ten experiments is the total
  campaign ceiling, not a replenishable queue target.
- Costs 10 bps fees + 5 bps slippage each way; no short, <=0.75 opening target cap,
  no additions to held units, close-D signal / next-open fill and boundary exits.
  Turnover >24x disqualifies. Rank worst/median/mean net fitness, then candidate SHA.
- Cash is mandatory and BTC is reported. Qualification requires positive return AND
  fitness vs cash throughout the specified selection/continuous/assessment gates.
  Otherwise HISTORICAL_REJECT. Both outcomes retain complete unfavorable evidence.
- ALL historical data is seen/development/exploratory, explicitly including
  2025-01-01..2026-08-19. Overlapping windows and ten searches are multiple comparisons,
  not independent confirmations or an untouched holdout. No historical production PASS.
- Only a qualified result may create a non-executable paper-monitor proposal. Future
  observation is >=180 days starting after candidate freeze and separate review;
  2026-09-23 is only the earliest possible date, never backfilled forward evidence.
- Job deadline 7200 elapsed seconds from admission including pauses, 64 MiB/job;
  campaign seven days, 512 MiB state; free disk >=1 GiB+64 MiB. Expiry is BLOCKED for
  review, not a fabricated strategy rejection. Temperature >75 C pauses; only <68 C
  clears the persisted latch. Sensor failure pauses. No result deletion to make space.

## Provenance and deployment

Preregistration committed BEFORE implementation or historical computation:
`8ade6f8992b6d89a63109d621d1a78f6046823fa` -
`Preregister finite retrospective walk-forward campaign and thermal boundaries`.

Research release `d534035a216a134cce610f80eec32afb8f0461bd` -
`Run pinned bounded walk-forward campaigns with checkpoint and thermal guards`.

- Release directory: `/opt/trendatlas-research/releases/d534035a216a134cce610f80eec32afb8f0461bd`.
- Release SHA256: `75632b88261d821efb4329648b7e4fe2a96a8d35849717527cfd81e681b4deb4`.
- Archive SHA256: `9b8092c40070f379627eb30a1582fda8b293a7629cc47199178edf121dc2a070`.
- 24 manifest files; 134920 bytes unpacked / 37120 archive bytes.
- Frozen input SHA256: `4d71367947e5789ca807e42d98541a079bd5a0c04054ec58a6781e8cc6a77712`.
- Dedicated existing trendatlas-research account; immutable release root:root,
  directories 0755, files 0444. Existing state ownership/production permissions preserved.
- Only three research units and their research-only resource drop-in were installed.
  The existing dispatcher timer is the only enabled research scheduler.
- Backups: `/var/backups/trendatlas-research/20260922-d534035a/`.
- No second repository/venv copy, network/API/IML dependency or moving code symlink.

Final resource guard commit: 47661e4f74d41478f0202bbd26485aaf4c9666b6.
Initial memory fix: 2ecf69aa69f37d4a12868a08dcad6c090778d6e2.
SQLite hot-journal recovery: d5a70cf7; final busy-admission fix: 47661e4f.

- Separate immutable wrapper: `/opt/trendatlas-research/resource-guards/47661e4f74d41478f0202bbd26485aaf4c9666b6/memory_guard.py`.
- Wrapper SHA256: `6225a2933f848b32c549a998c5f7d7821940c56498c7968c8f7a85e050a7d872`.
- Research drop-in SHA256: `d99b646bb66e5d4208c9ac7debb1ca1e4db93b61ee7b1eb3e3ada6ea2366166f`.
- Dispatcher recovery drop-in SHA256: `7608f753c38b2f3beb0a28b359ddf9de42696ffa720bbe46de20c5422377e927`.
- Original research release, accepted job release hashes and SEALED artifacts remain
  byte-identical. The OS resource launch restriction adds no strategy change.
- Verified same-sandbox mlock probe before resume. Actual resumed worker has hard/soft
  address-space and lock limits 402653184 bytes, locked memory and zero VmSwap.
- Memory locks cover the historical computation interpreter's current/future pages.
  They do not survive exec in the tiny fixed read-only systemctl metadata helpers;
  those inherit the virtual-address limit. This audit does not claim the absent
  kernel controller enforces a cgroup-wide no-swap policy.

## Earlier real execution and resume evidence

At first verification, PID 475616 was RUNNING, generation 1, with 10 distinct
candidates and 47 committed period evaluations. This was historical Pi data, not
fixture/dry-run work. The first experiment later SEALED HISTORICAL_REJECT.

Research alone was paused to add the memory restriction while experiment w02 had
three committed generations and 115 period evaluations. It resumed from that exact
SQLite state with the same accepted code/input/spec. The first SEALED job's complete
file hashes were verified unchanged after resume.

At 2026-09-22T21:09:03+02:00:

- Current job `btc_walk_forward_evolution_v3_20260922_w03`, RUNNING, PID 478192.
- Generation 3 in progress, 2 complete;
  17 distinct candidate IDs have at least one committed evaluation,
  94 period evaluations. A partially evaluated candidate is never selected early.
- First two experiments SEALED HISTORICAL_REJECT; the next was generated solely
  from the pinned campaign, without changing parameters after reading results.
- Temperature 49.05 C; RSS 42192 kB, locked 42880 kB,
  swap 0 kB; one thread. Service CPU accounting 10.410 seconds
  in the current activation. No claim of cumulative CPU across prior activations.
- CPU cgroup `cpu.max=20000 100000`: 20% of one CPU, Nice19, idle-class IO.
- Research state 13993364 bytes; free disk 2124615680 bytes.
- Production and research dispatcher timers both enabled/active. Research continues
  without Codex, rolls forward through the fixed list, and stops at its finite budget.

## SQLite crash-recovery correction

Forced-process-exit tests create hot rollback journals in both a queue ledger and
an unsealed research DB. The original read-only ready/report calls cannot recover
these. The external pinned guard therefore acquires worker.lock non-blocking and
allows SQLite itself to roll back only those existing unsealed hot journals before
admission. No custom SQL updates, reselection or changes to the immutable engine.
SEALED DBs are never opened writable. The dispatcher retains the same gate and
production ordering; its recovery-only write permission is confined to research
state. A busy lock exits 255, not skipped-condition 1, to prevent this Pi's OnSuccess
behavior from replacing a pending worker stop during production preemption.

These tests passed on Windows and Pi, including a killed actual SQLite child writer.
A final isolated systemd fixture additionally verified the 255 admission behavior,
all twelve race cases and production-before-worker ordering. The final guard/drop-ins
are installed for subsequent eligible activation; exhausted campaign cannot restart.
No historical result or original engine release was changed for this launch-layer fix.

## Status, artifacts and next action

Simple read-only atomic snapshot:

```sh
sudo cat /var/lib/trendatlas-research/status.json
```

Read-only status including actual systemd PID and SQLite counters:

```sh
sudo /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent /usr/bin/python3 -I -B /opt/trendatlas-research/releases/d534035a216a134cce610f80eec32afb8f0461bd/research_os/dev_only/evolution_worker/bootstrap.py status
```

Queue ledger: `/var/lib/trendatlas-research/queue.sqlite3`.
Root-owned initial queue: `queue/<id>/study.json`; exact-authorized automatic jobs:
`campaign_queue/<id>/study.json`. Both are validated against the pinned campaign.
Per-job results: `/var/lib/trendatlas-research/jobs/<id>/research.sqlite3`, then
`report.json`, `audit.json`, `SEALED.json`. Atomic `status.json` also reports leader,
last completed experiment, pause reason, temperature, CPU time and next step.
The campaign has now finished its active populations and assessments.
There are no remaining preregistered jobs in this campaign. Production preemption and thermal/disk guards
may pause work; next eligible 15-minute dispatcher tick resumes the same study.
No BLOCKED job is silently replaced. No orders or production promotion follow results.

## Safety and regression evidence

- 70 local tests passed (68.652 s); the same 70 passed on Pi (76.600 s, 15.555 s CPU)
  under Nice19 / CPU20% / MemoryMax384M / no network. Their actual memory-cgroup
  limitation was subsequently discovered and corrected with the process guard.
- Five guard/recovery tests passed locally and on Pi; 75 unique tests total. Successful
  actual mlock probe passed under the worker sandbox, not merely a mocked syscall.
- Isolated dummy user-systemd arbitration: manual worker start refused, dispatcher
  cannot stop production, production preempts worker before its own start, repeated
  dispatch during preemption creates no overlap, all 12 admission races passed.
  Final re-run also proved ExecCondition=255 does not trigger OnSuccess when admission is busy.
  Real production service was never started/stopped for these tests.
- JSON parses, py_compile, git diff --check and systemd-analyze verify passed.
- All 447 protected production/config/authority/account/execution-journal/run file
  hashes AND inventory unchanged. Three production control hashes also unchanged.
  Production HEAD remains `1bb2d0d64363d111d92e4257d0a7345b484b8532`; dirty status identical
  to preflight (131 entries). Original Windows dirty checkout untouched.
- Three old local research DB hashes unchanged, including btc_cash_stability_v2_20260920.
  Old Pi release 2a2319cd remains immutable and available, never replaced in place.
- Actual worker mount namespace: production and secret file inaccessible; campaign,
  pinned input and operator queue read-only; only research state writable. Actual
  environment names only PATH, LANG, HOME. No key copied, read into worker or required.
- No order sent, no production promotion, no live strategy/authority edit, no API
  request, no full refresh or production scheduling change. No real account PnL claim.

## Required repository audit

FILES READ: full AGENTS.md; source_of_truth README/master_state/chat_roles,
relevant project_truth/export_contract/paths_registry/current_issues; canonical
script/output registries and registry_workflow; pi_codex_runtime_workflow; evolution
and worker CONTRACT/README; mean_reversion CONTRACT/study/controller/backtest;
Research OS v2 contract; old evolution/mean-reversion result audits; worker installation
and post-install audit; existing worker runtime/bootstrap/gate/units/tests and builder.

SOURCE OF TRUTH: latest explicit campaign authorization; classes B/C/D. Versioned
CAMPAIGN_CONTRACT.md/campaign_v3.json were committed before implementation. Existing
production strategy and authority truth are unchanged. These separate dev-only
states do not redefine Research OS v2 runs/ lifecycle enums or normalized account data.

Contract impact: finite preregistered automatic succession replaces operator-only
empty-queue operation for v3, with strict next-job equality and unique ledger records.
Historical-only outcomes and production isolation remain mandatory. Period checkpointing
adds crash recovery without changing the frozen pure strategy math or old SEALED code.

Forbidden old paths checked: production imports/submit/publish/full refresh; arbitrary
code/jobs; historical SEALED reset/requeue; API keys/IML; production git reset/pull/stash;
production units/credentials/data writes. No such operation was used.

Exact implementation/preregistration changed files and git-add set:

```text
canonical/output_registry.json
canonical/script_registry.json
research_os/dev_only/evolution_worker/CAMPAIGN_CONTRACT.md
research_os/dev_only/evolution_worker/CONTRACT.md
research_os/dev_only/evolution_worker/README.md
research_os/dev_only/evolution_worker/bootstrap.py
research_os/dev_only/evolution_worker/campaign.py
research_os/dev_only/evolution_worker/campaign_v3.json
research_os/dev_only/evolution_worker/gate.py
research_os/dev_only/evolution_worker/resource_guard/CONTRACT.md
research_os/dev_only/evolution_worker/resource_guard/dispatch-recovery.conf.in
research_os/dev_only/evolution_worker/resource_guard/memory_guard.py
research_os/dev_only/evolution_worker/resource_guard/worker-resource-limits.conf.in
research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-worker.service.in
research_os/dev_only/evolution_worker/walk_forward.py
scripts/research/build_evolution_worker_release.py
source_of_truth/paths_registry.json
source_of_truth/project_truth.json
tests/pi_evolution_arbitration_fixture.py
tests/test_evolution_campaign.py
tests/test_evolution_memory_guard.py
```

Exact deployment-audit git add list:

```text
git add source_of_truth/project_truth.json source_of_truth/master_state.md source_of_truth/current_issues.md docs/evolution-campaign-deployment-20260922.md tests/pi_evolution_arbitration_fixture.py
```

Audit commit message: `Record completed Pi campaign, historical rejection and recovery verification`.
Audit commit hash: supplied in the completion response (containing commit).
Local ignored evidence: tmp/campaign-pi-preflight.json, campaign-release-build.json,
campaign-all-tests.log, campaign-pi-tests.log, campaign-pi-arbitration.log,
campaign-pi-install.log, campaign-pi-first-running.log, campaign-memory-probe.log,
campaign-memory-resume.log, campaign-pi-final-verification.json,
campaign-pi-isolation.json, campaign-old-sealed-hashes.json, campaign-pi-completed.json,
campaign-final-resource-guard.json, campaign-final-guard-pi-tests.log,
campaign-final-guard-install.log, campaign-pi-final-arbitration.log. No credentials stored.
