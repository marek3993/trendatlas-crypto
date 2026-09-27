# FILES READ / SOURCE OF TRUTH

## Required main read order

- AGENTS.md (user-provided and repository)
- source_of_truth/README.md
- source_of_truth/master_state.md
- source_of_truth/chat_roles.md
- source_of_truth/project_truth.json
- source_of_truth/export_contract.json
- source_of_truth/paths_registry.json
- source_of_truth/current_issues.md
- canonical/script_registry.json
- canonical/output_registry.json
- canonical/registry_workflow.md
- source_of_truth/pi_codex_runtime_workflow.md

## Research and infrastructure sources

- User attachment: Vlozeny text.txt, attachment671f1f52-f2f0-41e7-b486-13c53675dc29.
- c1e4574250c08c2027dea30070ec7705d8fde906: research/slow_trend_20260927/{contract.json,AUDIT.md,common.py,data.py,signals.py,ledger.py,test_research.py}; named-G gene definitions only, not saved performance as input.
- 58e308315d03a4561d53bbbd4019f7392f66e662: research/capacity_followup_20260927/{contract.json,data_prepare.py,data_finalize.py,designer.py}; exact raw input bundles and identity/notices metadata.
- e655035c3e3651468eb47ed078a6746ec0602860: docs/continuous-evolution-deployment-audit-20260922.md; research_os/dev_only/evolution_worker/{CONTINUOUS_CONTRACT.md,runtime.py,walk_forward.py,bootstrap.py,gate.py}; systemd templates and resource guard.
- Pi installed research release826e42d9f31d92d290c5c152566cc917cda5be20: guards/memory_guard.py; research dispatcher/worker/timer and their two drop-ins; cgroup controllers, resource metadata and production unit state (read-only).
- This package's contracts, preregistration, source_lineage.json and each newly implemented module/test.
- Pi actual frozen research status, service properties, private/host network namespace identifiers and process memory metadata; production HEAD and production/research-dispatch unit SHA256 before/after installation.
- Read-only SQLite backup exports of the live candidate/result and development-mailbox databases; all first three actual DeepSeek request/response/validation records.
- Verified synthetic status, manifest, tables, audit, lineage and equity; real-data smoke audit; research-only resource, filesystem-boundary and fake-authority probe results.

## SOURCE OF TRUTH

Production authority stays in the existing source_of_truth contracts and Pi runtime. This research has no authority over it. Research methodology is `evolution_contract.json` + `anti_overfitting_contract.json`; per-experiment immutable manifest is the byte-level code/raw-input identity; SQLite is the attempt/result/checkpoint authority. `source_lineage.json` pins copied source/raw blobs. Readable reports derive from those stores, never the reverse.

Exact root cause addressed: old continuous infrastructure used a weighted fitness and could launch a different family after rejection over the same history. That would continue selection pressure against already inspected data. Legacy strategy/PnL routes were also unsuitable as research truth. The new path restricts chronological information and budgets, freezes all nominees before outer, and requires new observations and refit admission for successors.

Exact contract impact: new research-only B/C/D contracts; no production source-of-truth, execution planner, account, dashboard, wallet, reconciliation, strategy setting or production timer contract is changed. Only research services and their private runtime are replaced after validation.
