"use client";

import { createBrowserClient } from "@supabase/ssr";

function publicConfig(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("Authentication is not configured.");
  return { url, key };
}

export function createClient() {
  const { url, key } = publicConfig();
  return createBrowserClient(url, key);
}
