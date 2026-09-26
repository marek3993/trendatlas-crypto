import "server-only";

import { randomUUID } from "node:crypto";
import { createEnvironmentAgentSecretProtector, type EncryptedAgentSecret } from "@/lib/hyperliquid/agent-authorization";
import { deterministicCloid } from "./cloid";
import { assertAgentPrivateKeyMatches, HYPERLIQUID_ORDER_EXPIRY_MS, HYPERLIQUID_EXPIRY_READBACK_SKEW_MS } from "./hyperliquid-l1-signing";
import { canWriteExchange } from "./mode";
import { buildPlan, validTarget } from "./planner";
import type { AccountState, AuthorizedTarget, EligibleAccount, ExecutionMode, FinalStatus, MarketSpec, OpenOrder, PlannedAction } from "./types";

export type ExchangeOrder = PlannedAction & { cloid: string; nonce: bigint; expiresAtMs: number; masterAddress: string; agentAddress: string; agentPrivateKey: `0x${string}` };
export type ExchangeCancellation = OpenOrder & { nonce: bigint; masterAddress: string; agentAddress: string; agentPrivateKey: `0x${string}` };
export type KnownOrder = { state: "filled" | "open" | "rejected" | "cancelled" | "unknown"; orderId?: string } | null;
export type SubmissionState = "NOT_SUBMITTED" | "KNOWN" | "SUBMITTED" | "AMBIGUOUS" | "REJECTED";
export type JournalAction = { action: PlannedAction; cloid: string; state: SubmissionState; orderId?: string; runId?: string; expiresAtMs?: number };
export interface ExchangeGateway {
  readAccount(masterAddress: string): Promise<AccountState>;
  readMarkets(): Promise<Map<string, MarketSpec>>;
  userRole(agentAddress: string): Promise<{ role: string; user: string | null }>;
  agentAuthorization(masterAddress: string, agentAddress: string, agentName: string): Promise<{ authorized: boolean; validUntilMs: number | null }>;
  findByCloid(masterAddress: string, cloid: string): Promise<KnownOrder>;
  writeIoc(order: ExchangeOrder): Promise<{ orderId?: string }>;
  cancelOrder?(order: ExchangeCancellation): Promise<void>;
}
export interface ExecutionRepository {
  listMultiAccountCandidates(): Promise<Array<EligibleAccount & { encryptedSecret?: EncryptedAgentSecret }>>;
  tryAcquire(accountId: string, holderId: string): Promise<boolean>;
  renewLease?(accountId: string, holderId: string): Promise<boolean>;
  release(accountId: string, holderId: string): Promise<void>;
  reserveNonce(agentAddress: string): Promise<bigint>;
  createRun(account: EligibleAccount, target: AuthorizedTarget, equityBefore: number | null, status: FinalStatus): Promise<string>;
  readActions?(runId: string): Promise<JournalAction[]>;
  readUnresolvedActions?(accountId: string): Promise<JournalAction[]>;
  markActionVerified?(cloid: string): Promise<void>;
  isManagedOrder?(accountId: string, cloid?: string, orderId?: string): Promise<boolean>;
  recordAction(runId: string, action: PlannedAction, cloid: string, state: SubmissionState, orderId?: string, expiresAtMs?: number): Promise<void>;
  finishRun(runId: string, status: FinalStatus, equityAfter: number | null, sanitizedError?: string): Promise<void>;
  setAccountStatus(authorizationId: string, status: "ready" | "disabled_by_user" | "blocked" | "executing" | "aligned" | "error"): Promise<void>;
}

export type AccountResult = { accountId: string; status: FinalStatus; orderRequested: boolean | null; failureKind?: "retryable" | "deterministic"; reason?: string };
const flat = (account: AccountState) => account.positions.every(({ size }) => size === 0);
const sameAction = (a: PlannedAction, b: PlannedAction) => a.action === b.action && a.asset === b.asset && (a.side ?? (a.reduceOnly ? "sell" : "buy")) === b.side;

