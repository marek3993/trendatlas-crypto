# Continuous Evolution Pi deployment and AVAX dashboard audit — 2026-09-22

## Authority and root cause

The Pi production checkout remains `/opt/market_regime_v1` at
`1bb2d0d64363d111d92e4257d0a7345b484b8532`. The authorized production
timer is `mrv1-production.timer`; its next run at audit time was 2026-09-23
02:10 CEST (00:10 UTC). The latest successful daily run evaluated the closed
2026-09-21 data. The real account held CASH / 0.00x, with no position or order.

AVAX / 1.00x was **model preference**, not a tradable instruction. Production
reported `trend_permission_active=false`, current authorized target CASH / 0,
`candidate_entry_not_authorized`, decision reason `candidate_asset_not_btc`,
gate `no_action` with `no_market_entry_authorized`, `allow_live_order_candidate=false`,
`order_requested=false`, and `real_order_sent=false`. Production data freshness,
execution policy, and the live kill switch did not block the system; the stale
BTC-derivatives warning belongs only to its research capability. The 2026-09-27
rebalance is a decision date, and the first scheduled processing after it is
2026-09-28 00:10 UTC, conditional on an authorized signal and normal safety gates.
No trade or strategy logic was changed. The tablet kiosk had mapped CASH/no-action
to the generic label `Blokované`; the reviewed anchored patch now displays
`Čaká na signál`, the unconfirmed candidate, reason for waiting, next daily
check, first post-rebalance check, and whether a safety gate actually blocks.
The observed kiosk payload after restart was real CASH / 0.0, candidate AVAX /
1.0, no safety block, next daily check 2026-09-23 00:10 UTC, and earliest
post-rebalance check 2026-09-28 00:10 UTC. Model exposure is never shown as
real account exposure.

The old research dispatcher ended a whole bounded campaign when its ten
preregistered studies became SEALED. It had no immutable successor ledger or
reasoned selection among distinct families. The new contract was preregistered
before implementation or any new historical computation, then deployed as a
separate pinned release. `SEALED` ends one cycle only. Five predeclared
trend/momentum, low-turnover, mean-reversion-entry, protected-trend and regime
ensemble hypotheses are chosen from rejection reasons and unused fingerprints.
The system will not repeat an exhausted same-data search. All historical periods
are development/retrospective; no historical result is a production PASS.

## Change and pinned release

Source commits, in order:

1. `72950b34070f8e557ffd26ef8bf9463f8d694a89` — preregister continuous
   contract, frozen policy and source/output registries.
2. `f9144dd2463761576f18c9737e2f30c8e4066d72` — normalize public wait
   fields and patch Streamlit/tablet wording with regressions.
3. `31d98327fc73c3e724886636cef4e7bc82d2fabf` — freeze checkpointed
   active-compute budget and conservative in-flight reservation before search.
4. `826e42d9f31d92d290c5c152566cc917cda5be20` — continuous controller,
   next-open family backtests, SQLite resume, systemd units/guard and tests.

The installed small release is
`/opt/trendatlas-research/releases/826e42d9f31d92d290c5c152566cc917cda5be20`.
Its canonical release SHA256 is
`78fb441a486d6a3e398e728f0c843d5f77acca9130e313b48e876631213c00cf`;
archive SHA256 is
`dd1f3fd0158e41e936e886321ca7d995ae1afe0cb0694ac022467730b4914a34`.
There are 36 allowlisted files plus `manifest.json`, 214,129 unpacked bytes and
a 58,246-byte archive. All release files are root:root 0444, directories
root:root 0755. The root-owned continuous authorization directory is
root:trendatlas-research 01770 (sticky), its pinned `authorization.json` is
root:trendatlas-research 0440. The BTC source was bound read-only from the
production checkout and frozen with SHA256
`4d71367947e5789ca807e42d98541a079bd5a0c04054ec58a6781e8cc6a77712`.
The old release, resource guard, ten v3 SEALED jobs and their SQLite databases
were not rewritten.

Only three research systemd units and two research-only drop-ins were replaced.
The original unit files are backed up under
`/var/backups/trendatlas-research/continuous-826e42d9f31d-20260922T203253Z`.
`systemd-analyze verify` passed before and after cutover. The dispatcher timer is
enabled/active with `OnUnitInactiveSec=15min` and a 30-second randomized delay;
its observed next tick after completion was 2026-09-22 22:48:14 CEST. The
worker has `RefuseManualStart=yes`, production `Conflicts`/`After`, CPUQuota=20%,
Nice=19, idle IO, LimitAS/MemoryMax=384M, and MemorySwapMax=0. The Pi exposes
only `cpuset cpu io pids` cgroup controllers: the memory cgroup values cannot
be claimed as enforced. The actual compute interpreter's transient and live
startup probes observed RLIMIT_AS and RLIMIT_MEMLOCK of 402,653,184 bytes,
`mlockall(CURRENT|FUTURE)`, about 22,384 KiB locked and 0 KiB swap. Thermal
hysteresis, disk guard, per-cycle 64 MiB cap, SQLite checkpoints and production
preemption remain part of the pinned policy. No IML or OpenAI API is involved.

## Validation and observed autonomous succession

