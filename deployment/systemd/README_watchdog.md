# Dependency-scoped maintenance watchdog

The existing mrv1-watchdog.service is diagnostic maintenance, not a production
orchestrator. Its timer runs at 01:25, 07:25, 13:25 and 19:25 UTC, with up to five
minutes jitter. User/group trendatlas; Nice10, CPUQuota50%, MemoryMax1G; strict
filesystem sandbox permits writes only in outputs/execution/watchdog.

The only repair ID is refresh_dependency_health_cache. It rebuilds the watchdog's
own sanitized cache when missing/stale/invalid or inconsistent with observations.
It cannot refresh market data, change dates, build a strategy, publish authority,
start/stop production, access trading credentials or send an order. Existing
production freshness/provenance checks still block the dependent trade transition.
Reports carry system_available=true, affected capabilities and blocked action IDs;
block_execution is a compatibility alias for new_trade_transition, never a command
to stop the application or scheduler. A cache repair does not resolve stale inputs.

AI configuration is configs/maintenance/watchdog_openai.json: gpt-5.4, low
reasoning, fail_closed=false, one bounded strict structured response without tools.
Only validated source/status/incident/action enums are sent; no account data,
logs, raw file contents or environment. Missing key/API/config gives a warning
and deterministic fallback. Healthy/NOT_TIME_YET never calls AI. Invalid AI
selection becomes none/needs_human=true and cannot broaden the allowlist.

The optional /etc/default/trendatlas-watchdog may contain OPENAI_API_KEY only.
Provision outside Git as root:root 0600. Do not copy another application's key
or print it. Missing file is supported by EnvironmentFile=-... and does not
prevent deployment. Never load trendatlas-multi-account or signer credentials.

Before deployment read source_of_truth/watchdog_maintenance_contract.md and the
Pi runtime workflow. Preserve production HEAD, dirty files, runtime data, journals
and all existing credentials. Check production inactive, record preimage SHA256,
back up only files being replaced, and deploy reviewed bytes atomically. Existing
watchdog override.conf must be inspected; harmless identity-only entries may stay.
Do not reset or pull the production checkout. Install/create only the watchdog
output directory as trendatlas:trendatlas 0700; do not recursively chown runtime.

Validation:

```sh
python -m unittest tests.test_dependency_scoped_watchdog tests.test_execution_chain_sync tests.test_authority_outage_recovery tests.test_pi_fast_daily_authority_refresh -q
python -m py_compile scripts/execution/mrv1_self_healing_watchdog.py scripts/production/data_health_common.py
sudo systemd-analyze verify /etc/systemd/system/mrv1-watchdog.service /etc/systemd/system/mrv1-watchdog.timer
sudo systemctl daemon-reload
sudo systemctl enable mrv1-watchdog.timer
sudo systemctl restart mrv1-watchdog.timer
```

Run a check-only probe with the same watchdog service sandbox (temporary transient
unit, ExecStart replaced with --check-only --json), then start only
mrv1-watchdog.service for the authorized --remediate-safe --ai-diagnose --json pass.
Never start production as a validation step. Inspect journal, report/actions,
CPU/memory, both timers and unchanged production controls. Missing API key is an
expected warning. No live API request is needed for tests; mocks exercise strict
schema and rejection behavior. No order API exists in the watchdog action path.

Rollback restores only the backed-up watchdog source/config/unit files and its
previous timer state; production timer, strategy, secrets and runtime remain intact.

OpenAI request shape follows the official
[Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5.4 model specification](https://developers.openai.com/api/docs/models/gpt-5.4).
