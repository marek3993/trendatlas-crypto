import "server-only";

import { createEnvironmentAgentSecretProtector, type EncryptedAgentSecret } from "@/lib/hyperliquid/agent-authorization";
import { loadAuthorizedTarget } from "./authority";
import type { ExchangeGateway, ExecutionRepository } from "./engine";
import { isEligibleMultiAccount } from "./engine";
import { assertAgentPrivateKeyMatches, HYPERLIQUID_EXPIRY_READBACK_SKEW_MS } from "./hyperliquid-l1-signing";
import { buildPlan, validTarget } from "./planner";
import type { AccountState, AuthorizedTarget, EligibleAccount, PlannedAction, Position } from "./types";

export type LivePreflightResult = {
  accountId: string;
  status: "READY" | "ALIGNED" | "ENTRY_BLOCKED" | "BLOCKED" | "FAILED";
  actionCount: number;
  maxActionNotionalUsd: number;
  reason?: string;
  failureKind?: "retryable" | "deterministic";
  targetAsset?: string;
  targetExposure?: number;
  accountEquityUsd?: number;
  positions?: Position[];
  actions?: PlannedAction[];
  cancelOrderIds?: string[];
  entryBlockedReason?: string;
};

type Candidate = EligibleAccount & { encryptedSecret?: EncryptedAgentSecret };
type PreflightRepository = Pick<ExecutionRepository, "isManagedOrder" | "readUnresolvedActions">;

async function preflightOne(candidate: Candidate, target: AuthorizedTarget, exchange: ExchangeGateway, repository?: PreflightRepository): Promise<LivePreflightResult> {
  let account: AccountState | undefined;
  const failure = (reason: string, kind: "retryable" | "deterministic" = "deterministic"): LivePreflightResult => ({
    accountId: candidate.accountId, status: kind === "retryable" ? "FAILED" : "BLOCKED", actionCount: 0, maxActionNotionalUsd: 0,
    reason, failureKind: kind, targetAsset: target.asset, targetExposure: target.exposure,
    ...(account ? { accountEquityUsd: account.equityUsd, positions: account.positions } : {})
  });
  if (!validTarget(target)) return failure("strategy target is invalid");
  if (!isEligibleMultiAccount(candidate) || !candidate.encryptedSecret) return failure("account is not eligible");
  try {
    const privateKey = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).decrypt(candidate.encryptedSecret);
    assertAgentPrivateKeyMatches(privateKey, candidate.agentAddress);
  } catch { return failure("signer secret is missing or invalid"); }
  try {
    const [role, authorization, initialAccount, markets] = await Promise.all([
      exchange.userRole(candidate.agentAddress),
      exchange.agentAuthorization(candidate.masterAddress, candidate.agentAddress, candidate.agentName),
      exchange.readAccount(candidate.masterAddress), exchange.readMarkets()
    ]);
    account = initialAccount;
    if (role.role !== "agent" || role.user?.toLowerCase() !== candidate.masterAddress.toLowerCase()) return failure("agent binding is invalid");
    if (!authorization.authorized || authorization.validUntilMs === null || authorization.validUntilMs <= Date.now()) return failure("agent authorization is missing or expired");
    const restingOrderIds: string[] = [];
    for (const entry of await repository?.readUnresolvedActions?.(candidate.accountId) ?? []) {
      if (entry.action.action === "CANCEL") continue;
      const known = await exchange.findByCloid(candidate.masterAddress, entry.cloid);
      account = await exchange.readAccount(candidate.masterAddress);
      const expiredAndAbsent = !known && Number.isSafeInteger(entry.expiresAtMs) && Date.now() > entry.expiresAtMs! + HYPERLIQUID_EXPIRY_READBACK_SKEW_MS && account.openOrderCount === 0;
      if (expiredAndAbsent) continue;
      if (!known || known.state === "unknown") return failure("a prior order cannot yet be verified", "retryable");
      if (known.state === "open") {
        if (!known.orderId) return failure("a prior resting order has no verifiable identity", "retryable");
        restingOrderIds.push(known.orderId);
      }
    }
    const orders = account.openOrders ?? [];
    if (account.openOrderCount !== orders.length || restingOrderIds.some((id) => !orders.some(({ orderId }) => orderId === id))) return failure("open order details are incomplete", "retryable");
    for (const order of orders) {
      if (!markets.has(order.asset)) return failure("an open order market is unavailable");
      if (!await repository?.isManagedOrder?.(candidate.accountId, order.cloid, order.orderId)) return failure("open order ownership cannot be verified");
    }
    if (!Number.isFinite(account.equityUsd) || !Array.isArray(account.positions) || account.positions.some(({ size, markPrice }) => !Number.isFinite(size) || !Number.isFinite(markPrice) || markPrice <= 0)) return failure("account state is ambiguous", "retryable");
    const plan = buildPlan(target, { ...account, openOrderCount: 0, openOrders: [] }, markets);
    const entryBlocked = plan.state === "BLOCKED" && target.asset !== "CASH" && account.positions.every(({ size }) => size === 0);
    if (plan.state === "BLOCKED" && !entryBlocked) return failure(plan.reason ?? "account cannot be reconciled");
    return {
      accountId: candidate.accountId,
      status: entryBlocked ? "ENTRY_BLOCKED" : plan.actions.length === 0 && orders.length === 0 ? "ALIGNED" : "READY",
      actionCount: plan.actions.length,
      maxActionNotionalUsd: Math.max(0, ...plan.actions.map(({ requestedNotionalUsd }) => requestedNotionalUsd)),
      targetAsset: target.asset, targetExposure: target.exposure, accountEquityUsd: account.equityUsd,
      positions: account.positions, actions: plan.actions, cancelOrderIds: orders.map(({ orderId }) => orderId),
      entryBlockedReason: entryBlocked ? plan.reason : plan.entryBlockedReason,
      ...(entryBlocked ? { reason: plan.reason, failureKind: "deterministic" as const } : {})
    };
  } catch { return failure("live preflight could not be verified", "retryable"); }
}

export async function preflightMultiAccountCandidates(candidates: Candidate[], target: AuthorizedTarget, exchange: ExchangeGateway, repository?: PreflightRepository): Promise<LivePreflightResult[]> {
  return Promise.all(candidates.map((candidate) => preflightOne(candidate, target, exchange, repository)));
}

/** Account, signer, ownership and CLOID checks are Info-only; no exchange mutation exists here. */
export async function runMultiAccountLivePreflight(repositoryRoot: string, repository: Pick<ExecutionRepository, "listMultiAccountCandidates" | "isManagedOrder" | "readUnresolvedActions">, exchange: ExchangeGateway): Promise<{ target: string; results: LivePreflightResult[] }> {
  const [target, candidates] = await Promise.all([loadAuthorizedTarget(repositoryRoot), repository.listMultiAccountCandidates()]);
  const results = await preflightMultiAccountCandidates(candidates, target, exchange, repository);
  return { target: target.asset, results };
}
