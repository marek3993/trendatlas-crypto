# Recovery and migration audit — 2026-09-28

Verdict: **MIGRATION_COMPLETE**. The same experiment
`causal_nested_v1_20260927` recovered from 5,085 completed evaluations, reached
5,087 on Pi, resumed to 5,089 and 5,091 on VPS, then passed an actual administrative
stop at 5,112 and resumed again. The recorded running observation at 18:52 UTC
contains **5,213** completed evaluations, `failure=null`, `outer_opened=false`.
The experiment continues; this report does not claim the scientific search is finished.

## SOURCE OF TRUTH and exact cause

Class **C+B**. Production authority remains the repository `source_of_truth/`
contracts; this report is research operational evidence only. Scientific authority
remains the frozen `evolution_contract.json`, `anti_overfitting_contract.json`,
input manifest and SQLite state from engine commit
`53b6a5336ca1f7ce35b481a017f7e82396f3613c`. The new operational source contract is
[contract.json](contract.json), outside that engine. The original resume contract
and engine files were not edited.

The old worker had `KillMode=control-group`. During a controlled systemd stop,
SIGTERM also terminated its `/usr/bin/systemctl list-jobs --no-legend --no-pager`
helper. The generic CalledProcessError handler persisted FAILED at
2026-09-28T00:10:02.064303Z. Its audit event is separately timestamped
00:10:02.065609Z and remains present. This was an orchestration classification bug.

Contract impact: only bound administrative stops or verified post-timeout durable
checkpoints become resumable. An unbound SIGTERM and an invalid checkpoint remain
FAILED. Stop requests are activation-token/PID-bound; the worker lock prevents
concurrent writers; completed attempt/result/checkpoint relationships and both
database integrities are validated before CHECKPOINTED. An interrupted reservation
retains its attempt budget. Recovery records the original failure and complete
preserved table hashes before clearing only the current failure field. No
strategy, candidate genes, seeds, metrics, data, scientific budget or OOS rule changed.

## Credential incident resolved first

The compromised credential was the **Pi SSH password**, not the existing VPS
private key. A new Ed25519 administrative key was generated with restricted local
ACLs and its public key appended on Pi and VPS without removing existing access.
Independent key-only SSH and sudo checks succeeded on both hosts before rotation.
The Pi password was then replaced through an in-memory stdin channel; its encrypted
local DPAPI store was updated. The replacement password and new key were verified,
and the old password was rejected. The non-compromised VPS key was retained.
No credential value appears in code, logs, evidence, diffs or this report.
LeadPilot credentials were not changed. See [rotation evidence](evidence/credential-rotation.json).

## State preservation and migration

1. **Before:** FAILED, 5,085 evaluations, 5,093 attempts (5,085 COMPLETE,
   8 INTERRUPTED), 999 candidates, 2,925 trials, 210 populations, 2,056 scores,
   108 partial finalists. No open reservations; both SQLite integrity checks OK;
   outer unopened. AI ledger: 84 calls, 418,156 tokens, estimated USD 0.15706938,
   81 COMPLETE and 3 FALLBACK proposals. Frozen ceilings remain 96 calls, USD 1,
   86,400 active seconds and 512 MiB state storage.
2. **Recovery:** locked SQLite backup API snapshots of both databases; hashes of
   all science tables, metadata, audit events and proposal ledger matched live
   state. The exact authorized failure and counts matched. The original FAILED
   event remains; exactly one AUTHORIZED_RECOVERY event was added. Pi resumed to
   5,087 with exit 0 and no current failure, then all three research timers were
   disabled. Pi state and the original forensic archive remain available.
3. **VPS:** the package contained only frozen research code/data, repaired
   orchestration, manifests and checkpoint state. No Pi venv, production checkout,
   execution journal, signer, trading credential or order adapter was transferred.
   All 66 package entries matched sizes/SHA256. Fresh x86 Python 3.13.5, numpy 2.4.4,
   pandas 3.0.3, dateutil 2.9.0.post0 and six 1.17.0 match Pi. SQLite is 3.46.1 on
   Pi and 3.49.1 on VPS. System Python and LeadPilot dependencies were untouched.
4. **Resume:** 5,087 → 5,089 → CHECKPOINTED → restart → 5,091 → CHECKPOINTED.
   Comparison proved all rows from the transferred science tables still present
   and unchanged, with identical AI ledger. A normal unrestricted activation then
   reached 5,112; backup maintenance invoked the real ExecStop and obtained a
   successful checkpoint with zero open reservations. Restart subsequently reached
   5,213. The running sample has one legitimate active reservation, zero missing
   prior evaluations, no duplicate COMPLETE/evaluation mapping and no SQLite lock
   errors. Both integrities and foreign keys pass. Original 5,085 rows were also
   compared directly against the Pi 5,087 checkpoint and are all unchanged.

Evidence: [original-row preservation](evidence/preservation-5085-to-5087.json),
[two VPS resume cycles](evidence/vps-validation-5091.json),
[actual stop and isolation](evidence/vps-real-stop-and-isolation.txt),
[running observation](evidence/vps-final-running.json).

