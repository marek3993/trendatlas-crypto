import "server-only";

import { createAdminClient } from "@/lib/supabase/admin";
import type { EncryptedAgentSecret } from "@/lib/hyperliquid/agent-authorization";
import type { AuthorizedTarget, EligibleAccount, FinalStatus, PlannedAction } from "./types";
import type { ExecutionRepository } from "./engine";

type CandidateRow = {
  id: string; user_id: string; hyperliquid_account_id: string; agent_address: string;
  authorization_status: string; ownership_verified_at: string | null; agent_authorized_at: string | null;
  auto_trading_requested: boolean; execution_status: EligibleAccount["executionStatus"];
  hyperliquid_accounts: { id: string; master_address: string; connection_status: "read_only_connected" } | null;
  hyperliquid_agent_secrets: { encrypted_private_key: string; encryption_nonce: string; encryption_key_version: string } | null;
};

export class SupabaseExecutionRepository implements ExecutionRepository {
  private readonly db = createAdminClient();

  async listMultiAccountCandidates(): Promise<Array<EligibleAccount & { encryptedSecret?: EncryptedAgentSecret }>> {
    const { data, error } = await this.db.from("hyperliquid_agent_authorizations")
      .select("id,user_id,hyperliquid_account_id,agent_address,authorization_status,ownership_verified_at,agent_authorized_at,auto_trading_requested,execution_status,hyperliquid_accounts!inner(id,master_address,connection_status),hyperliquid_agent_secrets(encrypted_private_key,encryption_nonce,encryption_key_version)")
      .eq("authorization_status", "authorized");
    if (error) throw new Error("eligible accounts are unavailable");
    return ((data ?? []) as unknown as CandidateRow[]).flatMap((row) => {
      const account = row.hyperliquid_accounts;
      const secret = row.hyperliquid_agent_secrets;
      if (!account) return [];
      return [{ userId: row.user_id, accountId: account.id, masterAddress: account.master_address, agentAddress: row.agent_address, authorizationId: row.id, connectionStatus: account.connection_status, authorizationStatus: row.authorization_status, ownershipVerifiedAt: row.ownership_verified_at, agentAuthorizedAt: row.agent_authorized_at, autoTradingRequested: row.auto_trading_requested, executionStatus: row.execution_status, hasEncryptedSecret: Boolean(secret), encryptedSecret: secret ? { encryptedPrivateKey: secret.encrypted_private_key, encryptionNonce: secret.encryption_nonce, encryptionKeyVersion: secret.encryption_key_version } : undefined }];
    });
  }

  async tryAcquire(accountId: string, holderId: string): Promise<boolean> {
    const { data, error } = await this.db.rpc("try_acquire_multi_account_execution_lock", { expected_account_id: accountId, expected_holder_id: holderId, lease_seconds: 120 });
    if (error) throw new Error("account lock is unavailable");
    return data === true;
  }
  async release(accountId: string, holderId: string): Promise<void> {
    await this.db.rpc("release_multi_account_execution_lock", { expected_account_id: accountId, expected_holder_id: holderId });
  }
  async reserveNonce(agentAddress: string): Promise<bigint> {
    const { data, error } = await this.db.rpc("reserve_multi_account_agent_nonce", { expected_agent_address: agentAddress });
    if (error || (typeof data !== "number" && typeof data !== "string")) throw new Error("agent nonce is unavailable");
    return BigInt(data);
  }
  async createRun(account: EligibleAccount, target: AuthorizedTarget, equityBefore: number, status: FinalStatus): Promise<string> {
    const existing = await this.db.from("multi_account_execution_runs").select("id").eq("hyperliquid_account_id", account.accountId).eq("canonical_signal_id", target.signalId).maybeSingle<{ id: string }>();
    if (existing.error) throw new Error("execution run cannot be recovered");
    if (existing.data) return existing.data.id;
    const { data, error } = await this.db.from("multi_account_execution_runs").insert({ user_id: account.userId, hyperliquid_account_id: account.accountId, canonical_signal_id: target.signalId, canonical_closed_day: target.closedDay, strategy_version: target.strategyVersion, authorized_target_asset: target.asset, authorized_target_exposure: target.exposure, account_equity_before: equityBefore, status }).select("id").single<{ id: string }>();
    if (error || !data) throw new Error("execution run cannot be recorded");
    return data.id;
  }
  async recordAction(runId: string, action: PlannedAction, cloid: string, submissionState: "NOT_SUBMITTED" | "KNOWN" | "SUBMITTED" | "AMBIGUOUS" | "REJECTED", orderId?: string): Promise<void> {
    const { error } = await this.db.from("multi_account_execution_actions").upsert({ run_id: runId, leg_index: action.leg, action: action.action, asset: action.asset, requested_notional: action.requestedNotionalUsd, size: action.size, reduce_only: action.reduceOnly, cloid, hyperliquid_order_id: orderId ?? null, submission_state: submissionState, verification_state: "PENDING", updated_at: new Date().toISOString() }, { onConflict: "cloid" });
    if (error) throw new Error("execution action cannot be recorded");
  }
  async finishRun(runId: string, status: FinalStatus, equityAfter: number | null, sanitizedError?: string): Promise<void> {
    const { error } = await this.db.from("multi_account_execution_runs").update({ status, account_equity_after: equityAfter, sanitized_error: sanitizedError ?? null, completed_at: new Date().toISOString() }).eq("id", runId);
    if (error) throw new Error("execution run cannot be finalized");
  }
  async setAccountStatus(authorizationId: string, status: "ready" | "disabled_by_user" | "blocked" | "executing" | "aligned" | "error"): Promise<void> {
    const { error } = await this.db.from("hyperliquid_agent_authorizations").update({ execution_status: status }).eq("id", authorizationId);
    if (error) throw new Error("account status cannot be updated");
  }
}
