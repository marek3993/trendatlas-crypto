import "server-only";

import path from "node:path";
import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";

export type CanonicalProductionGuard = {
  mode: "dry_run" | "live";
  repositoryRoot: string;
  runId: string;
  signalId: string;
  ownerMasterAddress: string;
  maxConcurrency: number;
};

/** Allows writes only as the execution stage of the already locked canonical orchestrator. */
export function requireCanonicalProductionContext(env: NodeJS.ProcessEnv = process.env): CanonicalProductionGuard {
  const mode = env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE;
  if (mode !== "dry_run" && mode !== "live") throw new Error("multi-account production mode is not explicitly enabled");
  if (env.TRENDATLAS_EXECUTION_OWNER !== "multi_account") throw new Error("multi-account execution ownership is not confirmed");
  if (env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_CONTEXT !== "canonical_orchestrator") throw new Error("canonical orchestrator context is missing");
  if (env.TRENDATLAS_MULTI_ACCOUNT_CONFIRMATION !== "ENABLE:ALL_ELIGIBLE_ACCOUNTS") throw new Error("all-account execution confirmation is missing");

  const repositoryRoot = path.resolve(env.TRENDATLAS_AUTHORITY_REPOSITORY_ROOT ?? "");
  if (!path.isAbsolute(repositoryRoot) || repositoryRoot === path.parse(repositoryRoot).root) throw new Error("authority repository root is invalid");
  const runId = env.MRV1_CURRENT_AUTHORITY_RUN_ID?.trim() ?? "";
  const signalId = env.TRENDATLAS_LIVE_SIGNAL_CONFIRMATION?.trim() ?? "";
  if (!runId || !signalId) throw new Error("canonical run and signal binding is missing");
  const owner = validateHyperliquidAddress(env.MRV1_HYPERLIQUID_ACCOUNT_ADDRESS ?? "");
  if (!owner.ok) throw new Error("canonical owner account is invalid");

  const maxConcurrency = Number(env.TRENDATLAS_MULTI_ACCOUNT_MAX_CONCURRENCY ?? "1");
  if (maxConcurrency !== 1) throw new Error("canonical multi-account production must execute sequentially");
  return { mode, repositoryRoot, runId, signalId, ownerMasterAddress: owner.address, maxConcurrency };
}
