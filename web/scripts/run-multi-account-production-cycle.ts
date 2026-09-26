import { sharedFailureReport, type ProductionStage } from "@/server/multi-account-executor/batch";

let stage: ProductionStage = "configuration";
let currentRunId: string | null = null;
let currentSignalId: string | null = process.env.TRENDATLAS_LIVE_SIGNAL_CONFIRMATION?.trim() || null;
let noSubmit = process.env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE !== "live";

async function main(): Promise<void> {
  const [
    { requireCanonicalProductionContext }, { loadCanonicalRunTarget }, { MultiAccountExecutor },
    { HyperliquidDryRunGateway }, { preflightMultiAccountCandidates }, { SupabaseExecutionRepository },
    { runPreflightedBatch, isolateDuplicateWallets, summarizeAccountBatch }
  ] = await Promise.all([
    import("@/server/multi-account-executor/canonical-production-guard"),
    import("@/server/multi-account-executor/authority"),
    import("@/server/multi-account-executor/engine"),
    import("@/server/multi-account-executor/dry-run-gateway"),
    import("@/server/multi-account-executor/live-preflight"),
    import("@/server/multi-account-executor/repository"),
    import("@/server/multi-account-executor/batch")
  ]);
  const guard = requireCanonicalProductionContext();
  currentRunId = guard.runId;
  currentSignalId = guard.signalId;
  noSubmit = guard.mode === "dry_run";
  const repository = new SupabaseExecutionRepository();
  const exchange = new HyperliquidDryRunGateway();
  stage = "authority";
  const target = await loadCanonicalRunTarget(guard.repositoryRoot, guard.runId, guard.signalId);
  if (target.signalId !== guard.signalId) throw new Error("canonical target does not match the confirmed signal");
  stage = "candidates";
  const candidates = await repository.listMultiAccountCandidates();
  stage = "metadata";
  await exchange.readMarkets();
  stage = "preflight";
  const preflight = isolateDuplicateWallets(candidates, await preflightMultiAccountCandidates(candidates, target, exchange, repository));
  stage = "execution";
  const results = await runPreflightedBatch(preflight, noSubmit, async (readyIds) => {
    const { HyperliquidLiveGateway } = await import("@/server/multi-account-executor/hyperliquid-live-gateway");
    const fixedRepository = {
      listMultiAccountCandidates: async () => candidates.filter(({ accountId }) => readyIds.includes(accountId)),
      tryAcquire: repository.tryAcquire.bind(repository), release: repository.release.bind(repository),
      reserveNonce: repository.reserveNonce.bind(repository), createRun: repository.createRun.bind(repository),
      recordAction: repository.recordAction.bind(repository), readActions: repository.readActions.bind(repository),
      readUnresolvedActions: repository.readUnresolvedActions.bind(repository), markActionVerified: repository.markActionVerified.bind(repository),
      isManagedOrder: repository.isManagedOrder.bind(repository), renewLease: repository.renewLease.bind(repository),
      finishRun: repository.finishRun.bind(repository), setAccountStatus: repository.setAccountStatus.bind(repository)
    };
    return new MultiAccountExecutor(fixedRepository, new HyperliquidLiveGateway(), "live", guard.maxConcurrency).runAllForTarget(target);
  }, async (failed) => {
    const candidate = candidates.find(({ accountId }) => accountId === failed.accountId);
    if (!candidate) throw new Error("preflight account context is unavailable");
    const status = failed.status === "FAILED" ? "FAILED" : "BLOCKED";
    const runId = await repository.createRun(candidate, target, failed.accountEquityUsd ?? null, status);
    // A failed preflight is an attempt outcome, never confirmation of pending orders.
    await repository.finishRun(runId, status, failed.accountEquityUsd ?? null, failed.reason);
    await repository.setAccountStatus(candidate.authorizationId, status === "FAILED" ? "error" : "blocked");
  });
  const summary = summarizeAccountBatch(candidates, results, guard.ownerMasterAddress);
  console.log(JSON.stringify({
    mode: noSubmit ? "canonical_multi_account_preflight" : "canonical_multi_account_production",
    runId: guard.runId, target: target.asset, signalId: target.signalId,
    accountCount: candidates.length, preflight, results, ...summary
  }));
  if (!summary.successful) process.exitCode = 1;
}

void main().catch(() => {
  console.log(JSON.stringify(sharedFailureReport(stage, currentRunId, noSubmit, currentSignalId)));
  console.error("Canonical multi-account production could not be verified.");
  process.exitCode = 1;
});
