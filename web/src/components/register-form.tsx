"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  const [message, setMessage] = useState<string>("");
  const [messageKind, setMessageKind] = useState<MessageKind>("notice");
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

    setPending(true);
    try {
      const { data, error } = await createClient().auth.signUp({
        email: validation.email,
        password: String(form.get("password")),
        options: {
          data: { display_name: validation.displayName }
        }
      });

      if (error) {
        if (isExistingAccount(error)) {
          showMessage("notice", "This email already has an account. Sign in instead.");
        } else if (isEmailRateLimit(error)) {
          showMessage("error", "Too many attempts. Wait a minute and try again.");
        } else {
          showMessage("error", "We could not create your account. Check the details and try again.");
        }
        return;
      }

      if (data.session) {
        router.replace("/dashboard");
        router.refresh();
        return;
      }

      if (data.user?.identities?.length === 0) {
        showMessage("notice", "This email already has an account. Sign in instead.");
        return;
      }

      showMessage("error", "Your account was created, but instant access is not enabled. Contact Marek.");
    } catch {
      showMessage("error", "The registration service could not be reached. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return <form onSubmit={onSubmit} noValidate>
    <p className="muted">No verification email is required. After registration you continue directly to your private dashboard.</p>
    <label>Name<input name="displayName" autoComplete="name" required /></label>
    <label>Email<input name="email" type="email" autoComplete="email" required /></label>
    <label>Password<input name="password" type="password" autoComplete="new-password" required /></label>
    <label>Confirm password<input name="passwordConfirmation" type="password" autoComplete="new-password" required /></label>
    <label className="checkbox"><input name="terms" type="checkbox" /> I accept the terms.</label>
    {message && <p className={messageKind} role="status">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Creating account…" : "Create account"}</button>
    <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
  </form>;
}
