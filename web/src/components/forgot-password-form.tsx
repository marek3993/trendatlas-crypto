"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { normalizeEmail } from "@/lib/auth/validation";

export function ForgotPasswordForm() {
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    try {
      const form = new FormData(event.currentTarget);
      await createClient().auth.resetPasswordForEmail(normalizeEmail(String(form.get("email") ?? "")), {
        redirectTo: `${window.location.origin}/auth/callback?next=/update-password`
      });
      setMessage("If an account exists, a reset link has been sent.");
    } catch {
      setMessage("We could not start password reset. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return <form onSubmit={onSubmit} noValidate>
    <label>Email<input name="email" type="email" autoComplete="email" required /></label>
    {message && <p className="notice" role="status">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Sending…" : "Send reset link"}</button>
    <p className="muted"><Link href="/login">Back to sign in</Link></p>
  </form>;
}
