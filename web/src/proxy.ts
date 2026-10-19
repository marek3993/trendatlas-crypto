import { NextResponse, type NextRequest } from "next/server";
import { protectedRouteRedirect, publicRouteRedirect } from "@/lib/auth/redirects";
import { updateSession } from "@/lib/supabase/middleware";

const protectedPaths = new Set(["/dashboard", "/onboarding", "/settings", "/update-password"]);
const publicAuthPaths = new Set(["/login", "/register"]);

export async function proxy(request: NextRequest) {
  const { response, hasUser } = await updateSession(request);
  const pathname = request.nextUrl.pathname;

  if (protectedPaths.has(pathname)) {
    const redirect = protectedRouteRedirect(pathname, hasUser);
    if (redirect) return NextResponse.redirect(new URL(redirect, request.url));
  }
  if (publicAuthPaths.has(pathname) && publicRouteRedirect(hasUser)) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return response;
}

export const config = {
  matcher: ["/dashboard", "/onboarding", "/settings", "/update-password", "/login", "/register"]
};
