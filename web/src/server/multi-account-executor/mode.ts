import "server-only";

import type { ExecutionMode } from "./types";

export function executionMode(value = process.env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE): ExecutionMode {
  return value === "dry_run" || value === "live" ? value : "disabled";
}

export function canWriteExchange(mode: ExecutionMode): boolean {
  return mode === "live";
}
