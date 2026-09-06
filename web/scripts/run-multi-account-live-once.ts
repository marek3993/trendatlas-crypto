import path from "node:path";
import { fileURLToPath } from "node:url";

async function main(): Promise<void> {
  const [{ requireExclusiveMultiAccountLiveOwnership }, { loadAuthorizedTarget }, { MultiAccountExecutor }, { HyperliquidLiveGateway }, { preflightMultiAccountCandidates }, { SupabaseExecutionRepository }] = await Promise.all([
    import("@/server/multi-account-executor/exclusive-live-guard"),
    import("@/server/multi-account-executor/authority"),
    import("@/server/multi-account-executor/engine"),
    import("@/server/multi-account-executor/hyperliquid-live-gateway"),
    import("@/server/multi-account-executor/live-preflight"),
    import("@/server/multi-account-executor/repository")
  ]);

  const guard = requireExclusiveMultiAccountLiveOwnership();
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
  const repository = new SupabaseExecutionRepository();
  const exchange = new HyperliquidLiveGateway();
  const [target, candidates] = await Promise.all([
    loadAuthorizedTarget(repositoryRoot),
    repository.listMultiAccountCandidates()
  ]);

  if (candidates.length !== 1 || candidates[0].masterAddress.toLowerCase() !== guard.allowedMasterAddress) {
    throw new Error("the eligible account set does not exactly match the live allowlist");
  }

  const preflight = await preflightMultiAccountCandidates(candidates, target, exchange);
  if (preflight.length !== 1 || !["READY", "ALIGNED"].includes(preflight[0].status)) {
    throw new Error("live preflight is not ready");
  }
  if (preflight[0].maxActionNotionalUsd > guard.maxNotionalUsd) {
    throw new Error("planned action exceeds the live notional cap");
  }
  if (preflight[0].actionCount > 0 && process.env.TRENDATLAS_LIVE_SIGNAL_CONFIRMATION !== target.signalId) {
    throw new Error("live signal confirmation does not match the authorized target");
  }

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
  const results = await new MultiAccountExecutor(fixedRepository, exchange, "live", 1).runAllForTarget(target);
  console.log(JSON.stringify({ mode: "live_once", target: target.asset, signalId: target.signalId, results }, null, 2));
  if (results.some(({ status }) => !["NO_ACTION", "FILLED_AND_ALIGNED"].includes(status))) process.exitCode = 1;
}

void main().catch((error) => {
  const message = error instanceof Error ? error.message : "unknown live execution error";
  console.error(`Multi-account live execution refused safely: ${message}`);
  process.exitCode = 1;
});
