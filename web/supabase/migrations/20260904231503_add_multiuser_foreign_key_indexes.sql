create index if not exists hyperliquid_account_performance_account_owner_idx
  on public.hyperliquid_account_performance(hyperliquid_account_id, user_id);

create index if not exists hyperliquid_account_performance_user_idx
  on public.hyperliquid_account_performance(user_id);

create index if not exists hyperliquid_account_performance_history_account_owner_idx
  on public.hyperliquid_account_performance_history(hyperliquid_account_id, user_id);

create index if not exists hyperliquid_account_performance_history_user_idx
  on public.hyperliquid_account_performance_history(user_id);

create index if not exists hyperliquid_agent_authorizations_account_owner_idx
  on public.hyperliquid_agent_authorizations(hyperliquid_account_id, user_id);

create index if not exists hyperliquid_agent_authorizations_user_idx
  on public.hyperliquid_agent_authorizations(user_id);

create index if not exists hyperliquid_agent_approval_challenges_account_owner_idx
  on public.hyperliquid_agent_approval_challenges(hyperliquid_account_id, user_id);

create index if not exists hyperliquid_agent_approval_challenges_authorization_idx
  on public.hyperliquid_agent_approval_challenges(authorization_id);

create index if not exists hyperliquid_agent_approval_challenges_user_idx
  on public.hyperliquid_agent_approval_challenges(user_id);

create index if not exists multi_account_execution_actions_run_idx
  on public.multi_account_execution_actions(run_id);

create index if not exists multi_account_execution_runs_user_idx
  on public.multi_account_execution_runs(user_id);
