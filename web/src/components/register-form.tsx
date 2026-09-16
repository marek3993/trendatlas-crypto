"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { validateRegistration } from "@/lib/auth/validation";

type MessageKind = "notice" | "error";

type AuthFailure = {
  code?: string;
  message: string;
  status?: number;
};

function isEmailRateLimit(error: AuthFailure) {
  return error.status === 429
    || error.code?.includes("rate_limit") === true
    || /rate limit|too many requests/i.test(error.message);
}

function isExistingAccount(error: AuthFailure) {
  return error.code === "user_already_exists"
    || /already (registered|exists)/i.test(error.message);
}

export function RegisterForm() {
  const [message, setMessage] = useState<string>("");
  const [messageKind, setMessageKind] = useState<MessageKind>("notice");
  const [verificationEmail, setVerificationEmail] = useState("");
  const [pending, setPending] = useState(false);

  function showMessage(kind: MessageKind, text: string) {
    setMessageKind(kind);
    setMessage(text);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const validation = validateRegistration({
      displayName: String(form.get("displayName") ?? ""),
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
      passwordConfirmation: String(form.get("passwordConfirmation") ?? ""),
      termsAccepted: form.get("terms") === "on"
    });
    if (!validation.ok) {
      showMessage("error", validation.message);
      return;
    }

    setVerificationEmail(validation.email);
    setPending(true);
    try {
      const { error } = await createClient().auth.signUp({
        email: validation.email,
        password: String(form.get("password")),
        options: {
          data: { display_name: validation.displayName },
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/dashboard`
        }
      });

      if (!error) {
        showMessage("notice", "Account created. Check your email (including spam) to verify it.");
      } else if (isExistingAccount(error)) {
        showMessage("notice", "This email is already registered. Sign in, or resend the verification email below.");
      } else if (isEmailRateLimit(error)) {
        showMessage("notice", "The account may already be created, but email sending is temporarily limited. Wait a minute, then resend the verification email.");
      } else {
        showMessage("error", "We could not complete registration. Please check the details and try again.");
      }
    } catch {
      showMessage("error", "The registration service could not be reached. Please try again.");
    } finally {
      setPending(false);
    }
  }

  async function resendVerification() {
    if (!verificationEmail) return;

    setPending(true);
    try {
      const { error } = await createClient().auth.resend({
        type: "signup",
        email: verificationEmail,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/dashboard`
        }
      });

      if (!error) {
        showMessage("notice", "Verification email sent. Check your inbox and spam folder.");
      } else if (isEmailRateLimit(error)) {
        showMessage("notice", "Please wait a minute before requesting another verification email.");
      } else {
        showMessage("error", "We could not resend the verification email. Please try again.");
      }
    } catch {
      showMessage("error", "The email service could not be reached. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return <form onSubmit={onSubmit} noValidate>
    <label>Name<input name="displayName" autoComplete="name" required /></label>
    <label>Email<input name="email" type="email" autoComplete="email" required /></label>
    <label>Password<input name="password" type="password" autoComplete="new-password" required /></label>
    <label>Confirm password<input name="passwordConfirmation" type="password" autoComplete="new-password" required /></label>
    <label className="checkbox"><input name="terms" type="checkbox" /> I accept the terms.</label>
    {message && <p className={messageKind} role="status">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Please wait…" : "Create account"}</button>
    {verificationEmail && <button disabled={pending} type="button" onClick={resendVerification}>Resend verification email</button>}
    <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
  </form>;
}
