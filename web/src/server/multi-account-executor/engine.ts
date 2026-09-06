import "server-only";

import { randomUUID } from "node:crypto";
import { createEnvironmentAgentSecretProtector, type EncryptedAgentSecret } from "@/lib/hyperliquid/agent-authorization";
import { deterministicCloid } from "./cloid";
import { assertAgentPrivateKeyMatches } from "./hyperliquid-l1-signing";
import { canWriteExchange } from "./mode";
import { buildPlan } from "./planner";
import type { AccountState, AuthorizedTarget, EligibleAccount, ExecutionMode, FinalStatus, MarketSpec, Plan, PlannedAction } from "./types";

export type ExchangeOrder = PlannedAction & { cloid: string; nonce: bigint; masterAddress: string; agentAddress: string; agentPrivateKey: `0x${string}` };
export type KnownOrder = { state: "filled" | "open" | "rejected" | "unknown"; orderId?: string } | null;
export interface ExchangeGateway {
  readAccount(masterAddress: string): Promise<AccountState>;
  readMarkets(): Promise<Map<"BTC" | "ETH", MarketSpec>>;
  userRole(agentAddress: string): Promise<{ role: string; user: string | null }>;
  agentAuthorization(masterAddress: string, agentAddress: string, agentName: string): Promise<{ authorized: boolean; validUntilMs: number | null }>;
  findByCloid(masterAddress: string, cloid: string): Promise<KnownOrder>;
  writeIoc(order: ExchangeOrder): Promise<{ orderId?: string }>;
}
export interface ExecutionRepository {
  listMultiAccountCandidates(): Promise<Array<EligibleAccount & { encryptedSecret?: EncryptedAgentSecret }>>;
  tryAcquire(accountId: string, holderId: string): Promise<boolean>;
  release(accountId: string, holderId: string): Promise<void>;
  reserveNonce(agentAddress: string): Promise<bigint>;
  createRun(account: EligibleAccount, target: AuthorizedTarget, equityBefore: number, status: FinalStatus): Promise<string>;
  recordAction(runId: string, action: PlannedAction, cloid: string, state: "NOT_SUBMITTED" | "KNOWN" | "SUBMITTED" | "AMBIGUOUS" | "REJECTED", orderId?: string): Promise<void>;
  finishRun(runId: string, status: FinalStatus, equityAfter: number | null, sanitizedError?: string): Promise<void>;
  setAccountStatus(authorizationId: string, status: "ready" | "disabled_by_user" | "blocked" | "executing" | "aligned" | "error"): Promise<void>;
}

export type AccountResult = { accountId: string; status: FinalStatus; reason?: string };

export function isEligibleMultiAccount(account: EligibleAccount): boolean {
  return account.connectionStatus === "read_only_connected" && account.authorizationStatus === "authorized" && Boolean(account.ownershipVerifiedAt) && Boolean(account.agentAuthorizedAt) && account.autoTradingRequested === true && (account.executionStatus === "ready" || account.executionStatus === "aligned" || account.executionStatus === "executing") && account.hasEncryptedSecret === true;
}

function sanitizedError(): string {
  return "Account execution could not be verified.";
}

function isAligned(plan: Plan): boolean {
  return plan.state === "NO_ACTION";
}

export class MultiAccountExecutor {
  constructor(private readonly repository: ExecutionRepository, private readonly exchange: ExchangeGateway, private readonly mode: ExecutionMode, private readonly maxConcurrency = 4) {}

  async runAllForTarget(target: AuthorizedTarget): Promise<AccountResult[]> {
    const accounts = await this.repository.listMultiAccountCandidates();
    const results = new Array<AccountResult>(accounts.length);
    let next = 0;
    const workers = Array.from({ length: Math.min(this.maxConcurrency, accounts.length) }, async () => {
      while (next < accounts.length) {
        const index = next++;
        results[index] = await this.runOne(accounts[index], target);
      }
    });
    await Promise.all(workers);
    return results;
  }

