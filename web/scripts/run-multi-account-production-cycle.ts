async function main(): Promise<void> {
  const [
    { requireCanonicalProductionContext },
    { loadCanonicalRunTarget },
    { MultiAccountExecutor },
    { HyperliquidLiveGateway },
    { preflightMultiAccountCandidates },
    { SupabaseExecutionRepository }
  ] = await Promise.all([
    import("@/server/multi-account-executor/canonical-production-guard"),
    import("@/server/multi-account-executor/authority"),
    import("@/server/multi-account-executor/engine"),
    import("@/server/multi-account-executor/hyperliquid-live-gateway"),
    import("@/server/multi-account-executor/live-preflight"),
    import("@/server/multi-account-executor/repository")
  ]);

  const guard = requireCanonicalProductionContext();
  const repository = new SupabaseExecutionRepository();
  const exchange = new HyperliquidLiveGateway();
  const [target, candidates] = await Promise.all([
    loadCanonicalRunTarget(guard.repositoryRoot, guard.runId, guard.signalId),
    repository.listMultiAccountCandidates()
  ]);
  if (target.signalId !== guard.signalId) throw new Error("canonical target does not match the confirmed signal");
  if (candidates.length === 0) throw new Error("no eligible multi-account candidates were found");
  if (candidates.filter(({ masterAddress }) => masterAddress.toLowerCase() === guard.ownerMasterAddress).length !== 1) {
    throw new Error("the canonical owner account is not uniquely eligible for multi-account execution");
  }

  const preflight = await preflightMultiAccountCandidates(candidates, target, exchange);
  if (preflight.length !== candidates.length || preflight.some(({ status }) => status === "BLOCKED" || status === "FAILED")) {
    throw new Error("one or more eligible accounts failed the all-account preflight");
  }

  let results: Array<{ accountId: string; status: string; reason?: string }>;
  let successful: boolean;
  let realOrderSent: boolean | null;
  if (guard.mode === "dry_run") {
    results = preflight.map(({ accountId, status, reason }) => ({
      accountId,
      status: status === "ALIGNED" ? "PREFLIGHT_ALIGNED" : "PREFLIGHT_READY",
      ...(reason ? { reason } : {})
    }));
    successful = true;
    realOrderSent = false;
  } else {
    const fixedRepository = {
      listMultiAccountCandidates: async () => candidates,
      tryAcquire: repository.tryAcquire.bind(repository),
      release: repository.release.bind(repository),
      reserveNonce: repository.reserveNonce.bind(repository),
      createRun: repository.createRun.bind(repository),
      recordAction: repository.recordAction.bind(repository),
      finishRun: repository.finishRun.bind(repository),
      setAccountStatus: repository.setAccountStatus.bind(repository)
    };
    results = await new MultiAccountExecutor(fixedRepository, exchange, "live", guard.maxConcurrency, {
      stopOnUnsafeResult: true
    }).runAllForTarget(target);
    successful = results.every(({ status }) => status === "NO_ACTION" || status === "FILLED_AND_ALIGNED");
    const ambiguous = results.some(({ status }) => status === "UNKNOWN_SUBMISSION_STATE" || status === "PARTIAL");
    realOrderSent = ambiguous ? null : results.some(({ status }) => status === "FILLED_AND_ALIGNED");
  }
  const report = {
    mode: guard.mode === "live" ? "canonical_multi_account_production" : "canonical_multi_account_preflight",
    runId: guard.runId,
    target: target.asset,
    signalId: target.signalId,
    accountCount: candidates.length,
    preflight,
    results,
    successful,
    realOrderSent
  };
  console.log(JSON.stringify(report));
  if (!successful) process.exitCode = 1;
}

void main().catch((error) => {
  const message = error instanceof Error ? error.message : "unknown multi-account production error";
  console.error(`Canonical multi-account production refused safely: ${message}`);
  process.exitCode = 1;
});
