import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { protectedRouteRedirect, publicRouteRedirect, safeRedirectPath } from "@/lib/auth/redirects";

describe("route access", () => {
  it("redirects unauthenticated protected-route access to login", () => {
    expect(protectedRouteRedirect("/dashboard", false)).toBe("/login?next=%2Fdashboard");
  });

  it("allows authenticated protected-route access", () => {
    expect(protectedRouteRedirect("/dashboard", true)).toBeNull();
    expect(publicRouteRedirect(true)).toBe("/dashboard");
  });

  it("allows only local redirect destinations", () => {
    expect(safeRedirectPath("/settings?tab=profile")).toBe("/settings?tab=profile");
    expect(safeRedirectPath("https://example.invalid")).toBe("/dashboard");
    expect(safeRedirectPath("//example.invalid")).toBe("/dashboard");
    expect(safeRedirectPath("javascript:alert(1)")).toBe("/dashboard");
  });

  it("uses the Next 16 Proxy convention with server-confirmed session refresh", () => {
    const proxy = fs.readFileSync(path.join(process.cwd(), "src/proxy.ts"), "utf8");
    const session = fs.readFileSync(path.join(process.cwd(), "src/lib/supabase/middleware.ts"), "utf8");
    expect(proxy).toContain("export async function proxy");
    expect(proxy).toContain("await updateSession(request)");
    expect(proxy).not.toContain("request.cookies.get");
    expect(session).toContain("supabase.auth.getUser()");
  });
});
