"use client";

import { useActionState } from "react";
import { refreshMyAccountPerformance, type RefreshPerformanceState } from "@/app/dashboard/actions";

const initialState: RefreshPerformanceState = { message: "" };

export function RefreshPerformanceButton() {
  const [state, action, pending] = useActionState(refreshMyAccountPerformance, initialState);
  return <form action={action}>
    <button disabled={pending} type="submit">{pending ? "Refreshing…" : "Refresh performance"}</button>
    {state.message && <p className="muted" role="status">{state.message}</p>}
  </form>;
}
