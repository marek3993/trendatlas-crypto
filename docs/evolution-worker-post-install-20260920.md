# Evolution Worker post-install audit — installed, empty queue, IDLE

User explicitly approved permanent installation of pinned source commit
`2a2319cd4bd2a2655e3b999ffa75802bf2136020` according to
`docs/evolution-worker-installation-review-20260920.md`. Approval covers only the
dedicated account, release, empty state/queue and three reviewed units, enabling
only the dispatcher timer. It does not authorize a historical study or trading.

Installation and final preservation checks completed on trendatlas.local on
2026-09-20, final preservation observation **18:19:16 CEST**. Every installation
prerequisite matched the review before mutation, including the exact free-space
value. A transient DNS lookup failure resolved on retry before SSH inspection.

## Ten requested checks

1. **Pinned release and SHA256 verified.** Installed at
   `/opt/trendatlas-research/releases/2a2319cd4bd2a2655e3b999ffa75802bf2136020/`.
   All 20 manifest-listed files, manifest identity and exact file set verified;
   no symlinks or unlisted files in release. Each installed unit matches the
   corresponding manifest hash. No clone, virtualenv or moving symlink.
   Release SHA256:
   `685659d6e069f96fade59096ea42e381bf0f1ba1418396550cdeb51a55445651`.
   Archive SHA256:
   `cf18d30d9812aaef13a99ca4405377c6f93e6af2dcd6b0bee5f844cb9bef8e1d`.
2. **Owners and permissions verified recursively.** Account
   `trendatlas-research`, UID 999, sole group GID 984, locked password,
   `/nonexistent` home and `/usr/sbin/nologin` shell. Release and parents
   root:root 0755 directories / 0444 files; input directory root:root 0755,
   empty CSV mount placeholder root:root 0444. State root research:research
   0750; queue root:research 0750; worker.lock research:research 0640 and empty.
   Three unit files root:root 0644. The enabled timer symlink is root:root,
   points to its reviewed unit and has normal symlink mode 0777.
3. **systemd-analyze verify passed**, exit 0, no warnings, both before activation
   and in post-install verification of all three installed units.
4. **trendatlas-evolution-dispatch.timer enabled / active (waiting).** First
   automatic trigger at 18:16:54 CEST. Both research services are static; only
   this research timer was enabled.
5. **Worker inactive/dead.** Loaded manager properties `RefuseManualStart=yes`,
   `CanStart=no`; `ExecMainPID=0`, empty `ExecMainStartTimestamp`. In compliance
   with the user instruction, no manual start request was sent to the real worker.
   Functional refusal was tested previously on the reviewed isolated dummy unit;
   installation verifies the real manager's refusal properties without starting it.
6. **Empty queue is IDLE.** Both actual services exited their read-only
   `bootstrap.py ready` ExecCondition with status 1. Systemd reports
   `Result=exec-condition`, not a research failure. This systemd version still
   triggers OnSuccess after the dispatch condition is skipped, so the worker's
   independent ready condition also runs and safely skips its ExecStart.
   No generation/backtest, queue ledger, jobs directory or study was created.
   A separate read-only probe confirmed `runtime.pending(state) == False` and
   printed `IDLE`. State contains only empty queue/ and empty worker.lock.
7. **mrv1-production.timer remained enabled / active.** Next event remains
   2026-09-21 02:10:00 CEST. Production service remains inactive/dead, success,
   unchanged inactivity timestamp 2026-09-20 09:12:12 CEST. No production service
   start, stop, restart, reload or timer operation was requested.
8. **Production commit and control hashes unchanged**, detailed below. Existing
   125 dirty entries preserved and no config/configs/scripts diff appeared.
9. **Research process isolation verified.** A temporary read-only diagnostic
   service, using UID 999/GID 984 and the installed worker's relevant hardening,
   mount, environment and resource directives, could not read the production
   checkout, its .git/HEAD, `/etc/default/trendatlas-multi-account`, credential
   stores, `/run/credentials` or `/opt/home_automation`. The diagnostic ran no
   worker engine, fixture or historical study and was automatically collected.
   BTC alias mount is read-only, SHA256 matches the unchanged production input;
   AF_INET socket creation denied, Nice 19, environment names only HOME/LANG/PATH.
   D-Bus confirms zero EnvironmentFiles, LoadCredential and
   LoadCredentialEncrypted entries on the installed worker.
   **Scope:** checkout invisibility is enforced by the service mount namespace;
   it is not a host-wide ACL restriction on an unsandboxed UID. The account has
   no login, and production directory permissions were deliberately preserved.
10. **Disk reserve sufficient:** 2,020,892,672 bytes available (~1.88 GiB), above
    the 1 GiB + 64 MiB guard. Before: 2,021,085,184 bytes. Observed filesystem
    consumption delta 192,512 bytes; release allocation 159,744 bytes, state
    allocation 8,192 bytes. No historical results were copied into installed state.

## Production preservation

Before/after HEAD: `1bb2d0d64363d111d92e4257d0a7345b484b8532`.
Before/after status-porcelain SHA256:
`656adf7c7372ff9721a977e75b56fbf10adc6e583240bc8b01bbad09934e5167`.

