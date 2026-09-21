# Dependency-scoped maintenance watchdog — deployed and verified

Deployment source commit: `4c8fdbd5c54603c9c8f40bd9faaccfe7f2d10590`.
Feature branch: `codex/dependency-scoped-watchdog-20260921` (pushed).
Pi checkout HEAD remains `1bb2d0d64363d111d92e4257d0a7345b484b8532`; reviewed
source files were deployed as overlays, without Git reset, checkout, stash, pull
or a production-branch switch. The audit commit only records observed state.

Final preservation verification: **2026-09-21 20:26:35 CEST**. SSH through
trendatlas.local and sudo worked; no network reset or configuration removal.

## Result

- mrv1-watchdog.timer: enabled/active, four daily UTC times 01:25, 07:25, 13:25,
  19:25, RandomizedDelaySec=5min. Observed next trigger 21:27:12 CEST (19:27:12 UTC).
- mrv1-watchdog.service: static/inactive after successful pass, ExecMainStatus=0.
  User/group trendatlas; Nice10, CPUQuota50%, MemoryMax1G. Systemd verify passed.
- mrv1-production.timer: unchanged enabled/active; next 2026-09-22 02:10:00 CEST.
  Production service remained inactive/success throughout maintenance verification.
- Evolution dispatcher timer also remains enabled/active; no research was started.
- First timer activation at 20:22:54 CEST caught up a missed Persistent timer event
  and successfully refreshed the watchdog's own diagnostic cache. The subsequent
  check-only test did not write that cache; the explicitly requested safe/AI pass
  at 18:23:50 UTC correctly selected none because the cache was already current.
- Observed incident: DEPENDENCY_UNHEALTHY, incident_level=degraded. Only the BTC
  derivatives research panel and quality artifact were stale, last date 2026-04-19
  versus expected 2026-09-20. blocked_action_ids=[run_research_btc_derivatives].
  system_available=true, block_app=false, block_execution=false. All production,
  BTC OHLCV, active-strategy ETF inputs, intent, gate and authority sources were OK.
- Optional provider environment entries are unavailable in the isolated watchdog
  environment and warn only. They were not obtained from trading credentials.
- /etc/default/trendatlas-watchdog and its OPENAI_API_KEY are absent. AI is configured
  for gpt-5.4/low with fail_closed=false, but **no real API request occurred**.
  Deterministic maintenance continues; operator key provisioning remains pending.
- The stale research panel remains unresolved. Cache repair does not refresh data,
  rewrite its dates, clear its block, change criteria or declare it trustworthy.
- **No order was sent.** live_order_chain=NOT_INVOKED. No refresh, publish, production
  start/stop, strategy change or authority/account/journal write occurred.

## Isolation and measured load

Only outputs/execution/watchdog is writable in the strict systemd filesystem
sandbox. A separate read-only diagnostic probe using the installed hardening
confirmed trading secrets and the production entrypoint inaccessible, source_of_truth,
authority and research state non-writable, and watchdog output writable.
No probe exposed credential contents. The account was UID1000 and Nice10.

The real safe service used 0.335 seconds CPU. Systemd did not retain MemoryPeak
after its short oneshot. A same-sandbox read-only in-process check measured
34,384 KiB maximum RSS (~33.6 MiB), 0.304 seconds CPU and 0.383 seconds checking
time. Host load average was 0.07/0.18/0.17. Free disk: **2,149,085,184 bytes**,
approximately 2.00 GiB. No production lock, service restart or cgroup conflict
was introduced. The watchdog cannot start or stop production through its action API.

## Exact installed files and SHA256

