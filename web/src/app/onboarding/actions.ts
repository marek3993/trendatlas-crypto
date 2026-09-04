"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { requireUser } from "@/lib/auth/require-user";
import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";
import { getHyperliquidAccountSnapshot } from "@/lib/hyperliquid/info";
import { createAdminClient } from "@/lib/supabase/admin";

export type ConnectionActionState = { message: string };

export async function connectHyperliquidAccount(
  _previousState: ConnectionActionState,
  formData: FormData
): Promise<ConnectionActionState> {
  const { user } = await requireUser();
  const validation = validateHyperliquidAddress(String(formData.get("masterAddress") ?? ""));
  if (!validation.ok) return { message: validation.message };

  try {
    await getHyperliquidAccountSnapshot(validation.address);
    const { error } = await createAdminClient()
      .from("hyperliquid_accounts")
      .upsert({
        user_id: user.id,
        master_address: validation.address,
        connection_status: "read_only_connected",
        verified_at: new Date().toISOString()
      }, { onConflict: "user_id" });
    if (error) return { message: "We could not connect that account. Please try again." };
  } catch {
    return { message: "We could not verify that account. Please check the address and try again." };
  }

  revalidatePath("/dashboard");
  redirect("/dashboard");
}

export async function disconnectHyperliquidAccount(): Promise<void> {
  const { supabase, user } = await requireUser();
  await supabase.from("hyperliquid_accounts").delete().eq("user_id", user.id);
  revalidatePath("/dashboard");
  revalidatePath("/onboarding");
}
