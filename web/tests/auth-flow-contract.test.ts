import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const source = (relativePath: string) => fs.readFileSync(path.join(root, relativePath), "utf8");

describe("authentication flow plumbing", () => {
  it("has email verification callback exchange and safe callback redirect", () => {
    const callback = source("src/app/auth/callback/route.ts");
    expect(callback).toContain("exchangeCodeForSession");
    expect(callback).toContain("safeRedirectPath");
  });

  it("starts the forgot-password flow with the password-update callback", () => {
    const form = source("src/components/forgot-password-form.tsx");
    expect(form).toContain("resetPasswordForEmail");
    expect(form).toContain("next=/update-password");
  });

  it("updates a password only through the authenticated provider session", () => {
    const form = source("src/components/update-password-form.tsx");
    expect(form).toContain("auth.updateUser({ password })");
  });

  it("provides a logout action", () => {
    expect(source("src/components/logout-button.tsx")).toContain("auth.signOut()");
  });

  it("sanitizes the login destination on the server before passing it to the client form", () => {
    const page = source("src/app/login/page.tsx");
    const form = source("src/components/login-form.tsx");
    expect(page).toContain("safeRedirectPath");
    expect(page).toContain("await searchParams");
    expect(page).toContain("<LoginForm destination={destination} />");
    expect(form).not.toContain("useSearchParams");
    expect(form).toContain("router.replace(destination)");
  });
});
