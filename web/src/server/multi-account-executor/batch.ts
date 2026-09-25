import type { LivePreflightResult } from "./live-preflight";
import type { EligibleAccount } from "./types";

export type BatchAccountResult = {
  accountId: string;
  status: string;
  reason?: string;
  orderRequested?: boolean | null;
  failureKind?: "retryable" | "deterministic";
  evidenceRecordingFailed?: boolean;
};
export type ProductionStage = "configuration" | "authority" | "candidates" | "metadata" | "preflight" | "execution";

/** Never serialize raw exceptions: transport/config errors may contain credentials. */
export function sharedFailureReport(stage: ProductionStage, runId: string | null, noSubmit: boolean, signalId: string | null = null) {
  return {
    mode: noSubmit ? "canonical_multi_account_preflight" : "canonical_multi_account_production",
    runId, signalId, successful: false, allAccountsSuccessful: false, accountCount: 0,
    results: [], preflight: [], ownerResult: null,
    realOrderSent: stage === "execution" && !noSubmit ? null : false,
    failureKind: stage === "configuration" || stage === "authority" ? "deterministic" : "retryable",
    reason: `Shared production ${stage} could not be verified.`
  };
}

/** Duplicate enrollments of one exchange wallet are unsafe only for those enrollments. */
export function isolateDuplicateWallets(candidates: Array<Pick<EligibleAccount, "masterAddress" | "accountId">>, preflight: LivePreflightResult[]): LivePreflightResult[] {
  const count = new Map<string, number>();
  for (const { masterAddress } of candidates) count.set(masterAddress.toLowerCase(), (count.get(masterAddress.toLowerCase()) ?? 0) + 1);
  const duplicateIds = new Set(candidates.filter(({ masterAddress }) => count.get(masterAddress.toLowerCase())! > 1).map(({ accountId }) => accountId));
  return preflight.map((row) => duplicateIds.has(row.accountId) ? { ...row, status: "BLOCKED", failureKind: "deterministic", reason: "exchange wallet has multiple automatic execution enrollments", actions: [], actionCount: 0 } : row);
}

export function summarizeAccountBatch(candidates: Array<Pick<EligibleAccount, "masterAddress" | "accountId">>, results: BatchAccountResult[], ownerMasterAddress: string) {
  const owners = candidates.filter(({ masterAddress }) => masterAddress.toLowerCase() === ownerMasterAddress.toLowerCase());
  const ownerResult = owners.length === 1 ? results.find(({ accountId }) => accountId === owners[0].accountId) : undefined;
  const effectiveOwner = ownerResult ?? { status: "BLOCKED", orderRequested: false, failureKind: "deterministic", reason: "canonical owner account is missing or has ambiguous enrollment" };
  const successes = new Set(["NO_ACTION", "FILLED_AND_ALIGNED", "PREFLIGHT_READY", "PREFLIGHT_ALIGNED"]);
  return {
    ownerResult: effectiveOwner,
    successful: successes.has(effectiveOwner.status),
    allAccountsSuccessful: candidates.length > 0 && results.length === candidates.length && results.every(({ status }) => successes.has(status)),
    realOrderSent: results.some(({ orderRequested }) => orderRequested === true) ? true : results.some(({ orderRequested }) => orderRequested == null) ? null : false,
    failureKind: results.some(({ failureKind }) => failureKind === "retryable") ? "retryable" : "deterministic"
  };
}

/** Failure recording and execution are both scoped to the affected account. */
export async function runPreflightedBatch(
  preflight: LivePreflightResult[],
  noSubmit: boolean,
  executeReady: (accountIds: string[]) => Promise<BatchAccountResult[]>,
  recordFailure?: (result: LivePreflightResult) => Promise<void>
): Promise<BatchAccountResult[]> {
  const recordingFailures = new Set<string>();
  if (recordFailure) {
    await Promise.all(preflight.filter(({ status }) => status === "FAILED" || status === "BLOCKED" || (noSubmit && status === "ENTRY_BLOCKED")).map(async (row) => {
      try { await recordFailure(row); } catch { recordingFailures.add(row.accountId); }
    }));
  }
  const fromPreflight = (row: LivePreflightResult, status: string): BatchAccountResult => ({
    accountId: row.accountId, status, reason: row.reason, orderRequested: false,
    ...(recordingFailures.has(row.accountId) ? { evidenceRecordingFailed: true, failureKind: "retryable" as const } : row.failureKind ? { failureKind: row.failureKind } : row.status === "FAILED" ? { failureKind: "retryable" as const } : row.status === "BLOCKED" || row.status === "ENTRY_BLOCKED" ? { failureKind: "deterministic" as const } : {})
  });
  if (noSubmit) return preflight.map((row) => fromPreflight(row, row.status === "ALIGNED" ? "PREFLIGHT_ALIGNED" : row.status === "READY" ? "PREFLIGHT_READY" : row.status === "ENTRY_BLOCKED" ? "PREFLIGHT_ENTRY_BLOCKED" : row.status));
  const readyIds = preflight.filter(({ status }) => status === "READY" || status === "ALIGNED" || status === "ENTRY_BLOCKED").map(({ accountId }) => accountId);
  const executed = readyIds.length ? await executeReady(readyIds) : [];
  return preflight.map((row) => executed.find(({ accountId }) => accountId === row.accountId) ?? fromPreflight(row, row.status === "FAILED" ? "FAILED" : "BLOCKED"));
}
