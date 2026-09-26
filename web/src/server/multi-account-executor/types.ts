export type TargetAsset = string;
export type ManagedAsset = string;

/** Syntax only. Exchange membership comes exclusively from current metadata. */
export function normalizeTargetAsset(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toUpperCase();
  return /^[A-Z0-9][A-Z0-9._:-]{0,63}$/.test(normalized) ? normalized : null;
}
export type ExecutionMode = "disabled" | "dry_run" | "live";
export type AccountExecutionStatus = "pending_multi_account_executor" | "ready" | "disabled_by_user" | "blocked" | "executing" | "aligned" | "error";
export type FinalStatus = "NO_ACTION" | "FILLED_AND_ALIGNED" | "PARTIAL" | "FAILED" | "BLOCKED" | "UNKNOWN_SUBMISSION_STATE" | "DISABLED" | "DRY_RUN" | "EXITED_ENTRY_FAILED_STAYING_CASH" | "ENTRY_FAILED_STAYING_CASH";

export type AuthorizedTarget = {
  strategyVersion: string;
  closedDay: string;
  signalId: string;
  asset: TargetAsset;
  exposure: number;
  stale: false;
  executionGate: "approved" | "no_action";
};

export type EligibleAccount = {
  userId: string;
  accountId: string;
  masterAddress: string;
  agentAddress: string;
  agentName: string;
  authorizationId: string;
  connectionStatus: string;
  authorizationStatus: string;
  ownershipVerifiedAt: string | null;
  agentAuthorizedAt: string | null;
  autoTradingRequested: boolean;
  executionStatus: AccountExecutionStatus;
  hasEncryptedSecret: boolean;
};

export type Position = { asset: string; size: number; markPrice: number };
export type OpenOrder = { asset: string; orderId: string; cloid?: string; side?: "buy" | "sell"; size?: number };
export type AccountState = { equityUsd: number; positions: Position[]; openOrderCount: number; openOrders?: OpenOrder[]; marginAvailableUsd?: number };
export type MarketSpec = { asset: ManagedAsset; markPrice: number; minNotionalUsd: number; sizeDecimals: number; maxLeverage?: number };
export type PlannedAction = { action: "ENTER" | "EXIT" | "RESIZE" | "CANCEL"; asset: ManagedAsset; requestedNotionalUsd: number; size: number; reduceOnly: boolean; leg: number; side?: "buy" | "sell" };
export type Plan = { state: "NO_ACTION" | "ENTER" | "EXIT" | "RESIZE" | "ROTATE" | "BLOCKED"; actions: PlannedAction[]; reason?: string; entryBlockedReason?: string };
