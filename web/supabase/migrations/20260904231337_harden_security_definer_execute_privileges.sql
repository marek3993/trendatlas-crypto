revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.set_profile_updated_at() from public, anon, authenticated;
revoke execute on function public.set_hyperliquid_account_updated_at() from public, anon, authenticated;
revoke execute on function public.set_hyperliquid_account_performance_updated_at() from public, anon, authenticated;
revoke execute on function public.set_hyperliquid_agent_authorization_updated_at() from public, anon, authenticated;
revoke execute on function public.consume_hyperliquid_agent_approval_challenge(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.reserve_multi_account_agent_nonce(text) from public, anon, authenticated;
revoke execute on function public.try_acquire_multi_account_execution_lock(uuid, uuid, integer) from public, anon, authenticated;
revoke execute on function public.release_multi_account_execution_lock(uuid, uuid) from public, anon, authenticated;

grant execute on function public.consume_hyperliquid_agent_approval_challenge(uuid, uuid) to service_role;
grant execute on function public.reserve_multi_account_agent_nonce(text) to service_role;
grant execute on function public.try_acquire_multi_account_execution_lock(uuid, uuid, integer) to service_role;
grant execute on function public.release_multi_account_execution_lock(uuid, uuid) to service_role;
