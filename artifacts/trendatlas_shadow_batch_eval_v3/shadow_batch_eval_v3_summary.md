# TrendAtlas Shadow Batch Eval

- Evaluated at: `2026-04-25T19:48:28Z`
- Execution mode: `mock`
- Final status: `working`
- Cases evaluated: `1`
- Fail-closed preserved across all cases: `True`
- Requested case set complete: `True`
- Compact manual review artifact: `C:\Users\benda\Desktop\market_regime_v1\artifacts\trendatlas_shadow_batch_eval_v3\shadow_batch_eval_v3_manual_review.csv`

## Decision Field Counts

- Planner: `{"exact_change": 0, "source_artifact_id": 0, "stop_condition": 0, "target_id": 0, "target_type": 0}`
- Critic: `{"recommended_next_action": 0, "recommended_verdict": 0}`

## Blocked Conditions

- Blocked reasons: `none`
- Evaluation errors: `0`
- Missing requested cases: `0`
- Retrieval-missing cases: `0`
- Real-call failure cases: `0`

## Reasoning-Only Diffs

- Planner reasoning-only cases: `1`
- Critic reasoning-only cases: `1`
- Planner reasoning field diff frequency: `{"mechanism_hypothesis": 1, "selection_rationale": 1}`
- Critic reasoning field diff frequency: `{"policy_alignment_note": 1, "recommended_reason": 1}`

## Token Deltas

- Planner prompt/input/output deltas: `{"prompt_estimated_input_tokens_delta": {"avg": 2123.0, "count": 1, "max": 2123, "min": 2123, "sum": 2123}, "response_input_tokens_delta": {"avg": 36.0, "count": 1, "max": 36, "min": 36, "sum": 36}, "response_output_tokens_delta": {"avg": 3.0, "count": 1, "max": 3, "min": 3, "sum": 3}, "response_total_tokens_delta": {"avg": 39.0, "count": 1, "max": 39, "min": 39, "sum": 39}}`
- Critic prompt/input/output deltas: `{"prompt_estimated_input_tokens_delta": {"avg": 2115.0, "count": 1, "max": 2115, "min": 2115, "sum": 2115}, "response_input_tokens_delta": {"avg": 38.0, "count": 1, "max": 38, "min": 38, "sum": 38}, "response_output_tokens_delta": {"avg": 4.0, "count": 1, "max": 4, "min": 4, "sum": 4}, "response_total_tokens_delta": {"avg": 42.0, "count": 1, "max": 42, "min": 42, "sum": 42}}`

## Reasoning Changed, Decision Identical

- Planner cases: `1`
- Critic cases: `1`
- Combined cases: `1`

## Cases

- `cost_aware_hysteretic_pilot_to_full / openai_token_opt_rerun`: planner_candidate_status=`completed`, critic_candidate_status=`completed`, planner_reasoning_changed_decision_identical=`True`, critic_reasoning_changed_decision_identical=`True`, planner_output_delta=`3`, critic_output_delta=`4`
