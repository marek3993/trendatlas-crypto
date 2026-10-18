"use client";

import { useActionState } from "react";
import { connectHyperliquidAccount, type ConnectionActionState } from "@/app/onboarding/actions";

const initialState: ConnectionActionState = { message: "" };

export function HyperliquidConnectForm() {
  const [state, action, pending] = useActionState(connectHyperliquidAccount, initialState);

  return <form action={action} noValidate>
    <label>
      Hyperliquid account address
      <input
        name="masterAddress"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        inputMode="text"
        placeholder="0x..."
        required
      />
    </label>
    <p className="muted">Enter only your public account address. TrendAtlas uses it to display account data.</p>
    {state.message && <p className="error" role="status">{state.message}</p>}
    <button disabled={pending} type="submit">{pending ? "Connecting…" : "Connect Hyperliquid"}</button>
  </form>;
}
