"use server";

import { revalidatePath } from "next/cache";
import { requireUser } from "@/lib/auth/require-user";
import { getHyperliquidAccountPerformance } from "@/lib/hyperliquid/performance";
import { createAdminClient } from "@/lib/supabase/admin";

export type RefreshPerformanceState = { message: string };

export async function refreshMyAccountPerformance(_previousState: RefreshPerformanceState): Promise<RefreshPerformanceState> {
  void _previousState;
  const { supabase, user } = await requireUser();
  const { data: account } = await supabase
    .from("hyperliquid_accounts")
    .select("id, master_address, connection_status")
    .eq("user_id", user.id)
    .maybeSingle<{ id: string; master_address: string; connection_status: string }>();
  if (!account || account.connection_status !== "read_only_connected") {
    return { message: "Connect an account before refreshing performance." };
  }

  try {
    const performance = await getHyperliquidAccountPerformance(account.master_address);
    const breakdown = performance.breakdown;
    const common = {
      user_id: user.id,
      hyperliquid_account_id: account.id,
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
    if (currentError || historyError) return { message: "Performance was calculated but could not be saved. Please try again." };
  } catch {
    return { message: "Account performance is temporarily unavailable." };
  }

  revalidatePath("/dashboard");
  return { message: "Performance refreshed." };
}
