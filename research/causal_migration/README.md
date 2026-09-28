# Same-experiment recovery and VPS migration

Class C (execution/orchestration), with class B checkpoint admission. This package
is outside the frozen scientific engine. See [REPORT.md](REPORT.md) for the
2026-09-28 execution evidence and [contract.json](contract.json) for admission rules.
This is research operational evidence, not production authority or account PnL.

## Runtime contract

The engine remains commit `53b6a5336ca1f7ce35b481a017f7e82396f3613c`; the
existing `causal_resume/runtime.py` provides its unchanged manifest verifier,
state transition primitives and reservation reconciliation. No engine patch or
new experiment initialization is performed by this package.

`ExecStop` binds an administrative request to the activation token and current
systemd MAINPID before SIGTERM. `KillMode=mixed` leaves the worker's helper alive
during cooperative shutdown. The exact legacy systemctl-helper SIGTERM is also
handled when it belongs to an authorized stop. An unbound signal remains FAILED.

A checkpoint requires integrity and foreign-key checks on both databases, a
bijection between completed reservations and evaluations, and the last atomic
checkpoint matching the last completed attempt. At most one unfinished
reservation may become INTERRUPTED; its consumed attempt budget remains. A hard
timeout is reconciled only by ExecStopPost after the worker exits and releases
its lock. A valid durable checkpoint is resumable while systemd retains its
timeout result. An invalid checkpoint is FAILED. Failures are never generically
cleared; the one-time recovery matches the exact authorized failure, original
counts, manifest and complete pre-recovery table hashes.

## Installed layout

- Frozen release: `/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c`.
- Orchestration: `/opt/trendatlas-research/orchestration/causal-migration-20260928/research/causal_migration`.
- Venv: `/opt/trendatlas-research/venvs/causal-v1`.
- Existing state: `/var/lib/trendatlas-research/causal-v1/current`, pointing to
  `cycles/causal_nested_v1_20260927`.
- Backups: `/var/backups/trendatlas-research`; exports: `/srv/trendatlas-research-export/latest`.
- Root-only research API source: `/etc/credstore/trendatlas-research-deepseek`;
  only the separate broker receives it through systemd LoadCredential.

`deploy.py vps --output <staging-directory>` renders the seven research units.
Review/install those files only, followed by `systemd-analyze verify` and
`systemctl daemon-reload`. The worker uses the isolated Python 3.13.5 environment
with numpy 2.4.4, pandas 3.0.3, python-dateutil 2.9.0.post0 and six 1.17.0.
Python was installed with pinned uv 0.8.22 into the research root, following
[uv's Python installation guide](https://docs.astral.sh/uv/guides/install-python/)
and [installation directory configuration](https://docs.astral.sh/uv/configuration/environment/).
Do not copy the Pi venv or install packages in LeadPilot's environment.

One worker is supported. The frozen `WorkerLock` is an exclusive flock, not a
multi-worker lease protocol. Worker network access is denied; the broker sees
only the proposal mailbox, not input data or results. Its frozen API client
validates development-only JSON payloads and the fixed endpoint. Neither user
belongs to docker or sudo. The worker's CPU/memory limits and the broker's smaller
limits are in `deploy.py`.

The worker is enabled at boot; the dispatch timer resumes successful checkpoints.
Unexpected worker failures remain terminal in the DB and fail admission rather
than silently restarting scientific work. The backup timer runs at 03:30 UTC.
Backup maintenance stops only research timers, requests the normal worker stop,
waits for the broker to finish, locks both writers, and uses SQLite's backup API.
It verifies SHA256/integrity before producing a root-owned 0440/0550 export and
restores only previously active timers. Retention keeps seven daily and four
weekly representatives, always including the newest valid snapshot. No production
publication exists. `backup-health.json` records disk usage and a warning above
75%; research `.log` files have dedicated daily/10M logrotate with seven copies.

## Reproducible checks

Run synthetic tests against an extracted frozen engine, never a fresh real experiment:

```text
python research/causal_migration/test_runtime.py --engine <frozen-engine-root> -v
python research/causal_migration/test_replay.py -v
python research/causal_migration/test_maintenance.py -v
python research/causal_resume/test_resume.py --engine <frozen-engine-root> -v
```

From the frozen engine root:

```text
python -m unittest research.causal_evolution.tests research.causal_evolution.vendor.test_research
```

`systemd_probe.py` exercises administrative stop, unexpected SIGTERM and a real
hard timeout with synthetic state in `/run`; it removes only its own transient
probe units. `replay.py choose` selects an already evaluated seed candidate.
`replay.py run` reads fixed development inputs without opening the experiment DB;
`compare` requires exact signal decisions and the predeclared frozen prefix-audit
numeric tolerance. It reports exact equality separately.

Do not run `recover` routinely. It accepts only the report's original 5,085-result
failure with a matching verified snapshot; a second call is idempotent. Normal
resume is `runtime.py run --platform vps`, under the installed systemd service.

## Rollback procedure

Never start Pi research while a VPS worker or broker can write. First stop and
disable the VPS research dispatch/broker/backup timers and worker, verify MainPID=0,
and retain the latest verified VPS backup for diagnosis. The unchanged Pi state
at 5,087 and the original 5,085 forensic archive are retained; do not overwrite
either with an active WAL database. Returning to 5,087 intentionally abandons
later VPS progress and therefore needs an explicit choice of recovery checkpoint.

On Pi retain this repaired orchestration, its production gate and existing systemd
resource limits. Replace only the validation ExecStart override with
`runtime.py run --platform pi` (normal bounded activation; no validation count
limit), then daemon-reload and enable its three research timers. Start through
the research dispatcher, verify a new evaluation and a successful checkpoint.
Do not change any `mrv1-*` production service, timer, watchdog or dashboard.
