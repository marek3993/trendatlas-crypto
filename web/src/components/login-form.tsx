"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { normalizeEmail } from "@/lib/auth/validation";
import { createClient } from "@/lib/supabase/client";

export function LoginForm({ destination }: Readonly<{ destination: string }>) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const { error } = await createClient().auth.signInWithPassword({
        email: normalizeEmail(String(form.get("email") ?? "")),
        password: String(form.get("password") ?? "")
      });
      if (error) setMessage("Email or password is incorrect.");
      else router.replace(destination);
    } catch {
      setMessage("We could not sign you in. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return <form onSubmit={onSubmit} noValidate>
    <label>Email<input name="email" type="email" autoComplete="email" required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
    {message && <p className="error" role="alert">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Signing in…" : "Sign in"}</button>
    <p className="muted"><Link href="/forgot-password">Forgot password?</Link></p>
    <p className="muted">New to TrendAtlas? <Link href="/register">Create an account</Link></p>
  </form>;
}
