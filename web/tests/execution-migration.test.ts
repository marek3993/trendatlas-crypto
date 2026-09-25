import { readFileSync } from "node:fs";
import path from "node:path";
import { PGlite } from "@electric-sql/pglite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const user = "10000000-0000-4000-8000-000000000001";
const account = "20000000-0000-4000-8000-000000000001";
const holder = "30000000-0000-4000-8000-000000000001";
let db: PGlite;
let runId: string;
const sql = (file: string) => readFileSync(path.join(process.cwd(), "supabase/migrations", file), "utf8");

describe("execution migration on PostgreSQL", () => {
  beforeAll(async () => {
    db = new PGlite();
    await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
      create schema auth; create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
      grant usage on schema auth, public to authenticated, service_role;
      create table public.hyperliquid_accounts(id uuid primary key);
      create table public.hyperliquid_agent_authorizations(execution_status text, auto_trading_requested boolean, authorization_status text);
      insert into auth.users values ('${user}'); insert into public.hyperliquid_accounts values ('${account}');`);
    await db.exec(sql("202609050001_create_multi_account_execution.sql"));
    await db.exec("grant all on all tables in schema public to service_role;");
    // Existing evidence must survive the migration, including historically long-only side.
    const inserted = await db.query<{ id: string }>(`insert into multi_account_execution_runs
      (user_id, hyperliquid_account_id, canonical_signal_id, canonical_closed_day, strategy_version, authorized_target_asset, authorized_target_exposure, status)
      values ($1,$2,'historical','2026-09-24','v1','BTC',1,'PARTIAL') returning id`, [user, account]);
    runId = inserted.rows[0].id;
    await db.query(`insert into multi_account_execution_actions(run_id,leg_index,action,asset,requested_notional,size,reduce_only,cloid,hyperliquid_order_id,submission_state,verification_state)
      values($1,0,'EXIT','BTC',40,0.00048,true,'0x11111111111111111111111111111111','123','SUBMITTED','VERIFIED')`, [runId]);
    await db.exec(sql("20260925062507_dynamic_execution_reconciliation.sql"));
  }, 30000);
  afterAll(async () => { await db?.close(); });

  it("preserves journal identity and terminal verification", async () => {
    const before = await db.query<{ side: string }>("select side from multi_account_execution_actions");
    expect(before.rows[0].side).toBe("sell");
    await expect(db.exec("update multi_account_execution_actions set submission_state='NOT_SUBMITTED'")).rejects.toThrow("cannot return");
    await expect(db.exec("update multi_account_execution_actions set size=1")).rejects.toThrow("immutable");
    await expect(db.exec("update multi_account_execution_actions set expires_at_ms=1900000000000")).rejects.toThrow("cannot be inferred retroactively");
    await db.exec("update multi_account_execution_actions set hyperliquid_order_id=null, verification_state='PENDING'");
    const result = await db.query("select hyperliquid_order_id,verification_state from multi_account_execution_actions");
    expect(result.rows[0]).toEqual({ hyperliquid_order_id: "123", verification_state: "VERIFIED" });
  });
  it("accepts new assets, cash outcomes and cancellations without an asset migration", async () => {
    await db.exec("update multi_account_execution_runs set authorized_target_asset='NEWCOIN123', status='EXITED_ENTRY_FAILED_STAYING_CASH'");
    await db.query(`insert into multi_account_execution_actions(run_id,leg_index,action,asset,side,requested_notional,size,reduce_only,cloid,submission_state,verification_state)
      values($1,1,'CANCEL','NEWCOIN123','buy',0,0,false,'0x22222222222222222222222222222222','NOT_SUBMITTED','PENDING')`, [runId]);
    await expect(db.exec("update multi_account_execution_runs set authorized_target_asset='../bad'")).rejects.toThrow();
    await expect(db.exec("update multi_account_execution_actions set side='invalid'")).rejects.toThrow();
  });
  it("retains tenant RLS and forbids browser writes and lease renewal", async () => {
    await db.exec(`set role authenticated; set request.jwt.claim.sub='${user}'`);
    expect((await db.query("select id from multi_account_execution_runs")).rows).toHaveLength(1);
    await db.exec("set request.jwt.claim.sub='10000000-0000-4000-8000-000000000002'");
    expect((await db.query("select id from multi_account_execution_runs")).rows).toHaveLength(0);
    await expect(db.exec("update multi_account_execution_runs set status='FAILED'")).rejects.toThrow("permission denied");
    await expect(db.query("select renew_multi_account_execution_lock($1,$2,120)",[account, holder])).rejects.toThrow("permission denied");
    await db.exec("reset role");
  });
  it("renews only the current unexpired lease and bounds duration", async () => {
    await db.query("select try_acquire_multi_account_execution_lock($1,$2,120)",[account, holder]);
    await db.exec("set role service_role");
    expect((await db.query<{ renewed:boolean }>("select renew_multi_account_execution_lock($1,$2,120) as renewed",[account,holder])).rows[0].renewed).toBe(true);
    expect((await db.query<{ renewed:boolean }>("select renew_multi_account_execution_lock($1,$2,120) as renewed",[account,user])).rows[0].renewed).toBe(false);
    await expect(db.query("select renew_multi_account_execution_lock($1,$2,301)",[account,holder])).rejects.toThrow("invalid lease");
    await db.exec("update multi_account_execution_locks set locked_until=clock_timestamp()-interval '1 second'");
    expect((await db.query<{ renewed:boolean }>("select renew_multi_account_execution_lock($1,$2,120) as renewed",[account,holder])).rows[0].renewed).toBe(false);
    await db.exec("reset role");
  });
});
