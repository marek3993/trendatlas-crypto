/** Operator migration observation only. No live gateway or persistence methods. */
import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { createAdminClient } from "@/lib/supabase/admin";
import { SupabaseExecutionRepository } from "@/server/multi-account-executor/repository";
import { HyperliquidDryRunGateway } from "@/server/multi-account-executor/dry-run-gateway";
import { preflightMultiAccountCandidates } from "@/server/multi-account-executor/live-preflight";
import { loadCanonicalRunTarget } from "@/server/multi-account-executor/authority";
import { buildPlan } from "@/server/multi-account-executor/planner";

const digest = (x: unknown) => createHash("sha256").update(JSON.stringify(x)).digest("hex");
async function checkpoint() {
  const db = createAdminClient(true);
  const tables: Record<string, unknown> = {};
  for (const table of ["multi_account_execution_runs", "multi_account_execution_actions", "multi_account_agent_nonces", "multi_account_execution_locks", "hyperliquid_agent_authorizations"]) {
    const columns = table === "hyperliquid_agent_authorizations" ? "id,hyperliquid_account_id,agent_address,agent_name,authorization_status,auto_trading_requested,execution_status" : "*";
    const { data, error, count } = await db.from(table).select(columns, { count: "exact" }).range(0, 9999);
    if (error || !data || count !== data.length) throw new Error("journal checkpoint unavailable or truncated: " + table);
    tables[table] = data.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  }
  return { tables, sha256: digest(tables) };
}
async function main() {
  const root = process.env.TRENDATLAS_AUTHORITY_REPOSITORY_ROOT!;
  const output = process.argv[2];
  if (!root || !output) throw new Error("root/output required");
  const production = JSON.parse(await fs.readFile(path.join(root, "outputs/production/current_strategy_snapshot.json"), "utf8"));
  // Preserve existing canonical intent/gate fingerprints; do not rewrite runtime files.
  const runId = "migration-read-only";
  process.env.MRV1_CURRENT_AUTHORITY_RUN_ID = runId;
  process.env.MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY = production.closed_day;
  process.env.MRV1_EXECUTION_BACKEND = "multi_account";
  const target = await loadCanonicalRunTarget(root, runId, production.execution_intent.signal_id);
  const repository = new SupabaseExecutionRepository(true);
  const exchange = new HyperliquidDryRunGateway();
  const before = await checkpoint();
  const candidates = await repository.listMultiAccountCandidates();
  const preflight = await preflightMultiAccountCandidates(candidates, target, exchange, repository);
  const markets = await exchange.readMarkets();
  const accounts = [];
  for (const candidate of candidates) {
    const account = await exchange.readAccount(candidate.masterAddress);
    const fillsResponse = await fetch("https://api.hyperliquid.xyz/info", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "userFills", user: candidate.masterAddress }),
      signal: AbortSignal.timeout(8_000)
    });
    if (!fillsResponse.ok) throw new Error("exchange fill readback unavailable");
    const recentFills: unknown = await fillsResponse.json();
    if (!Array.isArray(recentFills)) throw new Error("exchange fill readback invalid");
    accounts.push({ accountId: candidate.accountId, masterAddress: candidate.masterAddress,
      signerFingerprint: digest({ address: candidate.agentAddress, name: candidate.agentName }),
      account, recentFills, plan: buildPlan(target, account, markets) });
  }
  const after = await checkpoint();
  if (before.sha256 !== after.sha256) throw new Error("journal changed while observing; retry a quiescent snapshot");
  const result = { observedAt: new Date().toISOString(), target, production,
    trendPermissionActive: production.trend_permission_active, markets: [...markets], accounts, preflight,
    journal: before, journalUnchanged: true, live_order_chain: "NOT_INVOKED", real_order_sent: false };
  await fs.writeFile(output, JSON.stringify(result, null, 2) + "\n", { mode: 0o600 });
  console.log(JSON.stringify({ target, accountCount: accounts.length,
    preflight: preflight.map(({status}) => status), plans: accounts.map(({plan}) => plan.state),
    journalUnchanged: true, live_order_chain: "NOT_INVOKED", real_order_sent: false }));
}
void main().catch(error => { console.error(String(error.message)); process.exitCode = 1; });
