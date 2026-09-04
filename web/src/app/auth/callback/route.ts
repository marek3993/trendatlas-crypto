import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { safeRedirectPath } from "@/lib/auth/redirects";

function publicConfig(): { url: string; key: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  return url && key ? { url, key } : null;
}

export async function GET(request: NextRequest) {
  const target = safeRedirectPath(request.nextUrl.searchParams.get("next"));
  const response = NextResponse.redirect(new URL(target, request.url));
  const code = request.nextUrl.searchParams.get("code");
  const config = publicConfig();
  if (!code || !config) return NextResponse.redirect(new URL("/login", request.url));

  const supabase = createServerClient(config.url, config.key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      }
    }
  });
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  return error ? NextResponse.redirect(new URL("/login", request.url)) : response;
}
