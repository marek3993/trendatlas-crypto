-- Stage 4 authorization metadata is user-visible, but its signing material and
-- one-time approval challenges are server-only. No browser role can write any
-- authorization state or read a private key.
create table if not exists public.hyperliquid_agent_authorizations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  hyperliquid_account_id uuid not null,
  master_address text not null,
  agent_address text not null unique,
  agent_name text not null unique,
  authorization_status text not null default 'pending'
    check (authorization_status in ('pending', 'authorized', 'failed')),
  ownership_verified_at timestamptz,
  agent_authorized_at timestamptz,
  auto_trading_requested boolean not null default true,
  execution_status text not null default 'pending_multi_account_executor'
    check (execution_status = 'pending_multi_account_executor'),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint hyperliquid_agent_authorizations_account_owner_fk
    foreign key (hyperliquid_account_id, user_id)
    references public.hyperliquid_accounts (id, user_id) on delete cascade,
  constraint hyperliquid_agent_authorizations_master_address_format
    check (master_address ~ '^0x[0-9a-f]{40}$'),
  constraint hyperliquid_agent_authorizations_agent_address_format
    check (agent_address ~ '^0x[0-9a-f]{40}$'),
  constraint hyperliquid_agent_authorizations_agent_name_format
    check (agent_name ~ '^TA-[a-f0-9]{8}$')
);

create unique index if not exists hyperliquid_agent_authorizations_one_authorized_per_account
  on public.hyperliquid_agent_authorizations (hyperliquid_account_id)
  where authorization_status = 'authorized';

create table if not exists public.hyperliquid_agent_secrets (
  authorization_id uuid primary key references public.hyperliquid_agent_authorizations(id) on delete cascade,
  encrypted_private_key text not null,
  encryption_nonce text not null,
  encryption_key_version text not null,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.hyperliquid_agent_approval_challenges (
  id uuid primary key default gen_random_uuid(),
  authorization_id uuid not null references public.hyperliquid_agent_authorizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  hyperliquid_account_id uuid not null,
  master_address text not null,
  agent_address text not null,
  agent_name text not null,
  nonce bigint not null check (nonce >= 0),
  signature_chain_id text not null check (signature_chain_id = '0xa4b1'),
  hyperliquid_chain text not null check (hyperliquid_chain = 'Mainnet'),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  constraint hyperliquid_agent_approval_challenges_account_owner_fk
    foreign key (hyperliquid_account_id, user_id)
    references public.hyperliquid_accounts (id, user_id) on delete cascade,
  constraint hyperliquid_agent_approval_challenges_master_address_format
    check (master_address ~ '^0x[0-9a-f]{40}$'),
  constraint hyperliquid_agent_approval_challenges_agent_address_format
    check (agent_address ~ '^0x[0-9a-f]{40}$'),
  constraint hyperliquid_agent_approval_challenges_agent_name_format
    check (agent_name ~ '^TA-[a-f0-9]{8}$')
);

alter table public.hyperliquid_agent_authorizations enable row level security;
alter table public.hyperliquid_agent_authorizations force row level security;
alter table public.hyperliquid_agent_secrets enable row level security;
alter table public.hyperliquid_agent_secrets force row level security;
alter table public.hyperliquid_agent_approval_challenges enable row level security;
alter table public.hyperliquid_agent_approval_challenges force row level security;

revoke all on table public.hyperliquid_agent_authorizations from public, anon, authenticated;
grant select on table public.hyperliquid_agent_authorizations to authenticated;
revoke all on table public.hyperliquid_agent_secrets from public, anon, authenticated;
revoke all on table public.hyperliquid_agent_approval_challenges from public, anon, authenticated;

drop policy if exists "hyperliquid_agent_authorizations_select_own" on public.hyperliquid_agent_authorizations;
create policy "hyperliquid_agent_authorizations_select_own"
  on public.hyperliquid_agent_authorizations for select to authenticated
  using ((select auth.uid()) = user_id);

create or replace function public.set_hyperliquid_agent_authorization_updated_at()
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

revoke all on function public.set_hyperliquid_agent_authorization_updated_at() from public;

drop trigger if exists hyperliquid_agent_authorizations_set_updated_at on public.hyperliquid_agent_authorizations;
create trigger hyperliquid_agent_authorizations_set_updated_at
  before update on public.hyperliquid_agent_authorizations
  for each row execute procedure public.set_hyperliquid_agent_authorization_updated_at();

-- The server consumes a challenge before the exchange POST. This provides an
-- atomic, one-use gate even when two submissions race. Browser roles cannot
-- execute this function.
create or replace function public.consume_hyperliquid_agent_approval_challenge(
  challenge_id uuid,
  expected_user_id uuid
)
returns public.hyperliquid_agent_approval_challenges
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  consumed public.hyperliquid_agent_approval_challenges;
begin
  update public.hyperliquid_agent_approval_challenges
  set consumed_at = timezone('utc', now())
  where id = challenge_id
    and user_id = expected_user_id
    and consumed_at is null
    and expires_at > timezone('utc', now())
  returning * into consumed;

  if not found then
    raise exception 'approval challenge is unavailable';
  end if;
  return consumed;
end;
$$;

revoke all on function public.consume_hyperliquid_agent_approval_challenge(uuid, uuid) from public, anon, authenticated;