## Hashes and cross-architecture replay

| Artifact | SHA256 |
|---|---|
| Frozen fingerprint | `eeb244ea6a79ef396f8f607696eebe08115b4a3a3bb16d4e74d0d251df0d8385` |
| Frozen manifest, Pi and VPS | `1f92cd047b2d39cc071984f57485beaafbb560b935fd23109c9f121154af0abc` |
| Original 5,085 forensic archive | `98658cdf8687b7fd498a3cf953b439d5712869613b3077621028066c2ffab0ca` |
| Pi 5,087 checkpoint archive | `3ecf5101bee3a19993b500835e1521d4f2a2a53d1b78ff236ce151921107e8e8` |
| Transferred package archive | `9cfa5c74d8b57992620333a2d5d5c41399712d8c9b4280c6b09ac0717a5fa264` |
| 5,087 candidates.sqlite | `5457c1d146ae3d7825dec926cb0d13b82ea1b13c596f578c98b48715254ad720` |
| Proposal database | `b9f962fd154bedc05198ca1c07ae96517d4150b299e0bbe23b6c23efc16ae909` |
| 5,112 export manifest | `8ea25401ced71be4377f8530ed8ff80e72a41f568368f9028500f6280c1686ea` |

Per-file package manifest is retained on VPS as
`/opt/trendatlas-research/migration-SHA256.json`; subsequent orchestration changes
and all seven installed units have a separately verified
`/opt/trendatlas-research/deployment-SHA256.json`.
[Transfer sizes/hashes](evidence/transfer.json) and
[final deployed code hashes](evidence/deployment-SHA256.json) are versioned.

Existing candidate `F_43882aab02ff`, seed 1701, the 2023-02-02 to 2023-06-01
inner-validation slice and `double_cost` stress were selected before either replay.
The frozen prefix-audit tolerance (rtol/atol 1e-10) was declared before results;
signals and discrete fields require exact equality. Results were **exactly equal**:
signals, three fills, daily returns/NAV, metrics and audit, maximum delta 0.
The comparison normalizes nonfinite values to null and checks their masks; it is
an exact numeric comparison, not a claim that platform-specific environment JSON
or serialized NaN payloads are byte-identical.

One worker only: the frozen engine uses an exclusive flock and does not support
parallel leases. Two/three-worker benchmarks were therefore not attempted.
The same fixed replay took 30.9904 s on Pi (20% CPU cap) and 6.2437 s on VPS:
**4.96× measured wall-clock speedup under these deployed resource policies**.
The bounded Pi activation produced 2 results in 45.004 s (2.67/min); the first two
VPS activations produced 2 in 9.056 s and 2 in 9.225 s (about 13.2/13.0 per minute).
Those activation slices differ and include cache traversal; they are not a forecast
of whole-experiment speedup. [Replay evidence](evidence/replay-comparison.json).

## Isolation, production health, backup and export

- VPS has 4 vCPU, 8,122,306,560 bytes RAM, no swap. Worker observed peak RAM
  215,449,600 bytes, one task; limits are 4.5 GiB, swap 0, CPU quota 300%, weight
  10, nice 10 and idle I/O. Broker limit is 512 MiB/20%. Post-check disk free
  68,807,081,984 bytes, about 10.48% used; available RAM about 7.17 GB.
- Worker and three research timers are enabled for boot. Dispatcher resumes
  successful checkpoints; Restart=on-failure handles valid timeout checkpoints.
  Invalid FAILED states remain blocked by admission. Full VPS reboot was not
  performed because it would restart LeadPilot; service stop/restart/resume and
  boot enablement were verified instead.
- Real worker namespace checks denied external networking, LeadPilot secrets,
  Docker socket, root/ubuntu SSH directories and the broker credential. Separate
  broker namespace checks denied experiment DB, inputs, LeadPilot and Docker while
  permitting only its mailbox and research credential. The frozen broker restricts
  endpoint and development-only payloads. Research users have neither docker nor
  sudo groups. Public ports remain 22/80/443; no new public port or firewall change.
  This proves the new research deployment has no signing/order capability; it is
  not an unsupported claim about every pre-existing unrelated file on the VPS.
- LeadPilot API/frontend/database are healthy, proxy running; all four container
  IDs and StartedAt values match baseline and restart counts remain zero. Compose
  and Caddy hashes match. Authenticated HTTPS `/` and `/health/ready` return 200
  (sample 0.156/0.062 s). Initial guessed `/api/health*` paths returned 404; inspection
  of the existing healthcheck and routing identified the correct unchanged route.
- Pi production HEAD, dirty-diff hash, working-tree inventory, all four production
  unit hashes and all execution-journal hashes match baseline. Production timer,
  watchdog and dashboard remain enabled/active; the production service's normal
  inactive/success state is unchanged. Pi research remains disabled/inactive at
  5,087, MainPID=0. No simultaneous Pi/VPS experiment worker occurred.
- Unsigned read-only exchange `/info` at 18:54 UTC found zero fills since 17:00 UTC
  and zero open orders. `live_order_chain=NOT_INVOKED`, `real_order_sent=false`.
  This does not imply marked balances or market prices stayed constant.
