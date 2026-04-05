# Master State

## Official state snapshot
- research/raw leverage winner: phase68i_66g_1p50x_static
- best deployment candidate: phase68i_dynamic_ladder_candidate
- official softer fallback: phase68g_66g_1p25x_candidate
- Phase68J simple tail-risk guardrails: rejected
- ordering: unchanged
- leverage branch: live truth approved and applied
- current live truth: phase68i_dynamic_ladder_candidate
- direct app/live truth switch: approved and applied
- real-order gate: live_order_enabled_and_approved
- only real-order eligible status: live_order_enabled_and_approved

## Workflow rules
- Repo-heavy / multi-step workflow: Codex should be used for repo patching/execution.
- Heavy validations are run locally by the user.
- Segment chat interprets validation results and gives the next exact step.
- Truth-sensitive workflow: repo-based conclusions must include a FILES READ header listing the actual SSOT/README files read.
