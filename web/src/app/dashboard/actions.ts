"use server";

import { revalidatePath } from "next/cache";
import { requireUser } from "@/lib/auth/require-user";
import { getHyperliquidAccountPerformance } from "@/lib/hyperliquid/performance";
import { persistHyperliquidAccountPerformance } from "@/lib/hyperliquid/performance-store";

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
    await persistHyperliquidAccountPerformance({
      userId: user.id,
      accountId: account.id,
      performance
    });
  } catch {
    return { message: "Account performance is temporarily unavailable." };
  }

  revalidatePath("/dashboard");
  return { message: "Performance refreshed." };
}
