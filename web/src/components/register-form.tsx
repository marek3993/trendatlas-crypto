"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { validateRegistration } from "@/lib/auth/validation";

export function RegisterForm() {
  const [message, setMessage] = useState<string>("");
  const [pending, setPending] = useState(false);

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
    if (!validation.ok) return setMessage(validation.message);

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
      setMessage(error ? "We could not create your account. Please try again." : "Check your email to verify your account.");
    } catch {
      setMessage("We could not create your account. Please try again.");
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
    {message && <p className={message.startsWith("Check") ? "notice" : "error"} role="status">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Creating account…" : "Create account"}</button>
    <p className="muted">Already have an account? <Link href="/login">Sign in</Link></p>
  </form>;
}
