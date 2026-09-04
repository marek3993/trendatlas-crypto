import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function publicConfig(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("Authentication is not configured.");
  return { url, key };
}

export async function createClient() {
  const cookieStore = await cookies();
  const { url, key } = publicConfig();
  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll() {
        // Server Components cannot set cookies. Middleware refreshes sessions.
      }
    }
  });
}
