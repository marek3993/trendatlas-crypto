import { describe, expect, it } from "vitest";
import { normalizeEmail, validatePasswordUpdate, validateRegistration } from "@/lib/auth/validation";

describe("registration validation", () => {
  const valid = {
    displayName: "Alex Example",
    email: " Alex@Example.COM ",
    password: "long-password",
    passwordConfirmation: "long-password",
    termsAccepted: true
  };

  it("normalizes the email and accepts valid registration", () => {
    expect(validateRegistration(valid)).toEqual({ ok: true, displayName: "Alex Example", email: "alex@example.com" });
    expect(normalizeEmail(valid.email)).toBe("alex@example.com");
  });

  it("rejects a password mismatch", () => {
    expect(validateRegistration({ ...valid, passwordConfirmation: "another-password" })).toMatchObject({ ok: false, message: "Passwords do not match." });
  });

  it("requires terms acceptance", () => {
    expect(validateRegistration({ ...valid, termsAccepted: false })).toMatchObject({ ok: false, message: "Accept the terms to continue." });
  });

  it("validates a password update", () => {
    expect(validatePasswordUpdate("new-password", "new-password")).toMatchObject({ ok: true });
    expect(validatePasswordUpdate("new-password", "mismatch")).toMatchObject({ ok: false, message: "Passwords do not match." });
  });
});
