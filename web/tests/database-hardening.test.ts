import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const source = (relativePath: string) => fs.readFileSync(path.join(root, relativePath), "utf8");
const securityDefinerHardening = source("supabase/migrations/20260904231337_harden_security_definer_execute_privileges.sql");
const performanceHardening = source("supabase/migrations/20260904231430_harden_performance_write_integrity.sql");
const indexes = source("supabase/migrations/20260904231503_add_multiuser_foreign_key_indexes.sql");
const performanceSchema = source("supabase/migrations/202609040003_create_hyperliquid_account_performance.sql");
const agentSchema = source("supabase/migrations/202609040004_create_hyperliquid_agent_authorizations.sql");
const executionSchema = source("supabase/migrations/202609050001_create_multi_account_execution.sql");
const refreshAction = source("src/app/dashboard/actions.ts");
const adminModule = source("src/lib/supabase/admin.ts");

describe("canary database hardening", () => {
  it("keeps authenticated users read-only for their own canonical performance", () => {
    expect(performanceHardening).toContain("revoke insert, update on table public.hyperliquid_account_performance from authenticated;");
    expect(performanceHardening).toContain("revoke insert, update on table public.hyperliquid_account_performance_history from authenticated;");
    [
      "hyperliquid_account_performance_insert_own",
      "hyperliquid_account_performance_update_own",
      "hyperliquid_account_performance_history_insert_own",
      "hyperliquid_account_performance_history_update_own"
    ].forEach((policy) => expect(performanceHardening).toContain(`drop policy if exists ${policy}`));
    expect(performanceSchema).toContain("hyperliquid_account_performance_select_own");
    expect(performanceSchema).toContain("hyperliquid_account_performance_history_select_own");
  });

  it("derives refresh identity from the authenticated account lookup and persists only through the trusted server client", () => {
    expect(refreshAction).toContain("const { supabase, user } = await requireUser()");
    expect(refreshAction).toContain('.eq("user_id", user.id)');
    expect(refreshAction).toContain("getHyperliquidAccountPerformance(account.master_address)");
    expect(refreshAction).toContain("const admin = createAdminClient()");
    expect(refreshAction).toContain('admin.from("hyperliquid_account_performance").upsert');
    expect(refreshAction).toContain('admin.from("hyperliquid_account_performance_history").upsert');
    expect(refreshAction).not.toContain('supabase.from("hyperliquid_account_performance").upsert');
    expect(refreshAction).not.toContain('supabase.from("hyperliquid_account_performance_history").upsert');
  });

  it("keeps the admin credential server-only and out of browser modules", () => {
    expect(adminModule).toMatch(/^import "server-only";/);
    const clientModules = fs.readdirSync(path.join(root, "src"), { recursive: true })
      .filter((entry): entry is string => typeof entry === "string" && /\.(ts|tsx)$/.test(entry))
      .map((entry) => path.join(root, "src", entry))
      .filter((file) => /^\s*["']use client["']/.test(fs.readFileSync(file, "utf8")));
    clientModules.forEach((file) => {
      const contents = fs.readFileSync(file, "utf8");
      expect(contents).not.toMatch(/SUPABASE_ADMIN_KEY|service[_-]?role|supabase\/admin/i);
    });
  });

  it("denies browser roles every security-definer helper and limits execution RPCs to service_role", () => {
    const functions = [
      "handle_new_user()",
      "set_profile_updated_at()",
      "set_hyperliquid_account_updated_at()",
      "set_hyperliquid_account_performance_updated_at()",
      "set_hyperliquid_agent_authorization_updated_at()",
      "consume_hyperliquid_agent_approval_challenge(uuid, uuid)",
      "reserve_multi_account_agent_nonce(text)",
      "try_acquire_multi_account_execution_lock(uuid, uuid, integer)",
      "release_multi_account_execution_lock(uuid, uuid)"
    ];
    functions.forEach((fn) => expect(securityDefinerHardening).toContain(`revoke execute on function public.${fn} from public, anon, authenticated;`));
    [
      "consume_hyperliquid_agent_approval_challenge(uuid, uuid)",
      "reserve_multi_account_agent_nonce(text)",
      "try_acquire_multi_account_execution_lock(uuid, uuid, integer)",
      "release_multi_account_execution_lock(uuid, uuid)"
    ].forEach((fn) => expect(securityDefinerHardening).toContain(`grant execute on function public.${fn} to service_role;`));
  });

  it("keeps agent secrets, approval challenges, nonces, and locks inaccessible to browser roles", () => {
    expect(agentSchema).toContain("revoke all on table public.hyperliquid_agent_secrets from public, anon, authenticated;");
    expect(agentSchema).toContain("revoke all on table public.hyperliquid_agent_approval_challenges from public, anon, authenticated;");
    expect(executionSchema).toContain("revoke all on table public.multi_account_execution_runs, public.multi_account_execution_actions, public.multi_account_agent_nonces, public.multi_account_execution_locks from public, anon, authenticated;");
    expect(executionSchema).not.toMatch(/grant\s+(?:select|insert|update|delete)[^;]*(?:multi_account_agent_nonces|multi_account_execution_locks)[^;]*authenticated/i);
  });

  it("adds all foreign-key lookup indexes for multi-user queries", () => {
    [
      "hyperliquid_account_performance_account_owner_idx",
      "hyperliquid_account_performance_user_idx",
      "hyperliquid_account_performance_history_account_owner_idx",
      "hyperliquid_account_performance_history_user_idx",
      "hyperliquid_agent_authorizations_account_owner_idx",
      "hyperliquid_agent_authorizations_user_idx",
      "hyperliquid_agent_approval_challenges_account_owner_idx",
      "hyperliquid_agent_approval_challenges_authorization_idx",
      "hyperliquid_agent_approval_challenges_user_idx",
      "multi_account_execution_actions_run_idx",
      "multi_account_execution_runs_user_idx"
    ].forEach((index) => expect(indexes).toContain(`create index if not exists ${index}`));
  });
});