export function isEligibleMultiAccount(account: EligibleAccount): boolean {
  return account.connectionStatus === "read_only_connected" && account.authorizationStatus === "authorized" && Boolean(account.ownershipVerifiedAt) && Boolean(account.agentAuthorizedAt) && account.autoTradingRequested === true && account.executionStatus !== "disabled_by_user" && account.executionStatus !== "pending_multi_account_executor" && account.hasEncryptedSecret === true;
}

export class MultiAccountExecutor {
  constructor(private readonly repository: ExecutionRepository, private readonly exchange: ExchangeGateway, private readonly mode: ExecutionMode, private readonly maxConcurrency = 1) {}

  async runAllForTarget(target: AuthorizedTarget): Promise<AccountResult[]> {
    if (!validTarget(target)) throw new Error("shared strategy target is invalid");
    const accounts = await this.repository.listMultiAccountCandidates();
    const results = new Array<AccountResult>(accounts.length);
    let next = 0;
    const workers = Array.from({ length: Math.min(Math.max(1, this.maxConcurrency), accounts.length) }, async () => {
      while (next < accounts.length) {
        const index = next++;
        results[index] = await this.runOne(accounts[index], target);
      }
    });
    await Promise.all(workers);
    return results;
  }

  private async runOne(account: EligibleAccount & { encryptedSecret?: EncryptedAgentSecret }, target: AuthorizedTarget): Promise<AccountResult> {
    let orderRequested: boolean | null = false;
    const result = (status: FinalStatus, reason?: string, failureKind?: AccountResult["failureKind"]): AccountResult => ({ accountId: account.accountId, status, orderRequested, ...(reason ? { reason } : {}), ...(failureKind ? { failureKind } : {}) });
    if (!isEligibleMultiAccount(account)) return result("BLOCKED", "account is not eligible", "deterministic");
    if (this.mode === "disabled") return result("DISABLED", "global executor is disabled");
    const holderId = randomUUID();
    let runId: string | null = null;
    let lockHeld = false;
    let state: AccountState | null = null;
    let exited = false;
    let unresolvedRequest = false;
    const finish = async (status: FinalStatus, reason?: string, failureKind?: AccountResult["failureKind"]): Promise<AccountResult> => {
      if (runId) await this.repository.finishRun(runId, status, state?.equityUsd ?? null, reason);
      await this.repository.setAccountStatus(account.authorizationId, status === "NO_ACTION" || status === "FILLED_AND_ALIGNED" ? "aligned" : status === "DRY_RUN" ? "ready" : failureKind === "deterministic" ? "blocked" : "error");
      return result(status, reason, failureKind);
    };
    const entryFailure = (reason: string) => finish(state && flat(state) ? exited ? "EXITED_ENTRY_FAILED_STAYING_CASH" : "ENTRY_FAILED_STAYING_CASH" : "PARTIAL", reason, "deterministic");
    try {
      if (!await this.repository.tryAcquire(account.accountId, holderId)) return result("BLOCKED", "account is already executing", "retryable");
      lockHeld = true;
      const [role, authorization] = await Promise.all([this.exchange.userRole(account.agentAddress), this.exchange.agentAuthorization(account.masterAddress, account.agentAddress, account.agentName)]);
      if (role.role !== "agent" || role.user?.toLowerCase() !== account.masterAddress.toLowerCase()) return await finish("BLOCKED", "agent binding is invalid", "deterministic");
      if (!authorization.authorized || authorization.validUntilMs === null || authorization.validUntilMs <= Date.now()) return await finish("BLOCKED", "agent authorization is missing or expired", "deterministic");
      state = await this.exchange.readAccount(account.masterAddress);
      let markets = await this.exchange.readMarkets();
      runId = await this.repository.createRun(account, target, state.equityUsd, this.mode === "dry_run" ? "DRY_RUN" : "NO_ACTION");
      if (this.mode === "dry_run") {
        const preview = buildPlan(target, state, markets);
        if (preview.state === "BLOCKED") return await finish("BLOCKED", preview.reason, "deterministic");
        for (const action of preview.actions) {
          const cloid = deterministicCloid({ userId: account.userId, accountId: account.accountId, signalId: target.signalId, closedDay: target.closedDay, target: target.asset, action: action.action, asset: action.asset, side: action.side, leg: action.leg, attempt: 0 });
          await this.repository.recordAction(runId, action, cloid, "NOT_SUBMITTED");
        }
        return await finish("DRY_RUN");
      }
      if (!canWriteExchange(this.mode) || !account.encryptedSecret) return await finish("BLOCKED", "signer secret is unavailable", "deterministic");
      const secret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).decrypt(account.encryptedSecret);
      assertAgentPrivateKeyMatches(secret, account.agentAddress);
      if (!this.repository.readActions || !this.repository.renewLease || !this.repository.readUnresolvedActions || !this.repository.markActionVerified) throw new Error("durable recovery is unavailable");
      const journal = await this.repository.readActions(runId);
      const unresolved = await this.repository.readUnresolvedActions(account.accountId);
      const recovery = [...new Map([...journal, ...unresolved].map((entry) => [entry.cloid, entry])).values()];
      const restingRequests: JournalAction[] = [];
      await this.repository.setAccountStatus(account.authorizationId, "executing");
      const renew = async () => {
        if (!await this.repository.renewLease!(account.accountId, holderId)) throw new Error("account lease was lost");
      };
      // Recover every historical request before deriving any residual order.
      for (const entry of recovery) {
        if (entry.action.action === "CANCEL") {
          state = await this.exchange.readAccount(account.masterAddress);
          if (state.openOrders && !state.openOrders.some(({ orderId }) => orderId === entry.orderId)) await this.repository.markActionVerified(entry.cloid);
          continue;
        }
        const known = await this.exchange.findByCloid(account.masterAddress, entry.cloid);
        state = await this.exchange.readAccount(account.masterAddress);
        if (!known && entry.state === "NOT_SUBMITTED") continue;
        // Legacy journals without a durable signed expiry never qualify.
        if (!known && Number.isSafeInteger(entry.expiresAtMs) && Date.now() > entry.expiresAtMs! + HYPERLIQUID_EXPIRY_READBACK_SKEW_MS && state.openOrderCount === 0) {
          await this.repository.markActionVerified(entry.cloid);
          continue;
        }
        if (!known || known.state === "unknown") {
          orderRequested = entry.state === "NOT_SUBMITTED" ? false : null;
          return await finish("UNKNOWN_SUBMISSION_STATE", "prior request could not be verified", "retryable");
        }
        if (known.state === "open") { restingRequests.push(entry); continue; }
        entry.state = known.state === "filled" ? "KNOWN" : "REJECTED";
        await this.repository.recordAction(entry.runId ?? runId, entry.action, entry.cloid, entry.state, known.orderId);
        await this.repository.markActionVerified(entry.cloid);
        if (entry.action.action === "EXIT" && known.state === "filled" && !state.positions.some(({ asset, size }) => asset === entry.action.asset && size !== 0)) exited = true;
      }
      // Only journal-owned orders can be cancelled. An unrelated order isolates this account.
      if (state.openOrderCount !== 0) {
        const openOrders = state.openOrders;
        if (!openOrders || openOrders.length !== state.openOrderCount || !this.exchange.cancelOrder || !this.repository.isManagedOrder) return await finish("BLOCKED", "open order ownership is unavailable", "deterministic");
        for (const open of openOrders) {
          if (!markets.has(open.asset) || !await this.repository.isManagedOrder(account.accountId, open.cloid, open.orderId)) return await finish("BLOCKED", "an open order is outside automatic execution ownership", "deterministic");
        }
        for (const open of openOrders) {
          await renew();
          const action: PlannedAction = { action: "CANCEL", asset: open.asset, requestedNotionalUsd: 0, size: open.size ?? 0, reduceOnly: false, side: open.side, leg: journal.length };
          const cloid = deterministicCloid({ userId: account.userId, accountId: account.accountId, signalId: target.signalId, closedDay: target.closedDay, target: target.asset, action: "CANCEL", asset: open.asset, side: open.side, orderId: open.orderId, leg: 0, attempt: 0 });
          await this.repository.recordAction(runId, action, cloid, "NOT_SUBMITTED", open.orderId);
          await this.repository.recordAction(runId, action, cloid, "AMBIGUOUS", open.orderId);
          try {
            await this.exchange.cancelOrder({ ...open, nonce: await this.repository.reserveNonce(account.agentAddress), masterAddress: account.masterAddress, agentAddress: account.agentAddress, agentPrivateKey: secret });
          } catch {
            // A cancellation timeout is resolved only by fresh exchange state.
          }
          state = await this.exchange.readAccount(account.masterAddress);
          if (!state.openOrders || state.openOrders.some(({ orderId }) => orderId === open.orderId)) return await finish("UNKNOWN_SUBMISSION_STATE", "order cancellation could not be verified", "retryable");
          await this.repository.recordAction(runId, action, cloid, "KNOWN", open.orderId);
          await this.repository.markActionVerified(cloid);
        }
        if (state.openOrderCount !== 0) return await finish("BLOCKED", "conflicting orders remain", "retryable");
      }
      // A stale empty openOrders response must not overrule a still-open CLOID.
      for (const entry of restingRequests) {
        const known = await this.exchange.findByCloid(account.masterAddress, entry.cloid);
        state = await this.exchange.readAccount(account.masterAddress);
        if (!known || known.state === "open" || known.state === "unknown") return await finish("UNKNOWN_SUBMISSION_STATE", "resting request is not terminal", "retryable");
        await this.repository.recordAction(entry.runId ?? runId, entry.action, entry.cloid, known.state === "filled" ? "KNOWN" : "REJECTED", known.orderId);
        await this.repository.markActionVerified(entry.cloid);
      }
      const maximumSteps = state.positions.length + 4;
      for (let step = 0; step < maximumSteps; step++) {
        await renew();
        markets = await this.exchange.readMarkets();
        const plan = buildPlan(target, state, markets);
        if (plan.state === "NO_ACTION") return await finish(orderRequested || exited ? "FILLED_AND_ALIGNED" : "NO_ACTION");
        if (plan.state === "BLOCKED" || plan.actions.length === 0) return state && flat(state) && target.asset !== "CASH" ? await entryFailure(plan.reason ?? "entry is unavailable") : await finish("BLOCKED", plan.reason, "deterministic");
        // Replan after every step. Never use the prospective ENTRY from an EXIT plan.
        const planned = plan.actions[0];
        const prior = journal.filter(({ action }) => sameAction(action, planned));
        const prepared = prior.find(({ state: submission }) => submission === "NOT_SUBMITTED");
        const attempt = prior.filter(({ state: submission }) => submission !== "NOT_SUBMITTED").length;
        if (attempt >= 3) return await finish("PARTIAL", "bounded reconciliation attempts exhausted", "deterministic");
        const action = { ...planned, leg: prepared?.action.leg ?? journal.length };
        const cloid = prepared?.cloid ?? deterministicCloid({ userId: account.userId, accountId: account.accountId, signalId: target.signalId, closedDay: target.closedDay, target: target.asset, action: action.action, asset: action.asset, side: action.side, leg: action.leg, attempt });
        await this.repository.recordAction(runId, action, cloid, "NOT_SUBMITTED");
        const known = await this.exchange.findByCloid(account.masterAddress, cloid);
        if (known?.state === "open" || known?.state === "unknown") {
          state = await this.exchange.readAccount(account.masterAddress);
          return await finish("UNKNOWN_SUBMISSION_STATE", "request state is ambiguous", "retryable");
        }
        if (known?.state === "rejected" || known?.state === "cancelled") {
          state = await this.exchange.readAccount(account.masterAddress);
          await this.repository.recordAction(runId, action, cloid, "REJECTED", known.orderId);
          return !action.reduceOnly ? await entryFailure("entry was rejected by the exchange") : await finish("PARTIAL", "exit was rejected by the exchange", "deterministic");
        }
        if (!known) {
          const nonce = await this.repository.reserveNonce(account.agentAddress);
          const expiresAtMs = Number(nonce + BigInt(HYPERLIQUID_ORDER_EXPIRY_MS));
          if (!Number.isSafeInteger(expiresAtMs)) throw new Error("order expiry is invalid");
          // This durable boundary also covers power loss after sending but before receiving.
          await this.repository.recordAction(runId, action, cloid, "AMBIGUOUS", undefined, expiresAtMs);
          orderRequested = true;
          unresolvedRequest = true;
          try {
            const response = await this.exchange.writeIoc({ ...action, cloid, nonce, expiresAtMs, masterAddress: account.masterAddress, agentAddress: account.agentAddress, agentPrivateKey: secret });
            await this.repository.recordAction(runId, action, cloid, "SUBMITTED", response.orderId);
          } catch (error) {
            let recovered: KnownOrder = { state: "unknown" };
            try { recovered = await this.exchange.findByCloid(account.masterAddress, cloid); } catch { /* unresolved transport is ambiguous */ }
            if (!recovered && error !== null && typeof error === "object" && "definiteRejection" in error && error.definiteRejection === true) recovered = { state: "rejected" };
            state = await this.exchange.readAccount(account.masterAddress);
            await this.repository.recordAction(runId, action, cloid, recovered?.state === "filled" ? "KNOWN" : recovered?.state === "rejected" || recovered?.state === "cancelled" ? "REJECTED" : "AMBIGUOUS", recovered?.orderId);
            if (recovered?.state !== "filled") {
              if (recovered?.state === "rejected" || recovered?.state === "cancelled") {
                unresolvedRequest = false;
                await this.repository.markActionVerified(cloid);
                return !action.reduceOnly ? await entryFailure("entry was rejected by the exchange") : await finish("PARTIAL", "exit was rejected by the exchange", "deterministic");
              }
              return await finish("UNKNOWN_SUBMISSION_STATE", "submission could not be verified", "retryable");
            }
          }
        } else {
          await this.repository.recordAction(runId, action, cloid, "KNOWN", known.orderId);
        }
        state = await this.exchange.readAccount(account.masterAddress);
        unresolvedRequest = false;
        journal.push({ action, cloid, state: "KNOWN" });
        await this.repository.markActionVerified(cloid);
        if (action.action === "EXIT") {
          if (state.positions.some(({ asset, size }) => asset === action.asset && size !== 0)) return await finish("PARTIAL", "exit is not fully filled", "retryable");
          exited = true;
        }
      }
      return await finish("PARTIAL", "reconciliation did not converge", "deterministic");
    } catch {
      const failureStatus: FinalStatus = exited && state && flat(state) && !unresolvedRequest ? "EXITED_ENTRY_FAILED_STAYING_CASH" : unresolvedRequest ? "UNKNOWN_SUBMISSION_STATE" : "FAILED";
      if (runId) {
        try { await this.repository.finishRun(runId, failureStatus, state?.equityUsd ?? null, "Account execution could not be verified."); } catch { /* Preserve isolated account result when persistence fails. */ }
      }
      try { await this.repository.setAccountStatus(account.authorizationId, "error"); } catch { /* Lease remains bounded. */ }
      return result(failureStatus, "Account execution could not be verified.", "retryable");
    } finally {
      if (lockHeld) {
        try { await this.repository.release(account.accountId, holderId); } catch { /* Never reject independent accounts during cleanup. */ }
      }
    }
  }
}