| Path | SHA256 |
|---|---|
| /opt/market_regime_v1/scripts/execution/mrv1_self_healing_watchdog.py | 9dfe32b86490ff56ddc43b037f1930fd198d0268048156b2d1b5ac7da8dfa396 |
| /opt/market_regime_v1/scripts/production/data_health_common.py | f5d538b391d12ceb38e74094aabc45c9eecd987573328d19eda27471439d9912 |
| /opt/market_regime_v1/scripts/production/validate_data_health_report.py | a7b4cca10ae7c37218a3c9d434036954a3d3302d1c916b06ed24a2681ac36709 |
| /opt/market_regime_v1/configs/maintenance/watchdog_openai.json | acd489a5575a38657d6b5447049614834506a6d1d2b88a6d7f794c8f5edee3c2 |
| /etc/systemd/system/mrv1-watchdog.service | 043359c3a24ccbc3269e3b221777c6aa84599e061e5ae4f20f739f48e93480e6 |
| /etc/systemd/system/mrv1-watchdog.timer | 2dcefc2898ca89b8a1a7712bdac3f601211c892b0d7c48a7cb84417eaf0aa4d7 |

Existing services/shared/openai_responses.py was hash verified and left unchanged
(`3d12c98154d9ce5d5f2fc742808adb6fe2fbb15bdf1e467324ac1f1e5178e3ad`).
Existing harmless watchdog override.conf identity/public publish-path settings
were preserved; they cannot grant any action to the new static allowlist.
All replaced files retained their existing ownership/mode; new JSON config is
root:root 0644 and contains no secret. Systemd units remain root:root 0644.

Preimages and deployment manifest:
`/var/backups/trendatlas-watchdog/20260921-4c8fdbd5/` (root private directory).
Staging/test bundle: `/tmp/trendatlas-watchdog-4c8fdbd5/` (small source-only bundle).
No full repository or virtualenv copy was made.

## Preservation and expected output updates

544 existing runtime/dirty files were hashed before install. **541 retained their
hashes**; exactly the three authorized latest watchdog report/actions/summary
files changed as a result of the requested checks. These are expected report
updates, not preservation failures. All protected production, authority, account,
production-run and execution-journal file hashes **and file inventories** matched.
All 125 pre-existing git status entries remain. New entries are only the three
deployed scripts, maintenance config, watchdog cache directory and its OS lock.
No generated output or credential was committed to Git.

Unchanged production controls:

- service: d61d44e83e8ebd1703ac1904bdeb5357a54aa0f8cc1b36aec05bfdd148570624
- timer: 910fe5499e14af959b2de9ace5cd4195361eadcc919a86bcf83b03648495bb2f
- multi-account environment: 62f51063bedd9f774fc9955adef69ff0ebe4b3c9cf934201350fe29762cd7165

The environment was hash checked only, never printed or copied. Order/journal
inventory equality independently supports the no-order report. The Windows
original dirty checkout was not changed; work used trendatlas_recovery_20260920.

## Validation and known unrelated failure

- **55 targeted local unittests passed**: dependency-scoped watchdog, execution
  chain synchronization, authority outage recovery and fast daily wrapper tests.
- **19 watchdog tests passed on Pi** against the staged committed source before
  deployment. All API tests use mocks, including the real shared client's strict
  Responses payload construction; no test invoked the external API.
- Generated temporary data-health fixture passed the updated JSON validator.
- py_compile passed for watchdog, health common module/validator, shared client
  and new tests; six configuration/registry JSON parses passed; git diff --check
  passed. No full refresh or live order was needed for validation.
- systemd-analyze verify passed before activation and after deployment; calendar
  expansion confirmed all four UTC times. Safe check-only transient service,
  installed remediate-safe/ai-diagnose service and read-only isolation probe passed.
- Broader app/precedence testing: 75 of 76 passed. The account exact-schema test
  expects no `performance: {}` member while current baseline includes it. Repeating
  that specific test with the **unmodified HEAD health implementation** reproduced
  the identical failure. Account/strategy/frontend code was not changed to hide it.

