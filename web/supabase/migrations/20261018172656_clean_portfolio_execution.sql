-- Additive portfolio evidence; existing secrets, journals, RLS and consent are retained.
alter table public.multi_account_execution_runs add column authorized_target_weights jsonb, add column portfolio_completed_at timestamptz;
alter table public.multi_account_execution_actions
  add column execution_spec jsonb;
create unique index clean_portfolio_one_target_per_account_day
  on public.multi_account_execution_runs(hyperliquid_account_id,canonical_closed_day)
  where strategy_version='trendatlas_clean_5050_v1';
create function public.check_clean_portfolio_evidence() returns trigger
language plpgsql security invoker set search_path=public,pg_temp as $$
declare item record; total numeric := 0;
begin
  if tg_table_name='multi_account_execution_runs' then
    if tg_op='UPDATE' then new.portfolio_completed_at:=coalesce(old.portfolio_completed_at,new.portfolio_completed_at); end if;
    if new.strategy_version='trendatlas_clean_5050_v1' then
      if new.authorized_target_weights is null or jsonb_typeof(new.authorized_target_weights)<>'object' then raise exception 'portfolio weights required'; end if;
      for item in select * from jsonb_each(new.authorized_target_weights) loop
        if item.key !~ '^[A-Z0-9]+$' or item.key in ('BASE','CASH') or jsonb_typeof(item.value)<>'number' then raise exception 'invalid portfolio weight'; end if;
        if (item.value::text)::numeric<0 then raise exception 'negative portfolio weight'; end if;
        total:=total+(item.value::text)::numeric;
      end loop;
      if total>1 or abs(total-new.authorized_target_exposure)>0.000000000001 then raise exception 'portfolio exceeds 1x or mismatched exposure'; end if;
    end if;
    if tg_op='UPDATE' and (old.canonical_signal_id,old.canonical_closed_day,old.authorized_target_weights)
      is distinct from (new.canonical_signal_id,new.canonical_closed_day,new.authorized_target_weights) then raise exception 'portfolio target is immutable'; end if;
  elsif tg_op='UPDATE' and old.execution_spec is distinct from new.execution_spec then
    raise exception 'portfolio order specification is immutable';
  end if;
  return new;
end; $$;
revoke all on function public.check_clean_portfolio_evidence() from public,anon,authenticated;
create trigger check_clean_portfolio_runs before insert or update on public.multi_account_execution_runs
for each row execute function public.check_clean_portfolio_evidence();
create trigger check_clean_portfolio_actions before update on public.multi_account_execution_actions
for each row execute function public.check_clean_portfolio_evidence();