| Unchanged control file | SHA256 before and after |
|---|---|
| /etc/systemd/system/mrv1-production.service | d61d44e83e8ebd1703ac1904bdeb5357a54aa0f8cc1b36aec05bfdd148570624 |
| /etc/systemd/system/mrv1-production.timer | 910fe5499e14af959b2de9ace5cd4195361eadcc919a86bcf83b03648495bb2f |
| /etc/default/trendatlas-multi-account | 62f51063bedd9f774fc9955adef69ff0ebe4b3c9cf934201350fe29762cd7165 |
| /opt/market_regime_v1/data/ohlcv/BTCUSDT_1d.csv | ee0306daad88fd63c03ed0fbb3afd6c79557b4911319bf259795a0624f31d998 |

Secret file was hash checked only; values were never printed or copied. All eight
before/after preservation records (HEAD, status hash/count, config diff, control
hashes, service state, timer state, CSV hash/metadata) matched exactly. No new
research, AI API, IML, order call, strategy, authority publication, historical
SEALED modification or production checkout operation occurred.

## Installation operations and boundaries

Executed the review's sequence: preflight assertions; archive and every contained
file verified in memory; useradd system account; install new release/input/state
directories and lock; extract approved archive; enforce ownership/modes; install
three pinned unit files; systemd-analyze verify; systemctl daemon-reload;
`systemctl enable --now trendatlas-evolution-dispatch.timer`.

The sole persistent unit link added is
`/etc/systemd/system/timers.target.wants/trendatlas-evolution-dispatch.timer`.
Account creation necessarily updates the OS account databases. No production
unit, drop-in, environment file, permission or configuration was changed.
The only extra service was transient `ta-evo-postinstall-readonly-probe.service`,
collected after successful diagnostics (`LoadState=not-found` afterward).
The real worker was never manually started. Production priority directives and
all CPU/memory/IO/disk limits remain byte-for-byte the reviewed release.

Local evidence, kept outside Git under ignored tmp/:

- evolution-worker-install-preflight.json
- install_approved_worker.py and verify_installed_worker.py (no credentials)
- evolution-worker-install-state.json (unit state and first timer journal)
- evolution-worker-postinstall-verification.json (all path modes, hashes, probe)
- evolution-worker-postinstall-preservation.json

The initial local transcript writer hit a Windows encoding error after SSH
execution completed. The installation was not repeated; subsequent independent
unit, file and journal reads confirmed completion and are the retained evidence.

## Required repository audit

**FILES READ:** AGENTS.md; source_of_truth/README.md, master_state.md,
chat_roles.md, relevant project_truth.json/export_contract.json/paths_registry.json,
current_issues.md; canonical/script_registry.json, output_registry.json,
registry_workflow.md; source_of_truth/pi_codex_runtime_workflow.md; reviewed
installation document; worker CONTRACT.md, bootstrap.py, runtime.py ready/release
validation; pinned manifest and all three rendered units. Prior engine and
Research OS audits are referenced by the installation review and were not rerun.

**SOURCE OF TRUTH:** latest explicit user approval of the exact pinned release
supersedes the review's installation stop. Classes B/C, infrastructure installation
only. Existing production authority, runtime and export contracts are unchanged.
Research-branch SSOT records the installed/idle status; Pi production SSOT remains
untouched. This audit is not a strategy qualification or production PASS.

**Exact root cause:** no new defect patched. The previously reviewed worker lacked
permanent installation approval; the user supplied that approval and the approved
installation is now applied.

**Exact contract impact:** activated only the reviewed finite queue host with an
empty operator queue. Research criteria, seed, domains, budget, frozen engine,
source release bytes and production authority are unchanged.

**Exact files changed:** Pi additions are the 20 manifest-listed release files
plus manifest.json, input placeholder, state/queue directories, empty worker.lock,
three units and one timer symlink; OS account records added by useradd. Research
repository changes are exactly the four files in the git add command below.

**Regression test added/updated:** none; no executable code changed. The reviewed
60 tests and dummy priority/manual-refusal tests remain the pre-install evidence.
New verification consisted solely of manifest/mode assertions, systemd verification,
automatic empty-queue condition checks, read-only sandbox assertions and exact
before/after production comparisons. No new synthetic or historical search ran.

**Forbidden old path checked:** production checkout/data/outputs/authority,
/opt/home_automation, production service/timer/secrets and old SEALED studies were
not written. No fetch/pull/reset/stash/checkout or producer/submitter was invoked.

**Validation commands/results:** `systemd-analyze verify` on three installed unit
paths: exit 0; `systemctl show`, `list-unit-files`, `list-jobs`: expected idle/static
services, enabled/active timers, no pending jobs; read-only manifest and recursive
stat assertions: pass; transient sandbox probe: exit 0, IDLE and all isolation
assertions pass; `git rev-parse HEAD`, `status --porcelain`, `diff --name-only --
config configs scripts`, SHA256 and production state comparisons: unchanged.
JSON metadata parse and `git diff --check` validated before the audit commit.

**Exact git add list:**

```text
git add source_of_truth/project_truth.json canonical/script_registry.json canonical/output_registry.json docs/evolution-worker-post-install-20260920.md
```

**Commit message:** `Record approved Pi worker installation and idle verification`.

**Commit hash:** the containing audit commit is reported in the completion response;
it changes only research-branch metadata/documentation, not the installed release
pin or Pi production commit.