Local ignored evidence files: tmp/watchdog-preflight.json,
watchdog-targeted-tests.log, watchdog-tests.log, watchdog-baseline-app-test.log,
watchdog-deploy-manifest.json, watchdog-install-result.json,
watchdog-pi-unit-tests.log, watchdog-pi-check-only.json,
watchdog-pi-final-evidence.json (includes journal), watchdog-pi-isolation.json,
watchdog-final-preservation.json. No credentials are stored in these records.

## Required repository audit

**FILES READ:** full AGENTS.md; mandatory source_of_truth README, master_state,
chat_roles, relevant project_truth/export_contract/paths_registry/current_issues;
canonical script/output registries and registry_workflow; full Pi runtime workflow;
existing watchdog/service/timer/README; shared OpenAI Responses client; data-health
common, build/validate entrypoints and consumers' guard call sites; relevant tests;
OpenAI Docs skill and official GPT-5.4/Structured Outputs documentation.

**SOURCE OF TRUTH:** user-authorized B/C maintenance scope. The new maintenance
contract and revised source dependency semantics were validated before runtime
implementation. Observed deployment fields were updated only after Pi verification.
Canonical trade provenance/freshness and production strategy truth remain authoritative.

**Exact root cause:** health summarization conflated production dependency failures
with global app blocking. The old hourly watchdog could invoke a legacy fast
authority refresh/publish path independently of the canonical orchestrator. It
lacked optional constrained AI diagnosis and the requested resource schedule.

**Exact contract impact:** source, summary and watchdog incidents now identify
affected capabilities and blocked actions with system availability independent.
Existing block_execution compatibility retains new-trade fail-closed checks;
block_app no longer disables application availability due to data failures.
AI selects only deterministic incident-eligible IDs from a strict schema and has
no command/code, strategy, secret, source-of-truth or order authority. The normalized
public export minimum field set remains compatible; scoped fields belong to the
data-health source/summary and maintenance report contract.

**Regression tests added/updated:** tests/test_dependency_scoped_watchdog.py has
19 cases covering all six required regressions plus fresh eligibility, missing API,
sanitization, strict client payload, no tools, endpoints, atomic publication and
no arbitrary/legacy command. Updated the old wrapper test to assert the watchdog
cannot invoke that competing refresh path.

**Forbidden old path checked:** old run_pi_fast_daily_authority_refresh,
run_pi_authoritative_producer, publish, live-order and full-refresh actions are
absent from the watchdog executable path. Only fixed read-only systemctl queries
remain; no service mutation command. Production controls/authority/account/journals
and unrelated research paths are unchanged and protected from watchdog writes.

**Exact implementation git add list (also exact changed files):**

```text
git add canonical/output_registry.json canonical/script_registry.json deployment/systemd/README_watchdog.md deployment/systemd/mrv1-watchdog.service deployment/systemd/mrv1-watchdog.timer scripts/execution/mrv1_self_healing_watchdog.py scripts/production/data_health_common.py scripts/production/validate_data_health_report.py source_of_truth/current_issues.md source_of_truth/export_contract.json source_of_truth/master_state.md source_of_truth/paths_registry.json source_of_truth/pi_codex_runtime_workflow.md source_of_truth/project_truth.json source_of_truth/watchdog_maintenance_contract.md configs/maintenance/watchdog_openai.json tests/test_dependency_scoped_watchdog.py tests/test_pi_fast_daily_authority_refresh.py
```

Implementation message: `Scope watchdog health incidents and constrain optional AI maintenance`.
Implementation hash: `4c8fdbd5c54603c9c8f40bd9faaccfe7f2d10590`.

**Exact deployment audit git add list:**

```text
git add source_of_truth/project_truth.json source_of_truth/export_contract.json source_of_truth/current_issues.md source_of_truth/master_state.md docs/watchdog-deployment-audit-20260921.md
```

Audit commit message: `Record deployed watchdog isolation and dependency-scoped health audit`.
Audit commit hash: reported in the completion response (the containing commit).
It does not change installed runtime bytes or the Pi checkout HEAD.
