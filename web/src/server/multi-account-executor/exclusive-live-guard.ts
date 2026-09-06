import "server-only";

import { spawnSync } from "node:child_process";
import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";

export type SystemdStateReader = (operation: "is-active" | "is-enabled", unit: string) => string;

const defaultSystemdStateReader: SystemdStateReader = (operation, unit) => {
  const result = spawnSync("systemctl", [operation, unit], { encoding: "utf8" });
  return String(result.stdout || result.stderr || "").trim();
};

export type ExclusiveLiveGuard = {
  allowedMasterAddress: string;
  maxNotionalUsd: number;
};

/** Refuses live ownership while the legacy production scheduler can still run. */
export function requireExclusiveMultiAccountLiveOwnership(
  env: NodeJS.ProcessEnv = process.env,
  readSystemdState: SystemdStateReader = defaultSystemdStateReader
): ExclusiveLiveGuard {
  if (env.TRENDATLAS_MULTI_ACCOUNT_EXECUTION_MODE !== "live") throw new Error("live mode is not explicitly enabled");
  if (env.TRENDATLAS_EXECUTION_OWNER !== "multi_account") throw new Error("multi-account execution ownership is not confirmed");

  const address = validateHyperliquidAddress(env.TRENDATLAS_LIVE_MASTER_ADDRESS ?? "");
  if (!address.ok) throw new Error("live master address is invalid");
  const allowedMasterAddress = address.address;
  if (env.TRENDATLAS_LIVE_CONFIRMATION !== `ENABLE:${allowedMasterAddress}`) throw new Error("live account confirmation does not match");

  const maxNotionalUsd = Number(env.TRENDATLAS_LIVE_MAX_NOTIONAL_USD);
  if (!Number.isFinite(maxNotionalUsd) || maxNotionalUsd < 10 || maxNotionalUsd > 100) {
    throw new Error("live notional cap must be between 10 and 100 USD");
  }

  if (readSystemdState("is-enabled", "mrv1-production.timer") !== "disabled") {
    throw new Error("legacy production timer is not disabled");
  }
  if (readSystemdState("is-active", "mrv1-production.timer") !== "inactive") {
    throw new Error("legacy production timer is not inactive");
  }
  if (readSystemdState("is-active", "mrv1-production.service") !== "inactive") {
    throw new Error("legacy production service is not inactive");
  }

  return { allowedMasterAddress, maxNotionalUsd };
}
