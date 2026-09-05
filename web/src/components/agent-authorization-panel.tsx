"use client";

import { useState } from "react";
import { createWalletClient, custom, isAddress, type Address, type EIP1193Provider } from "viem";
import {
  approveAgentDomain,
  approveAgentTypes
} from "@/lib/hyperliquid/approve-agent-typed-data";
import {
  beginAgentAuthorization,
  setAutoTradingRequested,
  submitAgentAuthorization
} from "@/app/dashboard/agent-actions";
import { normalizeHyperliquidAddress } from "@/lib/hyperliquid/address";

type AuthorizationState = {
  authorizationStatus: string;
  autoTradingRequested: boolean;
  executionStatus: string;
  liveExecutorEnabled: boolean;
} | null;

type BrowserChallenge = {
  id: string;
  masterAddress: string;
  action: { agentAddress: string; agentName: string; nonce: string };
};

type DetectableProvider = EIP1193Provider & {
  isTrust?: boolean;
  isTrustWallet?: boolean;
  providers?: DetectableProvider[];
};

function walletProvider(): EIP1193Provider | null {
  if (typeof window === "undefined") return null;
  const browser = window as unknown as {
    ethereum?: DetectableProvider;
    trustwallet?: DetectableProvider | { ethereum?: DetectableProvider };
  };
  const trustWallet = browser.trustwallet;
  const nestedTrustWallet = (trustWallet as { ethereum?: DetectableProvider } | undefined)?.ethereum;
  if (nestedTrustWallet) return nestedTrustWallet;
  const directTrustWallet = trustWallet as DetectableProvider | undefined;
  if (typeof directTrustWallet?.request === "function") return directTrustWallet;
  const injected = browser.ethereum;
  return injected?.providers?.find((provider) => provider.isTrust || provider.isTrustWallet) ??
    (injected?.isTrust || injected?.isTrustWallet ? injected : injected ?? null);
}

export function AgentAuthorizationPanel({ authorization }: { authorization: AuthorizationState }) {
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function authorize() {
    setPending(true);
    setMessage("");
    try {
      const started = await beginAgentAuthorization();
      if (!started.challenge) {
        setMessage(started.message);
        return;
      }
      await connectAndSign(started.challenge as BrowserChallenge);
    } catch {
      setMessage("We could not complete the wallet approval. Please try again.");
    } finally {
      setPending(false);
    }
  }

  async function connectAndSign(challenge: BrowserChallenge) {
    const provider = walletProvider();
    if (!provider) {
      setMessage("No browser wallet was found. Install or unlock your wallet, then try again.");
      return;
    }
    const wallet = createWalletClient({ transport: custom(provider) });
    const addresses = await wallet.requestAddresses();
    const connected = addresses[0];
    if (!connected || !isAddress(connected, { strict: false }) || normalizeHyperliquidAddress(connected) !== challenge.masterAddress) {
      setMessage("The connected wallet does not match your saved Hyperliquid account. No signature was requested.");
      return;
    }
    const signature = await wallet.signTypedData({
      account: connected as Address,
      domain: approveAgentDomain,
      types: approveAgentTypes,
      primaryType: "HyperliquidTransaction:ApproveAgent",
      message: {
        hyperliquidChain: "Mainnet",
        agentAddress: challenge.action.agentAddress as Address,
        agentName: challenge.action.agentName,
        nonce: BigInt(challenge.action.nonce)
      }
    });
    const result = await submitAgentAuthorization(challenge.id, signature);
    setMessage(result.message);
  }

  async function changePreference() {
    if (!authorization) return;
    setPending(true);
    try {
      const result = await setAutoTradingRequested(!authorization.autoTradingRequested);
      setMessage(result.message);
    } finally {
      setPending(false);
    }
  }

  if (authorization?.authorizationStatus === "authorized") {
    return <section className="authorization-panel" aria-label="TrendAtlas authorization">
      <h2>TrendAtlas</h2>
      <p>Ownership <span className="notice">Verified</span></p>
      <p>TrendAtlas agent <span className="notice">Authorized</span></p>
      <p>Auto trading preference <strong>{authorization.autoTradingRequested ? "ON" : "OFF"}</strong></p>
      <p>Executor <span className="muted">{authorization.liveExecutorEnabled ? "Ready" : "Live executor: not enabled yet"}</span></p>
      <button type="button" disabled={pending} onClick={changePreference}>
        Turn auto trading {authorization.autoTradingRequested ? "off" : "on"}
      </button>
      {message && <p className="muted" role="status">{message}</p>}
    </section>;
  }

  return <section className="authorization-panel" aria-label="TrendAtlas authorization">
    <h2>Authorize TrendAtlas</h2>
    <p>TrendAtlas never asks for your wallet private key or seed phrase.</p>
    <p className="muted">Your wallet signs one approval that grants a generated TrendAtlas agent trading-signature authority. This authorization does not send trades.</p>
    <button type="button" disabled={pending} onClick={authorize}>
      {pending ? "Preparing approval…" : "Approve TrendAtlas trading agent"}
    </button>
    {message && <p className="error" role="status">{message}</p>}
  </section>;
}
