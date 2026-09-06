import "server-only";

import { createEnvironmentAgentSecretProtector, type EncryptedAgentSecret } from "@/lib/hyperliquid/agent-authorization";
import { loadAuthorizedTarget } from "./authority";
import type { ExchangeGateway, ExecutionRepository } from "./engine";
import { isEligibleMultiAccount } from "./engine";
import { assertAgentPrivateKeyMatches } from "./hyperliquid-l1-signing";
import { buildPlan } from "./planner";
import type { EligibleAccount } from "./types";

export type LivePreflightResult = {
  accountId: string;
  status: "READY" | "ALIGNED" | "BLOCKED" | "FAILED";
  actionCount: number;
  maxActionNotionalUsd: number;
  reason?: string;
};

type Candidate = EligibleAccount & { encryptedSecret?: EncryptedAgentSecret };

async function preflightOne(candidate: Candidate, target: Awaited<ReturnType<typeof loadAuthorizedTarget>>, exchange: ExchangeGateway): Promise<LivePreflightResult> {
  if (!isEligibleMultiAccount(candidate) || !candidate.encryptedSecret) {
    return { accountId: candidate.accountId, status: "BLOCKED", actionCount: 0, maxActionNotionalUsd: 0, reason: "account is not eligible" };
  }
  try {
    const [role, authorization, account, markets] = await Promise.all([
      exchange.userRole(candidate.agentAddress),
      exchange.agentAuthorization(candidate.masterAddress, candidate.agentAddress, candidate.agentName),
      exchange.readAccount(candidate.masterAddress),
      exchange.readMarkets()
    ]);
    if (role.role !== "agent" || role.user?.toLowerCase() !== candidate.masterAddress.toLowerCase()) {
      return { accountId: candidate.accountId, status: "BLOCKED", actionCount: 0, maxActionNotionalUsd: 0, reason: "agent binding is invalid" };
    }
    if (!authorization.authorized || authorization.validUntilMs === null || authorization.validUntilMs <= Date.now()) {
      return { accountId: candidate.accountId, status: "BLOCKED", actionCount: 0, maxActionNotionalUsd: 0, reason: "agent authorization is missing or expired" };
    }
    const privateKey = createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).decrypt(candidate.encryptedSecret);
    assertAgentPrivateKeyMatches(privateKey, candidate.agentAddress);
    const plan = buildPlan(target, account, markets);
    if (plan.state === "BLOCKED") {
      return { accountId: candidate.accountId, status: "BLOCKED", actionCount: 0, maxActionNotionalUsd: 0, reason: plan.reason };
    }
    return {
      accountId: candidate.accountId,
      status: plan.actions.length === 0 ? "ALIGNED" : "READY",
      actionCount: plan.actions.length,
      maxActionNotionalUsd: Math.max(0, ...plan.actions.map(({ requestedNotionalUsd }) => requestedNotionalUsd))
    };
  } catch {
    return { accountId: candidate.accountId, status: "FAILED", actionCount: 0, maxActionNotionalUsd: 0, reason: "live preflight could not be verified" };
  }
}

export async function preflightMultiAccountCandidates(
  candidates: Candidate[],
  target: Awaited<ReturnType<typeof loadAuthorizedTarget>>,
  exchange: ExchangeGateway
): Promise<LivePreflightResult[]> {
  return Promise.all(candidates.map((candidate) => preflightOne(candidate, target, exchange)));
}

/** Performs exchange reads and signer-identity checks only; it has no write call. */
export async function runMultiAccountLivePreflight(
  repositoryRoot: string,
  repository: Pick<ExecutionRepository, "listMultiAccountCandidates">,
  exchange: ExchangeGateway
): Promise<{ target: string; results: LivePreflightResult[] }> {
  const [target, candidates] = await Promise.all([
    loadAuthorizedTarget(repositoryRoot),
    repository.listMultiAccountCandidates()
  ]);
  const results = await preflightMultiAccountCandidates(candidates, target, exchange);
  return { target: target.asset, results };
}
