-- Asset support belongs to current exchange metadata, not a database enum.
-- Preserve all journals, enrollment, secrets, grants and RLS policies.
alter table public.multi_account_execution_runs
  drop constraint multi_account_execution_runs_authorized_target_asset_check,
  add constraint multi_account_execution_runs_authorized_target_asset_check
    check (authorized_target_asset ~ '^[A-Z0-9][A-Z0-9._:-]{0,63}$'),
  drop constraint multi_account_execution_runs_status_check,
  add constraint multi_account_execution_runs_status_check check (status in (
    'NO_ACTION', 'FILLED_AND_ALIGNED', 'PARTIAL', 'FAILED', 'BLOCKED',
    'UNKNOWN_SUBMISSION_STATE', 'DISABLED', 'DRY_RUN',
    'EXITED_ENTRY_FAILED_STAYING_CASH', 'ENTRY_FAILED_STAYING_CASH'
  ));

alter table public.multi_account_execution_actions
  add column side text,
  add column expires_at_ms bigint check (expires_at_ms > 0 and expires_at_ms <= 9007199254740991),
  drop constraint multi_account_execution_actions_asset_check,
  add constraint multi_account_execution_actions_asset_check
    check (asset ~ '^[A-Z0-9][A-Z0-9._:-]{0,63}$' and asset <> 'CASH'),
  drop constraint multi_account_execution_actions_action_check,
  add constraint multi_account_execution_actions_action_check
    check (action in ('ENTER', 'EXIT', 'RESIZE', 'CANCEL')),
  drop constraint multi_account_execution_actions_size_check,
  add constraint multi_account_execution_actions_size_check
    check (size > 0 or (action = 'CANCEL' and size = 0));

-- The previous executor was long-only. Preserve its historical order identity.
update public.multi_account_execution_actions
  set side = case when reduce_only then 'sell' else 'buy' end where side is null;
alter table public.multi_account_execution_actions
  alter column side set not null,
  add constraint multi_account_execution_actions_side_check check (side in ('buy', 'sell'));

create or replace function public.preserve_multi_account_action_evidence()
returns trigger language plpgsql security invoker set search_path = public, pg_temp as $$
begin
  if old.expires_at_ms is not null and new.expires_at_ms is distinct from old.expires_at_ms then
    raise exception 'signed order expiry is immutable';
  end if;
  if old.submission_state <> 'NOT_SUBMITTED' then
    if new.expires_at_ms is distinct from old.expires_at_ms then
      raise exception 'submitted order expiry cannot be inferred retroactively';
    end if;
    if new.submission_state = 'NOT_SUBMITTED' then
      raise exception 'submitted action cannot return to an unsubmitted state';
    end if;
    if (new.run_id, new.cloid, new.asset, new.side, new.size, new.reduce_only, new.action)
       is distinct from (old.run_id, old.cloid, old.asset, old.side, old.size, old.reduce_only, old.action) then
      raise exception 'submitted action identity is immutable';
    end if;
  end if;
  new.hyperliquid_order_id := coalesce(new.hyperliquid_order_id, old.hyperliquid_order_id);
  if old.verification_state = 'VERIFIED' then new.verification_state := 'VERIFIED'; end if;
  return new;
end;
$$;
revoke all on function public.preserve_multi_account_action_evidence() from public, anon, authenticated;
create trigger preserve_multi_account_action_evidence
  before update on public.multi_account_execution_actions
  for each row execute function public.preserve_multi_account_action_evidence();

create or replace function public.renew_multi_account_execution_lock(
  expected_account_id uuid, expected_holder_id uuid, lease_seconds integer default 120
)
returns boolean language plpgsql security invoker set search_path = public, pg_temp as $$
declare renewed boolean;
begin
  if lease_seconds < 1 or lease_seconds > 300 then raise exception 'invalid lease duration'; end if;
  update public.multi_account_execution_locks
  set locked_until = clock_timestamp() + make_interval(secs => lease_seconds), updated_at = clock_timestamp()
  where hyperliquid_account_id = expected_account_id and holder_id = expected_holder_id
    and locked_until > clock_timestamp()
  returning true into renewed;
  return coalesce(renewed, false);
end;
$$;
revoke all on function public.renew_multi_account_execution_lock(uuid, uuid, integer) from public, anon, authenticated;
grant execute on function public.renew_multi_account_execution_lock(uuid, uuid, integer) to service_role;

-- timestamptz leases must not depend on the database session's timezone.
create or replace function public.try_acquire_multi_account_execution_lock(
  expected_account_id uuid, expected_holder_id uuid, lease_seconds integer default 120
)
returns boolean language plpgsql security invoker set search_path = public, pg_temp as $$
declare acquired boolean;
begin
  if lease_seconds < 1 or lease_seconds > 300 then raise exception 'invalid lease duration'; end if;
  insert into public.multi_account_execution_locks(hyperliquid_account_id, holder_id, locked_until, updated_at)
  values (expected_account_id, expected_holder_id, clock_timestamp() + make_interval(secs => lease_seconds), clock_timestamp())
  on conflict (hyperliquid_account_id) do update
    set holder_id = excluded.holder_id, locked_until = excluded.locked_until, updated_at = clock_timestamp()
    where public.multi_account_execution_locks.locked_until < clock_timestamp()
  returning true into acquired;
  return coalesce(acquired, false);
end;
$$;
revoke all on function public.try_acquire_multi_account_execution_lock(uuid, uuid, integer) from public, anon, authenticated;
grant execute on function public.try_acquire_multi_account_execution_lock(uuid, uuid, integer) to service_role;

create index if not exists multi_account_execution_actions_order_id_idx
  on public.multi_account_execution_actions(hyperliquid_order_id) where hyperliquid_order_id is not null;
