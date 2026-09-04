-- Stage 5: durable, server-written execution evidence for explicitly enrolled
-- multi-user accounts.  Browser roles can only read their own history.
alter table public.hyperliquid_agent_authorizations
  drop constraint if exists hyperliquid_agent_authorizations_execution_status_check;

alter table public.hyperliquid_agent_authorizations
  add constraint hyperliquid_agent_authorizations_execution_status_check
  check (execution_status in (
    'pending_multi_account_executor', 'ready', 'disabled_by_user',
    'blocked', 'executing', 'aligned', 'error'
  ));

update public.hyperliquid_agent_authorizations
set execution_status = case when auto_trading_requested then 'ready' else 'disabled_by_user' end
where authorization_status = 'authorized'
  and execution_status = 'pending_multi_account_executor';

create table if not exists public.multi_account_execution_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  hyperliquid_account_id uuid not null references public.hyperliquid_accounts(id) on delete cascade,
  canonical_signal_id text not null,
  canonical_closed_day date not null,
  strategy_version text not null,
  authorized_target_asset text not null check (authorized_target_asset in ('BTC', 'ETH', 'CASH')),
  authorized_target_exposure numeric not null check (authorized_target_exposure >= 0),
  account_equity_before numeric,
  account_equity_after numeric,
  status text not null check (status in ('NO_ACTION', 'FILLED_AND_ALIGNED', 'PARTIAL', 'FAILED', 'BLOCKED', 'UNKNOWN_SUBMISSION_STATE', 'DISABLED', 'DRY_RUN')),
  started_at timestamptz not null default timezone('utc', now()),
  completed_at timestamptz,
  sanitized_error text,
  unique (hyperliquid_account_id, canonical_signal_id)
);

create table if not exists public.multi_account_execution_actions (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.multi_account_execution_runs(id) on delete cascade,
  leg_index integer not null check (leg_index >= 0),
  action text not null check (action in ('ENTER', 'EXIT', 'RESIZE')),
  asset text not null check (asset in ('BTC', 'ETH')),
  requested_notional numeric not null check (requested_notional >= 0),
  size numeric not null check (size > 0),
  reduce_only boolean not null,
  cloid text not null check (cloid ~ '^0x[0-9a-f]{32}$'),
  hyperliquid_order_id text,
  submission_state text not null check (submission_state in ('NOT_SUBMITTED', 'KNOWN', 'SUBMITTED', 'AMBIGUOUS', 'REJECTED')),
  verification_state text not null check (verification_state in ('PENDING', 'VERIFIED', 'UNALIGNED', 'UNKNOWN')),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (cloid)
);

create table if not exists public.multi_account_agent_nonces (
  agent_address text primary key check (agent_address ~ '^0x[0-9a-f]{40}$'),
  last_nonce bigint not null check (last_nonce >= 0),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.multi_account_execution_locks (
  hyperliquid_account_id uuid primary key references public.hyperliquid_accounts(id) on delete cascade,
  locked_until timestamptz not null,
  holder_id uuid not null,
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.multi_account_execution_runs enable row level security;
alter table public.multi_account_execution_runs force row level security;
alter table public.multi_account_execution_actions enable row level security;
alter table public.multi_account_execution_actions force row level security;
alter table public.multi_account_agent_nonces enable row level security;
alter table public.multi_account_agent_nonces force row level security;
alter table public.multi_account_execution_locks enable row level security;
alter table public.multi_account_execution_locks force row level security;

revoke all on table public.multi_account_execution_runs, public.multi_account_execution_actions, public.multi_account_agent_nonces, public.multi_account_execution_locks from public, anon, authenticated;
grant select on table public.multi_account_execution_runs, public.multi_account_execution_actions to authenticated;

create policy "multi_account_execution_runs_select_own" on public.multi_account_execution_runs
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "multi_account_execution_actions_select_own" on public.multi_account_execution_actions
  for select to authenticated using (exists (
    select 1 from public.multi_account_execution_runs r
    where r.id = run_id and r.user_id = (select auth.uid())
  ));

create or replace function public.reserve_multi_account_agent_nonce(expected_agent_address text)
returns bigint language plpgsql security definer set search_path = public, pg_temp as $$
declare reserved_nonce bigint;
begin
  insert into public.multi_account_agent_nonces(agent_address, last_nonce)
  values (expected_agent_address, floor(extract(epoch from clock_timestamp()) * 1000)::bigint)
  on conflict (agent_address) do update set
    last_nonce = greatest(
      public.multi_account_agent_nonces.last_nonce + 1,
      floor(extract(epoch from clock_timestamp()) * 1000)::bigint
    ), updated_at = timezone('utc', now())
  returning last_nonce into reserved_nonce;
  return reserved_nonce;
end;
$$;
revoke all on function public.reserve_multi_account_agent_nonce(text) from public, anon, authenticated;

create or replace function public.try_acquire_multi_account_execution_lock(
  expected_account_id uuid,
  expected_holder_id uuid,
  lease_seconds integer default 120
)
returns boolean language plpgsql security definer set search_path = public, pg_temp as $$
declare acquired boolean;
begin
  insert into public.multi_account_execution_locks(hyperliquid_account_id, holder_id, locked_until)
  values (expected_account_id, expected_holder_id, timezone('utc', now()) + make_interval(secs => lease_seconds))
  on conflict (hyperliquid_account_id) do update set
    holder_id = excluded.holder_id,
    locked_until = excluded.locked_until,
    updated_at = timezone('utc', now())
  where public.multi_account_execution_locks.locked_until < timezone('utc', now())
  returning true into acquired;
  return coalesce(acquired, false);
end;
$$;
revoke all on function public.try_acquire_multi_account_execution_lock(uuid, uuid, integer) from public, anon, authenticated;

create or replace function public.release_multi_account_execution_lock(expected_account_id uuid, expected_holder_id uuid)
returns void language sql security definer set search_path = public, pg_temp as $$
  delete from public.multi_account_execution_locks
  where hyperliquid_account_id = expected_account_id and holder_id = expected_holder_id;
$$;
revoke all on function public.release_multi_account_execution_lock(uuid, uuid) from public, anon, authenticated;
