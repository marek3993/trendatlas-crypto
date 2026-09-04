export const SUPPORTED_TARGETS = ["BTC", "ETH", "CASH"] as const;
export type TargetAsset = (typeof SUPPORTED_TARGETS)[number];
export type ManagedAsset = Exclude<TargetAsset, "CASH">;
export type ExecutionMode = "disabled" | "dry_run" | "live";
export type AccountExecutionStatus = "pending_multi_account_executor" | "ready" | "disabled_by_user" | "blocked" | "executing" | "aligned" | "error";
export type FinalStatus = "NO_ACTION" | "FILLED_AND_ALIGNED" | "PARTIAL" | "FAILED" | "BLOCKED" | "UNKNOWN_SUBMISSION_STATE" | "DISABLED" | "DRY_RUN";

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
export type AccountState = { equityUsd: number; positions: Position[]; openOrderCount: number };
export type MarketSpec = { asset: ManagedAsset; markPrice: number; minNotionalUsd: number; sizeDecimals: number };
export type PlannedAction = { action: "ENTER" | "EXIT" | "RESIZE"; asset: ManagedAsset; requestedNotionalUsd: number; size: number; reduceOnly: boolean; leg: number };
export type Plan = { state: "NO_ACTION" | "ENTER" | "EXIT" | "RESIZE" | "ROTATE" | "BLOCKED"; actions: PlannedAction[]; reason?: string };