  private async runOne(account: EligibleAccount & { encryptedSecret?: EncryptedAgentSecret }, target: AuthorizedTarget): Promise<AccountResult> {
    if (!isEligibleMultiAccount(account)) return { accountId: account.accountId, status: "BLOCKED", reason: "account is not eligible" };
    if (this.mode === "disabled") return { accountId: account.accountId, status: "DISABLED", reason: "global executor is disabled" };
    const holderId = randomUUID();
    let runId: string | null = null;
    let lockHeld = false;
    try {
      if (!await this.repository.tryAcquire(account.accountId, holderId)) return { accountId: account.accountId, status: "BLOCKED", reason: "account is already executing" };
      lockHeld = true;
      const [role, authorization] = await Promise.all([
        this.exchange.userRole(account.agentAddress),
        this.exchange.agentAuthorization(account.masterAddress, account.agentAddress, account.agentName)
      ]);
      if (role.role !== "agent" || role.user?.toLowerCase() !== account.masterAddress.toLowerCase()) {
        await this.repository.setAccountStatus(account.authorizationId, "blocked");
        return { accountId: account.accountId, status: "BLOCKED", reason: "agent binding is invalid" };
      }
      if (!authorization.authorized || authorization.validUntilMs === null || authorization.validUntilMs <= Date.now()) {
        await this.repository.setAccountStatus(account.authorizationId, "blocked");
        return { accountId: account.accountId, status: "BLOCKED", reason: "agent authorization is missing or expired" };
      }
      const [before, markets] = await Promise.all([this.exchange.readAccount(account.masterAddress), this.exchange.readMarkets()]);
      const plan = buildPlan(target, before, markets);
      runId = await this.repository.createRun(account, target, before.equityUsd, plan.state === "BLOCKED" ? "BLOCKED" : this.mode === "dry_run" ? "DRY_RUN" : "NO_ACTION");
      if (plan.state === "BLOCKED") {
        await this.repository.setAccountStatus(account.authorizationId, "blocked");
        await this.repository.finishRun(runId, "BLOCKED", before.equityUsd, plan.reason);
        return { accountId: account.accountId, status: "BLOCKED", reason: plan.reason };
      }
      if (this.mode === "dry_run") {
        for (const action of plan.actions) {
          const cloid = deterministicCloid({
            userId: account.userId,
            accountId: account.accountId,
            signalId: target.signalId,
            closedDay: target.closedDay,
            target: target.asset,
            action: action.action,
            leg: action.leg,
            attempt: 0
          });
          await this.repository.recordAction(runId, action, cloid, "NOT_SUBMITTED");
        }
        await this.repository.finishRun(runId, "DRY_RUN", before.equityUsd);
        return { accountId: account.accountId, status: "DRY_RUN" };
      }
      if (!canWriteExchange(this.mode) || !account.encryptedSecret) throw new Error("secret is unavailable");
      const secret = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).decrypt(account.encryptedSecret);
      assertAgentPrivateKeyMatches(secret, account.agentAddress);
      await this.repository.setAccountStatus(account.authorizationId, "executing");
      for (const action of plan.actions) {
        const cloid = deterministicCloid({ userId: account.userId, accountId: account.accountId, signalId: target.signalId, closedDay: target.closedDay, target: target.asset, action: action.action, leg: action.leg, attempt: 0 });
        await this.repository.recordAction(runId, action, cloid, "NOT_SUBMITTED");
        const known = await this.exchange.findByCloid(account.masterAddress, cloid);
        if (known?.state === "open" || known?.state === "unknown") {
          await this.repository.recordAction(runId, action, cloid, "AMBIGUOUS", known.orderId);
          await this.repository.finishRun(runId, "UNKNOWN_SUBMISSION_STATE", null);
          return { accountId: account.accountId, status: "UNKNOWN_SUBMISSION_STATE" };
        }
        if (known?.state === "rejected") {
          await this.repository.recordAction(runId, action, cloid, "REJECTED", known.orderId);
          await this.repository.finishRun(runId, "FAILED", null);
          return { accountId: account.accountId, status: "FAILED" };
        }
        if (!known) {
          const nonce = await this.repository.reserveNonce(account.agentAddress);
          try {
            const response = await this.exchange.writeIoc({ ...action, cloid, nonce, masterAddress: account.masterAddress, agentAddress: account.agentAddress, agentPrivateKey: secret });
            await this.repository.recordAction(runId, action, cloid, "SUBMITTED", response.orderId);
          } catch {
            let recovered: KnownOrder = { state: "unknown" };
            try {
              recovered = await this.exchange.findByCloid(account.masterAddress, cloid);
            } catch {
              // An unverified post-submit lookup is ambiguous and must never trigger a retry.
            }
            await this.repository.recordAction(runId, action, cloid, recovered?.state === "filled" ? "KNOWN" : "AMBIGUOUS", recovered?.orderId);
            await this.repository.finishRun(runId, recovered?.state === "filled" ? "PARTIAL" : "UNKNOWN_SUBMISSION_STATE", null);
            return { accountId: account.accountId, status: recovered?.state === "filled" ? "PARTIAL" : "UNKNOWN_SUBMISSION_STATE" };
          }
        } else {
          await this.repository.recordAction(runId, action, cloid, "KNOWN", known.orderId);
        }
        const afterLeg = await this.exchange.readAccount(account.masterAddress);
        if (action.action === "EXIT" && afterLeg.positions.some((position) => position.asset === action.asset && position.size !== 0)) {
          await this.repository.finishRun(runId, "PARTIAL", afterLeg.equityUsd);
          return { accountId: account.accountId, status: "PARTIAL" };
        }
      }
      const after = await this.exchange.readAccount(account.masterAddress);
      const finalPlan = buildPlan(target, after, markets);
      if (!isAligned(finalPlan) || after.openOrderCount !== 0) {
        await this.repository.setAccountStatus(account.authorizationId, "error");
        await this.repository.finishRun(runId, "PARTIAL", after.equityUsd);
        return { accountId: account.accountId, status: "PARTIAL" };
      }
      await this.repository.setAccountStatus(account.authorizationId, "aligned");
      await this.repository.finishRun(runId, plan.actions.length === 0 ? "NO_ACTION" : "FILLED_AND_ALIGNED", after.equityUsd);
      return { accountId: account.accountId, status: plan.actions.length === 0 ? "NO_ACTION" : "FILLED_AND_ALIGNED" };
    } catch {
      if (runId) {
        try {
          await this.repository.finishRun(runId, "FAILED", null, sanitizedError());
        } catch {
          // The account result remains isolated even when its journal is unavailable.
        }
      }
      try {
        await this.repository.setAccountStatus(account.authorizationId, "error");
      } catch {
        // The account result remains isolated even when its status update is unavailable.
      }
      return { accountId: account.accountId, status: "FAILED", reason: sanitizedError() };
    } finally {
      if (lockHeld) {
        try {
          await this.repository.release(account.accountId, holderId);
        } catch {
          // The database lease remains bounded; never let cleanup reject other accounts.
        }
      }
    }
  }
}
