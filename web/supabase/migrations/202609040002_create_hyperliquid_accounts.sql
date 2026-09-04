create table if not exists public.hyperliquid_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  master_address text not null,
  connection_status text not null default 'read_only_connected' check (connection_status = 'read_only_connected'),
  verified_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint hyperliquid_accounts_one_per_user unique (user_id),
  constraint hyperliquid_accounts_one_owner_per_address unique (master_address),
  constraint hyperliquid_accounts_master_address_format
    check (master_address ~ '^0x[0-9a-f]{40}$')
);

alter table public.hyperliquid_accounts enable row level security;
alter table public.hyperliquid_accounts force row level security;

revoke all on table public.hyperliquid_accounts from public, anon, authenticated;
grant select, delete on table public.hyperliquid_accounts to authenticated;

create or replace function public.set_hyperliquid_account_updated_at()
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

revoke all on function public.set_hyperliquid_account_updated_at() from public;

drop trigger if exists hyperliquid_accounts_set_updated_at on public.hyperliquid_accounts;
create trigger hyperliquid_accounts_set_updated_at
  before update on public.hyperliquid_accounts
  for each row execute procedure public.set_hyperliquid_account_updated_at();

drop policy if exists "hyperliquid_accounts_select_own" on public.hyperliquid_accounts;
create policy "hyperliquid_accounts_select_own"
  on public.hyperliquid_accounts for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_accounts_insert_own" on public.hyperliquid_accounts;
create policy "hyperliquid_accounts_insert_own"
  on public.hyperliquid_accounts for insert to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_accounts_update_own" on public.hyperliquid_accounts;
create policy "hyperliquid_accounts_update_own"
  on public.hyperliquid_accounts for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "hyperliquid_accounts_delete_own" on public.hyperliquid_accounts;
create policy "hyperliquid_accounts_delete_own"
  on public.hyperliquid_accounts for delete to authenticated
  using ((select auth.uid()) = user_id);
