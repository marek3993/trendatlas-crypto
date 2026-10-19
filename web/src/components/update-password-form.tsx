"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { validatePasswordUpdate } from "@/lib/auth/validation";

export function UpdatePasswordForm() {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const validation = validatePasswordUpdate(password, String(form.get("passwordConfirmation") ?? ""));
    if (!validation.ok) return setMessage(validation.message);
    setPending(true);
    try {
      const { error } = await createClient().auth.updateUser({ password });
      if (error) setMessage("We could not update your password. Request a new reset link and try again.");
      else router.replace("/dashboard");
    } catch {
      setMessage("We could not update your password. Request a new reset link and try again.");
    } finally {
      setPending(false);
    }
  }

  return <form onSubmit={onSubmit} noValidate>
    <label>New password<input name="password" type="password" autoComplete="new-password" required /></label>
    <label>Confirm new password<input name="passwordConfirmation" type="password" autoComplete="new-password" required /></label>
    {message && <p className="error" role="alert">{message}</p>}
    <button disabled={pending} type="submit">{pending ? "Updating…" : "Update password"}</button>
  </form>;
}
