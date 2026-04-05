# Current Issues

## Leverage live truth status
- research/raw winner = phase68i_66g_1p50x_static
- best deployment candidate = phase68i_dynamic_ladder_candidate
- official softer fallback = phase68g_66g_1p25x_candidate
- Phase68J simple tail-risk guardrails = rejected
- ordering remains unchanged
- leverage branch live truth has been promoted to phase68i_dynamic_ladder_candidate
- direct app/live truth switch is approved and applied
- current live truth is phase68i_dynamic_ladder_candidate
- approval_gate_status = approved_and_applied
- real orders are enabled and approved under live_order_enabled_and_approved
- only live_order_enabled_and_approved counts as real-order eligible

## Execution refresh branch status
- Hyperliquid execution branch is enabled for guarded live-order runtime
- automation wrapper layer for execution refresh is functional
- canonical execution chain is:
1. scripts/execution/materialize_execution_app_exports.py
2. scripts/execution/validate_execution_source_contract.py
3. scripts/execution/hyperliquid_read_only_snapshot.py
4. scripts/execution/render_execution_app_status.py
5. scripts/execution/build_execution_intent_from_strategy_exports.py
6. scripts/execution/run_dry_execution_bridge.py
- execution outputs are decision-relevant operational artifacts, not official truth
- automation artifacts for execution refresh are not official truth
- live orders are enabled and approved
- source_of_truth writes are not part of execution refresh runtime