Locally, 120 relevant unittests passed in 153.021 seconds. JSON validation,
`py_compile`, `node --check`, and `git diff --check` passed. The new 19 focused
tests cover close-D/next-open execution, lookahead, costs, exposure/turnover,
five generations of 10→6+4, one-gene neighboring mutations, cash/BTC and
chronological folds, input rewriting, source-day closure, SEALED integrity,
duplicate-fingerprint prevention, durable ERROR latch, active-time reservation,
crash windows, resume and automatic family succession.
After the observed deployment state was written into source-of-truth and
canonical registries, 21 focused truth/registry tests passed. Two legacy
`test_output_registry_allowed_values` assertions still fail because their
hard-coded layer and decision-relevance sets exclude many values already present
in the 72-entry registry before this change; the set of such values is identical
in the parent commit and this update. No registry semantics were widened to
silence those pre-existing failures.

On Pi, `systemd-analyze verify` passed. Two tiny **synthetic** cycles ran as the
research user in a separate fixture root: a first process committed one period,
a fresh process resumed it, SEALED trend/momentum, automatically created and
evaluated mean-reversion-entry with a different fingerprint, then SEALED it.
Both fixture cycles sent no order. A separate user-manager dummy systemd test
passed manual-start refusal, production preemption, re-dispatch while stopping,
12 admission races without overlap, and left real production untouched. An
isolated transient process could read only the bound BTC input; it could not
read the production checkout, tablet checkout or multi-account secret, and
AF_INET socket creation was denied. The live worker journal also reported
zero swap and the pinned memory guard at startup.

After dispatcher activation, **without manually starting the worker or
enqueuing a job**, the Pi completed these real retrospective cycles on the same
frozen input:

| Automatic order | Family/template | Generations | SEALED outcome | Main rejection |
| --- | --- | ---: | --- | --- |
| 1 | trend_momentum / trend_momentum_base_v1 | 5 | HISTORICAL_REJECT | Cash gate in all selection folds and assessment |
| 2 | regime_ensemble / regime_ensemble_v1 | 1 | HISTORICAL_REJECT | Fewer than six eligible survivors; early-stop rule |
| 3 | trend_low_turnover / trend_momentum_low_turnover_v1 | 5 | HISTORICAL_REJECT | Cash gate in several folds and assessment |
| 4 | mean_reversion_entry / mean_reversion_entry_v1 | 5 | HISTORICAL_REJECT | Cash gate in several folds and assessment |
| 5 | trend_momentum_protected / trend_momentum_pullback_protected_v1 | 5 | HISTORICAL_REJECT | No entries in some folds/assessment and cash gate |

All five have distinct SHA256 fingerprints. Every new `SEALED.json` was checked
against the hashes of its listed files. The regime ensemble legitimately stopped
at generation one because its frozen six-survivor eligibility rule failed; no
generations or domains were widened. The final status is `WAITING_FOR_NEW_DATA`,
worker inactive/success, `last_reject_reason=no_entries`, `orders_sent=false`,
`production_promotion=false`, and `ai_api_used=false`. The dispatcher remains
active and will admit another cycle only after at least 30 *append-only, closed
UTC* BTC bars are available. It will not replay these five rejected fingerprints
on the unchanged history.

## Preservation, no-order evidence and next 24 hours

Preflight, immediately after research installation, after the kiosk patch, and
after all five real cycles compared the Pi against the same protected baseline:
production HEAD and exact dirty status (131 entries), all 575 protected
production/account/authority/intent/gate/run/journal file paths and SHA256
values, 93 old immutable research files, BTC source, and production/watchdog
unit hashes were unchanged. `mrv1-production.timer` and `mrv1-watchdog.timer`
remain enabled/active, production service inactive/success. No production
checkout commit, secret, systemd trading unit, strategy or runtime data was
altered. Research has no exchange/order imports, credentials or network path;
the unchanged execution journal and real account, isolation probe and five
SEALED audit records support `orders_sent=false`. No manual or research order
was sent and no research candidate was promoted.

The kiosk changed only `/opt/home_automation/home_dashboard.py` and
`/opt/home_automation/static/app.js` via reviewed anchors, after exact original
SHA checks; original copies were retained locally on Pi. New SHA256 values are
`6b7d46b91d83b05f2de89273130a388eb43324ec6d89eb96e5ec4c7ea37522a9`
and `b1a1dfef01bfda150e4a0dafd36a0bba668cc8f6006316f27a76858fd1827dda`.
`home-blinds-dashboard.service` restarted active. The dashboard's observed
payload reports real CASH / 0.00x, model AVAX / 1.00x, `Čaká na signál`, and
no blocking safety gate. No internal implementation labels were added to its
visible explanatory text.

At final inspection the Pi had 1,942,982,656 free bytes (94% of its root
filesystem used), worker RAM last observed about 42.6 MiB, temperature about
48–50 °C and no active worker CPU use after exhaustion. In the next 24 hours,
the research dispatcher will continue its approximately 15-minute checks and
remain idle on the unchanged input. The ordinary production timer will evaluate
the next closed day at 2026-09-23 00:10 UTC; any order remains subject to the
existing production signal and safety gates. The maintenance watchdog follows
its existing four daily UTC runs. Research will not submit an order, edit an
authority snapshot, or install a historical strategy. A fresh 30-day closed,
append-only input is needed before this exact pinned research policy can begin
another distinct cycle.
