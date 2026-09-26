import type { Address } from "viem";

export const HYPERLIQUID_MAINNET_CHAIN_ID = 42161;
export const HYPERLIQUID_SIGNATURE_CHAIN_ID = "0xa4b1";
export const HYPERLIQUID_CHAIN = "Mainnet" as const;

export const approveAgentTypes = {
  "HyperliquidTransaction:ApproveAgent": [
    { name: "hyperliquidChain", type: "string" },
    { name: "agentAddress", type: "address" },
    { name: "agentName", type: "string" },
    { name: "nonce", type: "uint64" }
  ]
} as const;

export const approveAgentDomain = {
  name: "HyperliquidSignTransaction",
  version: "1",
  chainId: HYPERLIQUID_MAINNET_CHAIN_ID,
  verifyingContract: "0x0000000000000000000000000000000000000000" as Address
} as const;
