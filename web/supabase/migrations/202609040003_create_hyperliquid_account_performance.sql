-- User-owned, normalized read-only account-performance snapshots. No exchange
-- credentials, raw exchange payloads, model fields, or any other account's data
-- are stored here.
alter table public.hyperliquid_accounts
  add constraint hyperliquid_accounts_id_user_id_unique unique (id, user_id);

create table if not exists public.hyperliquid_account_performance (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  hyperliquid_account_id uuid not null,
  snapshot_at timestamptz not null,
  account_equity_usd numeric not null check (account_equity_usd >= 0),
  live_genesis_at timestamptz,
  history_days integer not null check (history_days >= 0),
  total_live_pnl_usd numeric,
  cash_flow_adjusted_return_pct numeric,
  cash_flow_adjusted_return_available boolean not null default false,
  cash_flow_adjusted_return_reason text,
  trading_pnl_usd numeric,
  fees_usd numeric,
  funding_usd numeric,
  deposits_usd numeric,
  withdrawals_usd numeric,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint hyperliquid_account_performance_owner_fk
    foreign key (hyperliquid_account_id, user_id)
    references public.hyperliquid_accounts (id, user_id) on delete cascade,
  constraint hyperliquid_account_performance_one_current_per_account unique (hyperliquid_account_id)
);

create table if not exists public.hyperliquid_account_performance_history (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  hyperliquid_account_id uuid not null,
  performance_day date not null,
  snapshot_at timestamptz not null,
  account_equity_usd numeric not null check (account_equity_usd >= 0),
  total_live_pnl_usd numeric,
  trading_pnl_usd numeric,
  fees_usd numeric,
  funding_usd numeric,
  deposits_usd numeric,
  withdrawals_usd numeric,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint hyperliquid_account_performance_history_owner_fk
    foreign key (hyperliquid_account_id, user_id)
    references public.hyperliquid_accounts (id, user_id) on delete cascade,
  constraint hyperliquid_account_performance_history_one_row_per_day unique (hyperliquid_account_id, performance_day)
);

alter table public.hyperliquid_account_performance enable row level security;
alter table public.hyperliquid_account_performance force row level security;
alter table public.hyperliquid_account_performance_history enable row level security;
alter table public.hyperliquid_account_performance_history force row level security;

revoke all on table public.hyperliquid_account_performance from public, anon, authenticated;
revoke all on table public.hyperliquid_account_performance_history from public, anon, authenticated;
grant select, insert, update on table public.hyperliquid_account_performance to authenticated;
grant select, insert, update on table public.hyperliquid_account_performance_history to authenticated;

create or replace function public.set_hyperliquid_account_performance_updated_at()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

revoke all on function public.set_hyperliquid_account_performance_updated_at() from public;

drop trigger if exists hyperliquid_account_performance_set_updated_at on public.hyperliquid_account_performance;
create trigger hyperliquid_account_performance_set_updated_at
  before update on public.hyperliquid_account_performance
  for each row execute procedure public.set_hyperliquid_account_performance_updated_at();

drop trigger if exists hyperliquid_account_performance_history_set_updated_at on public.hyperliquid_account_performance_history;
create trigger hyperliquid_account_performance_history_set_updated_at
  before update on public.hyperliquid_account_performance_history
  for each row execute procedure public.set_hyperliquid_account_performance_updated_at();

drop policy if exists "hyperliquid_account_performance_select_own" on public.hyperliquid_account_performance;
create policy "hyperliquid_account_performance_select_own"
  on public.hyperliquid_account_performance for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_account_performance_insert_own" on public.hyperliquid_account_performance;
create policy "hyperliquid_account_performance_insert_own"
  on public.hyperliquid_account_performance for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_account_performance_update_own" on public.hyperliquid_account_performance;
create policy "hyperliquid_account_performance_update_own"
  on public.hyperliquid_account_performance for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_account_performance_history_select_own" on public.hyperliquid_account_performance_history;
create policy "hyperliquid_account_performance_history_select_own"
  on public.hyperliquid_account_performance_history for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_account_performance_history_insert_own" on public.hyperliquid_account_performance_history;
create policy "hyperliquid_account_performance_history_insert_own"
  on public.hyperliquid_account_performance_history for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_account_performance_history_update_own" on public.hyperliquid_account_performance_history;
create policy "hyperliquid_account_performance_history_update_own"
  on public.hyperliquid_account_performance_history for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
