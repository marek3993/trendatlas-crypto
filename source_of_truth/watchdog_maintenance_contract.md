# Dependency-scoped maintenance watchdog contract

Classes B/C. User authorized implementation and deployment on 2026-09-21.
Deployment status is recorded separately only after observed installation.

Data-health source failures carry incident_level, affected_capability_ids,
blocked_action_ids and system_available=true. Availability means the system can
continue serving unaffected functions; it never asserts failed data is trustworthy.
Production/execution dependency failures block only new_trade_transition. This
retains the existing order gate's fail-closed source/provenance/freshness checks.
block_execution remains a compatibility alias for that transition, not an
instruction to stop services. block_app is false; dashboard/account display,
scheduler, independent research and unrelated actions continue. A research source
degrades only its registered capability. Unknown incidents require a human and
remain scoped to maintenance diagnostics; they never disable the whole system.
Dynamic ETF dependencies remain production-critical when required by the active
strategy. No date, snapshot or failed source is repaired by relabeling it healthy.

The single existing scripts/execution/mrv1_self_healing_watchdog.py observes
mrv1-production.service/timer and evaluates dependency health read-only. It must
not invoke the legacy daily service, fast/full refresh, producer, publisher,
execution planner, submitter, exchange client or systemctl start/stop/restart.
The explicit action allowlist contains only refresh_dependency_health_cache,
eligible when the watchdog's own cache is missing, invalid, stale or inconsistent
with observed scoped health. It refreshes diagnostics under outputs/execution/
watchdog/data_health only; canonical production health, authority, account, strategy
and journal files are never written by maintenance. Revalidate eligibility before
dispatch. If production is active, starting, stopping, pending or state is unknown,
skip repair; check-only reporting and all production scheduling remain independent.

AI is optional, uses services/shared/openai_responses.py with a strict Responses
JSON schema and no tools. Payload is constructed from validated source IDs, status
enums, incident/capability/action IDs and booleans only. Never send raw logs, file
contents, environment, account identifiers, free-text exception messages or secrets.
The model may select only none or an action already deterministically eligible for
that incident. An invalid selection/schema/refusal becomes none and needs_human=true.
API/key/config failure is a warning and never blocks deterministic maintenance or
the rest of TrendAtlas. Healthy and NOT_TIME_YET observations never call the API.
An AI choice never changes health severity, trade permission or dependency scope.

Config: configs/maintenance/watchdog_openai.json, model gpt-5.4, reasoning low,
fail_closed=false. Pin the official Responses endpoint; no configurable arbitrary
endpoint/key environment. Key only OPENAI_API_KEY loaded from optional
/etc/default/trendatlas-watchdog (root:root 0600 when supplied). Never create a fake
key, print values, store credentials in Git or load multi-account credentials.
At most one bounded API request per watchdog pass; missing key still logs warning.

Systemd: user/group trendatlas; --remediate-safe --ai-diagnose --json; four daily
UTC times 01:25, 07:25, 13:25, 19:25; randomized delay 5min; Nice10, CPUQuota50%,
MemoryMax1G. ProtectSystem=strict, only watchdog output directory writable,
NoNewPrivileges, no capabilities, inaccessible trading credentials, production
submitter/refresh script paths and private home/tmp. No production dependency that
starts/stops production. mrv1-production.timer stays the only trading scheduler.

Reports are atomically written under the watchdog output directory and protected
by an OS lock (no stale PID-file deletion). Unknown/corrupt metadata produces a
sanitized scoped incident. check-only never performs a repair or calls AI.
Run local regressions, schema/compile checks, Pi check-only and safe-remediation
verification before marking deployed. Existing runtime data, changes, journals,
production timer/configuration and credentials are preserved. Deploy only reviewed
source/config/unit files, with preimage hashes and backup; never reset/pull across
runtime changes. No live order is authorized by this task.