- Daily 03:30 UTC SQLite-safe backup and root-owned read-only export verified at
  `/var/backups/trendatlas-research/20260928T184709Z` and
  `/srv/trendatlas-research-export/20260928T184709Z`; `latest` selects the export.
  Seven daily/four weekly retention, newest checkpoint protection, dedicated
  logrotate and disk-warning health JSON are installed. No research-to-production
  deployment exists. Both original and migration archives also remain on Windows
  under `.codex/tmp/causal-migration-20260928`.
- Pi had less than its frozen 1 GiB disk reserve. Only the two regenerable APT
  binary caches `/var/cache/apt/pkgcache.bin` and `srcpkgcache.bin` were removed
  while APT services were inactive, restoring the reserve. Production paths and
  scientific limits were not altered.

## Regression tests and validation commands/results

- `python research/causal_migration/test_runtime.py --engine <frozen> -v`:
  **9 passed** on Windows, Pi ARM64 and VPS x86_64. Includes expected helper stop,
  cooperative interrupted reservation, unexpected signal FAILED, other helper
  failure FAILED, stale stop rejection, verified hard timeout, invalid timeout,
  repeated stop/start preservation and exact 5,085 synthetic accounting recovery.
- `python research/causal_migration/test_replay.py -v`: **5 passed**.
- `python research/causal_migration/test_maintenance.py -v`: **2 passed**.
- Existing `test_resume.py --engine <frozen> -v`: **17 passed**, unchanged.
- From frozen root, `python -m unittest research.causal_evolution.tests
  research.causal_evolution.vendor.test_research`: **45 passed**, unchanged.
- `systemd_probe.py`: **3 real systemd scenarios passed** on Pi: administrative
  stop CHECKPOINTED/success; unexpected signal FAILED/exit-code; hard timeout
  CHECKPOINTED with systemd failed/timeout retained. Synthetic state only.
- `systemd-analyze verify` research units: exit 0. Only unrelated pre-existing
  xfs CPUAccounting deprecation warnings on VPS; old Pi oneshot RuntimeMax warnings.
- `logrotate --debug /etc/logrotate.d/trendatlas-research`: exit 0.
- SQLite backup/integrity/FK, manifest checks, prior-row comparisons, real resume,
  namespace probes, health checks and frozen hash verification: passed.
- `git diff --check`: passed. Generic unittest discovery was initially invoked
  without the required `--engine`; corrected explicit invocation passed. A first
  audit assertion looked for a failure object inside the old event; inspection
  confirmed that legacy events store status/reason/time separately. Corrected
  event verification proves the original event remains. Neither diagnostic
  changed experiment state or relaxed scientific invariants.

## FILES READ

In the required order: `source_of_truth/README.md`, `master_state.md`, `chat_roles.md`,
`project_truth.json`, `export_contract.json`, `paths_registry.json`,
`current_issues.md`; `canonical/script_registry.json`, `output_registry.json`,
`registry_workflow.md`; then `source_of_truth/pi_codex_runtime_workflow.md`.
Also AGENTS.md; the supplied original migration request and previous audit REPORT;
frozen `evolution_contract.json`, `anti_overfitting_contract.json`, `protocol.py`,
`resources.py`, `store.py`, `locking.py`, `evaluator.py`, `controller.py`, `designer.py`,
`mailbox.py`, vendor ledger/signals/common modules and tests; prior
`causal_resume/{README.md,contract.json,runtime.py,deploy.py,test_resume.py,audit.py}`
and its evidence; live frozen manifests, SQLite schema/metadata/audit records,
research unit definitions, production-unit hashes and health baselines. For the
unsigned account check, only the existing read-only snapshot request schema was
read; production execution scripts were not invoked.

## Exact files changed, forbidden paths, git handoff

All additions are under `research/causal_migration/`: contract, runtime, unit renderer,
broker, snapshot/maintenance/replay helpers, systemd probe, three test files,
logrotate configuration, README, this report, exact add list and sanitized evidence.
The exhaustive path list is [GIT_ADD.txt](GIT_ADD.txt).

Forbidden old paths checked: no diff to frozen `research/causal_evolution` or
`research/causal_resume`; no production `source_of_truth`, generated `outputs/*`,
`data/*`, frontend, production adapters or authority snapshots changed. Active
research ExecStart uses this wrapper, not frozen cli.py or the old resume wrapper.
Pi `/opt/market_regime_v1` and `/opt/home_automation` are untouched. LeadPilot Compose,
PostgreSQL, Caddy, credentials and volumes were not modified. `main` was neither
changed nor merged. No full-refresh or live-order command was run.

Commit message: `Recover causal experiment and migrate isolated research to VPS`.
Push target: `origin codex/causal-continuous-evolution-20260927`.

Commit hash: recorded in the final handoff and the external
`REPORT_RECOVERED.md` after commit/push. This versioned report cannot contain its
own commit hash; resolve it with `git log -1 --format=%H -- research/causal_migration`.
