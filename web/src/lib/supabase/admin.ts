import "server-only";

import { createClient } from "@supabase/supabase-js";
import { readOnlyTransport } from "@/server/multi-account-executor/read-only-transport";

export function createAdminClient(readOnly = false) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_ADMIN_KEY;
  if (!url || !key) throw new Error("Account connections are not configured.");
  return createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false },
    ...(readOnly ? { global: { fetch: readOnlyTransport() } } : {}) });
}
