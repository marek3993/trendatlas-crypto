create schema if not exists public;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  account_status text not null default 'active',
  onboarding_status text not null default 'not_started'
);

alter table public.profiles enable row level security;
alter table public.profiles force row level security;

revoke all on table public.profiles from public, anon, authenticated;
grant select on table public.profiles to authenticated;
grant update (display_name) on table public.profiles to authenticated;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    lower(trim(coalesce(new.email, ''))),
    left(trim(coalesce(new.raw_user_meta_data ->> 'display_name', '')), 120)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

revoke all on function public.handle_new_user() from public;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

create or replace function public.set_profile_updated_at()
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

revoke all on function public.set_profile_updated_at() from public;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute procedure public.set_profile_updated_at();

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
  on public.profiles for select to authenticated
  using ((select auth.uid()) = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);
