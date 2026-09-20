import "server-only";

import type { HyperliquidAccountPerformance } from "@/lib/hyperliquid/performance";
import { createAdminClient } from "@/lib/supabase/admin";

type PersistPerformanceInput = {
  userId: string;
  accountId: string;
  performance: HyperliquidAccountPerformance;
};

export async function persistHyperliquidAccountPerformance({
  userId,
  accountId,
  performance
}: PersistPerformanceInput): Promise<void> {
  const breakdown = performance.breakdown;
  const common = {
    user_id: userId,
    hyperliquid_account_id: accountId,
    snapshot_at: new Date(performance.asOfMs).toISOString(),
    account_equity_usd: performance.snapshot.accountEquityUsd,
    total_live_pnl_usd: performance.totalLivePnlUsd,
    trading_pnl_usd: breakdown?.tradingPnlUsd ?? null,
    fees_usd: breakdown?.feesUsd ?? null,
    funding_usd: breakdown?.fundingUsd ?? null,
    deposits_usd: breakdown?.depositsUsd ?? null,
    withdrawals_usd: breakdown?.withdrawalsUsd ?? null
  };
  const admin = createAdminClient();
  const [{ error: currentError }, { error: historyError }] = await Promise.all([
    admin.from("hyperliquid_account_performance").upsert({
      ...common,
      live_genesis_at: performance.liveGenesisAtMs === null ? null : new Date(performance.liveGenesisAtMs).toISOString(),
      history_days: performance.historyDays,
      cash_flow_adjusted_return_pct: performance.cashFlowAdjustedReturnPct,
      cash_flow_adjusted_return_available: performance.cashFlowAdjustedReturnAvailable,
      cash_flow_adjusted_return_reason: performance.cashFlowAdjustedReturnReason
    }, { onConflict: "hyperliquid_account_id" }),
    admin.from("hyperliquid_account_performance_history").upsert({
      ...common,
      performance_day: new Date(performance.asOfMs).toISOString().slice(0, 10)
    }, { onConflict: "hyperliquid_account_id,performance_day" })
  ]);
  if (currentError || historyError) {
    throw new Error("Account performance persistence failed.");
  }
}
