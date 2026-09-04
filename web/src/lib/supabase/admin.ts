import "server-only";

import { createClient } from "@supabase/supabase-js";

export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_ADMIN_KEY;
  if (!url || !key) throw new Error("Account connections are not configured.");
  return createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } });
}
