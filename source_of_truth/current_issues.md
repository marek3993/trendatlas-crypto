# Current Issues

## Accepted current state
- research/raw winner = phase68i_66g_1p50x_static
- best deployment candidate = phase68i_dynamic_ladder_candidate
- official softer fallback = phase68g_66g_1p25x_candidate
- Phase68J simple tail-risk guardrails = rejected
- ordering remains unchanged
- leverage branch live truth has been promoted to phase68i_dynamic_ladder_candidate
- direct app/live truth switch is approved and applied
- current live truth is phase68i_dynamic_ladder_candidate
- approval_gate_status = approved_and_applied
- real_order_gate_status = live_order_enabled_and_approved
- only live_order_enabled_and_approved counts as real-order eligible

## Resolved blockers / completed accepted progress
- DATA plumbing / execution-contract / source-mapping blocker is closed
- APP final export-contract preparation for dynamic ladder is complete
- AUTOMATION local-PC controlled runtime loop discipline is operational
- validated safe posture:
  - mode = read_only
  - trading_enabled = false
  - dry_run_enabled = true
  - kill_switch = true
- default runtime behavior is one_pass
- continuous runtime loop requires explicit request
- source_of_truth writes are not part of runtime loops
- AI LAB schema_contract_expansion maintenance step is complete
- AI LAB phase69 remains paused pending future objective reframing
- AI LAB strategy advancement remains paused
- AI LAB dev-only execution mode is approved
- AI LAB dev-only runner/spec maintenance is allowed
- AI LAB widened dev-only implementation is approved for:
  - cross_asset_decoupling_stack
  - liquidity_stress_anomaly_stack
  - event_context_flags_stack
- all such AI LAB outputs must remain:
  - dev_only = true
  - non_authoritative = true
- no official truth mutation is allowed from AI LAB outputs themselves
- no new strategy line, no phase69 reopening, no scoring loosening, and no APP / DATA / EXECUTION / live-order drift

## Operational posture
- execution outputs are decision-relevant operational artifacts, not official truth
- automation artifacts for execution refresh/runtime are not official truth
- current local-PC runtime discipline is safe read_only + dry_run only
- remaining work is controlled 24/7 runtime discipline, not DATA blocker analysis
