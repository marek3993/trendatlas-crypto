> Current new-release authorization (2026-09-22): see
> [CONTINUOUS_CONTRACT.md](CONTINUOUS_CONTRACT.md). The installation-only v1 and
> bounded v3 campaign rules below are historical for their respective pinned
> releases and SEALED artifacts. Continuous cycles use a separate state namespace.

# Local Pi Evolution Worker contract

Classes B/C; authorized implementation and fixture validation, installation pending
explicit approval. This adds an isolated execution host for preregistered studies,
not a new strategy, experiment, production scheduler or revision of sealed results.
Existing evolution/mean_reversion code, math, contracts and SEALED files stay frozen.

## Release, queue and deterministic execution

- Build a small allowlisted release from a committed source revision. No git checkout,
  virtualenv copy, credentials, production modules or generated historical outputs.
  Install only after approval under /opt/trendatlas-research/releases/<commit>/.
  manifest.json pins every file's SHA256 and an aggregate release SHA256. Unit paths
  reference that exact release, never a moving branch or mutable current symlink.
- Initially support the frozen BTC mean-reversion engine, whose controller already
  owns real backtests, adjacent mutations and SQLite generations. A thin adapter
  supplies a separately preregistered study and research-only state root. No changes
  to the engine's math or old code hash. Legacy evolution results remain sealed.
- Queue records are local JSON files named queue/<job_id>/study.json. They bind
  job ID, immutable study, preregistration commit, release SHA256, input basename and
  SHA256, and research/fixture mode. Only an operator can enqueue. No AI service,
  network, new seed, domain expansion, generated experiment or infinite search.
- A job's frozen study keeps its 5 generations of 10 -> 6 + 4 and every original
  seed, fold, parameter domain, cost, ranking and qualification rule. The worker
  runs all remaining generations automatically, then exports a final audit and stops.
- Old SEALED study IDs/spec fingerprints are denied as new research jobs. Duplicate
  IDs and study fingerprints are recorded in a durable queue ledger. A changed
  queued job or release/input hash fails closed; never silently update a running job.
- Queue is operator-owned read-only to the worker. Its accepted JSON is copied
  atomically into job state before execution. One advisory OS lock covers the worker;
  ledger claims and each engine generation use SQLite transactions, synchronous FULL.
  Initialization builds in a staging directory and atomically renames to its final
  job root, so an interrupted initialization never presents a partial live database.
- Reboot/preemption resumes the same accepted job and engine DB. Uncommitted
  generations roll back; committed generations are not rerun. Report publication
  is atomic and deterministic; an already-published file must match exactly.
- HISTORICAL_REJECT seals and stops. HISTORICAL_QUALIFIED_AWAITING_FORWARD freezes
  candidate genes/hash and writes a JSON proposal for read-only paper monitoring.
  Neither result installs a monitor, changes production or opens another experiment.
- SEALED engine DBs are read only. A final seal records database/report/accepted-spec
  hashes; repeated worker invocations verify them without rewriting them. Never
  describe historical qualification as production PASS.

## Isolation and priority

- Dedicated unprivileged trendatlas-research user, no login/home/supplementary
  production groups. Fresh allowlisted environment, Python isolated mode, no IML,
  OpenAI/client APIs, exchange/order imports, subprocesses in strategy execution,
  Supabase admin key, Hyperliquid key or multi-account environment.
- Only code explicitly allowed in the pinned manifest is imported. Historical
  BTC CSV is bind-mounted read-only to /opt/trendatlas-research/input/BTCUSDT_1d.csv;
  production checkout and secret directories are inaccessible to the service.
  A per-job input copy is hash checked and immutable; production refreshes cannot
  change an accepted job. Production source data is never edited or refreshed.
- All persistent research writes are under /var/lib/trendatlas-research. Code,
  queue and data mounts are read-only; PrivateNetwork, empty capabilities,
  NoNewPrivileges, ProtectSystem=strict, protected home/proc/devices/kernel,
  restricted address families and syscall classes defend the boundary.
- Nice=19, idle-class IO, CPUQuota=20% of one CPU, MemoryMax=384M, TasksMax=16.
  At least 1 GiB free disk plus 64 MiB operation headroom, 512 MiB research-state
  budget, 128 MiB per file, 5 MiB input and 10,000 input bars. Check before work
  and each generation; low disk pauses without changing study semantics.
- Production unit files, timer, checkout, credentials and existing runtime data
  are unchanged. Never acquire the production lock or request production stop/start.
- Proposed arbitration uses three research-only units. A timer invokes a tiny
  dispatcher. OnSuccessJobMode=ignore-requirements activates a RefuseManualStart
  worker, preserving ordering while preventing research activation from queuing
  a stop of production. Worker Conflicts= and After=mrv1-production.service mean
  a normal production start stops the whole research cgroup before production
  runs. ExecCondition separately requires production inactive after a successful
  completed pass, its timer enabled, and no production start job pending.
  Do not connect the timer or any Wants/Requires directly to the worker.
- The single dispatcher must also require the worker inactive/failed with no
  pending worker job. This prevents a repeated dispatch from replacing the stop
  job during production preemption. It is ordered after production, and is the
  only configured indirect worker activation source; manual worker start is refused.
- Verify this asymmetric ordering on isolated dummy units, including the admission
  race and worker preemption, without touching real production. Until proven on the
  Pi systemd version, the installation review must remain blocked. Direct manual
  worker start is refused. Runtime preemption is bounded to two seconds with
  control-group kill; SQLite recovers on next admitted attempt.
- Timer checks only the finite operator queue. No job means idle. Each activation
  handles at most one job. Errors pause/block that job, not retry strategy tuning.

## Validation / approval boundary

Test fixture only (synthetic prices), or inspect an existing SEALED DB read-only;
do not run a new historical search. Verify all production unit/config hashes,
checkout commit/status and production timer enabled before/after. Prepare exact
release manifest, units, filesystem permissions, disk forecast and rollback plan.
STOP before installing real systemd worker units, creating the service account,
enabling its timer or queuing a new research study. User requirement 20 requires
review of the concrete result before those installation actions.
