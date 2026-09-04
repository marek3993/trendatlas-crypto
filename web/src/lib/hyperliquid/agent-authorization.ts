import "server-only";

import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { isAddress, parseSignature, recoverTypedDataAddress, type Address, type Hex } from "viem";
import { normalizeHyperliquidAddress } from "@/lib/hyperliquid/address";
import {
  approveAgentDomain,
  approveAgentTypes,
  HYPERLIQUID_CHAIN,
  HYPERLIQUID_MAINNET_CHAIN_ID,
  HYPERLIQUID_SIGNATURE_CHAIN_ID
} from "@/lib/hyperliquid/approve-agent-typed-data";

const EXCHANGE_API_URL = "https://api.hyperliquid.xyz/exchange";
const REQUEST_TIMEOUT_MS = 8_000;
const AES_GCM_IV_BYTES = 12;

export { HYPERLIQUID_MAINNET_CHAIN_ID, HYPERLIQUID_SIGNATURE_CHAIN_ID, HYPERLIQUID_CHAIN };
export const ALLOWED_EXCHANGE_ACTION_TYPES = ["approveAgent"] as const;
export { approveAgentDomain, approveAgentTypes };

export type ApproveAgentAction = {
  type: "approveAgent";
  hyperliquidChain: typeof HYPERLIQUID_CHAIN;
  signatureChainId: typeof HYPERLIQUID_SIGNATURE_CHAIN_ID;
  agentAddress: Address;
  agentName: string;
  nonce: bigint;
};

export type ApproveAgentChallengePayload = {
  id: string;
  masterAddress: Address;
  action: ApproveAgentAction;
};

type GeneratedAgentMaterial = { address: Address; privateKey: Hex; name: string };
export type EncryptedAgentSecret = {
  encryptedPrivateKey: string;
  encryptionNonce: string;
  encryptionKeyVersion: string;
};

export class AgentAuthorizationError extends Error {
  constructor(message = "Agent authorization could not be completed.") {
    super(message);
  }
}

function assertAddress(value: string): Address {
  if (!isAddress(value, { strict: false })) throw new AgentAuthorizationError();
  return normalizeHyperliquidAddress(value) as Address;
}

function assertAgentName(value: string): string {
  if (!/^TA-[a-f0-9]{8}$/.test(value)) throw new AgentAuthorizationError();
  return value;
}

function assertNonce(value: bigint): bigint {
  if (value < 0n || value > 18_446_744_073_709_551_615n) throw new AgentAuthorizationError();
  return value;
}

export function buildApproveAgentAction(agentAddress: string, agentName: string, nonce: bigint): ApproveAgentAction {
  return {
    type: "approveAgent",
    hyperliquidChain: HYPERLIQUID_CHAIN,
    signatureChainId: HYPERLIQUID_SIGNATURE_CHAIN_ID,
    agentAddress: assertAddress(agentAddress),
    agentName: assertAgentName(agentName),
    nonce: assertNonce(nonce)
  };
}

export function approveAgentTypedData(action: ApproveAgentAction) {
  return {
    domain: approveAgentDomain,
    types: approveAgentTypes,
    primaryType: "HyperliquidTransaction:ApproveAgent" as const,
    message: {
      hyperliquidChain: action.hyperliquidChain,
      agentAddress: action.agentAddress,
      agentName: action.agentName,
      nonce: action.nonce
    }
  };
}

/** Generates fresh server-only agent material; callers must encrypt it before persistence. */
export function generateAgentMaterial(): GeneratedAgentMaterial {
  const privateKey = generatePrivateKey();
  const account = privateKeyToAccount(privateKey);
  return {
    address: normalizeHyperliquidAddress(account.address) as Address,
    privateKey,
    name: `TA-${randomBytes(4).toString("hex")}`
  };
}

function decodeKek(value: string | undefined): Buffer {
  if (!value || !/^[A-Za-z0-9+/]{43}=$/.test(value)) {
    throw new AgentAuthorizationError("Agent authorization is not configured.");
  }
  const key = Buffer.from(value, "base64");
  if (key.length !== 32) throw new AgentAuthorizationError("Agent authorization is not configured.");
  return key;
}

export interface AgentSecretProtector {
  readonly keyVersion: string;
  encrypt(plaintext: Hex): EncryptedAgentSecret;
  decrypt(secret: EncryptedAgentSecret): Hex;
}

export function createEnvironmentAgentSecretProtector(kekB64: string | undefined): AgentSecretProtector {
  const key = decodeKek(kekB64);
  const keyVersion = "env-aes-256-gcm-v1";
  return {
    keyVersion,
    encrypt(plaintext: Hex): EncryptedAgentSecret {
      const iv = randomBytes(AES_GCM_IV_BYTES);
      const cipher = createCipheriv("aes-256-gcm", key, iv);
      const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
      const authenticatedCiphertext = Buffer.concat([cipher.getAuthTag(), ciphertext]);
      return {
        encryptedPrivateKey: authenticatedCiphertext.toString("base64"),
        encryptionNonce: iv.toString("base64"),
        encryptionKeyVersion: keyVersion
      };
    },
    decrypt(secret: EncryptedAgentSecret): Hex {
      if (secret.encryptionKeyVersion !== keyVersion) throw new AgentAuthorizationError();
      const iv = Buffer.from(secret.encryptionNonce, "base64");
      const payload = Buffer.from(secret.encryptedPrivateKey, "base64");
      if (iv.length !== AES_GCM_IV_BYTES || payload.length <= 16) throw new AgentAuthorizationError();
      const decipher = createDecipheriv("aes-256-gcm", key, iv);
      decipher.setAuthTag(payload.subarray(0, 16));
      try {
        return Buffer.concat([decipher.update(payload.subarray(16)), decipher.final()]).toString("utf8") as Hex;
      } catch {
        throw new AgentAuthorizationError();
      }
    }
  };
}

export function encryptGeneratedAgent(material: GeneratedAgentMaterial, protector: AgentSecretProtector): EncryptedAgentSecret {
  return protector.encrypt(material.privateKey);
}

export async function recoverApproveAgentSigner(action: ApproveAgentAction, signature: Hex): Promise<Address> {
  try {
    const recovered = await recoverTypedDataAddress({ ...approveAgentTypedData(action), signature });
    return normalizeHyperliquidAddress(recovered) as Address;
  } catch {
    throw new AgentAuthorizationError("The wallet signature could not be verified.");
  }
}

function isAllowedExchangeActionType(value: unknown): value is (typeof ALLOWED_EXCHANGE_ACTION_TYPES)[number] {
  return typeof value === "string" && (ALLOWED_EXCHANGE_ACTION_TYPES as readonly string[]).includes(value);
}

/** The sole Stage 4 mutation gate. It rejects every non-approveAgent action before fetch. */
export function assertAllowedExchangeAction(action: unknown): asserts action is ApproveAgentAction {
  if (!action || typeof action !== "object" || !isAllowedExchangeActionType((action as { type?: unknown }).type)) {
    throw new AgentAuthorizationError("This exchange action is not allowed.");
  }
}

type ExchangeFetcher = (input: string, init: RequestInit) => Promise<Response>;

export async function submitApproveAgentExchangeAction(
  action: ApproveAgentAction,
  signature: Hex,
  fetcher: ExchangeFetcher = fetch
): Promise<void> {
  assertAllowedExchangeAction(action);
  let parsed: ReturnType<typeof parseSignature>;
  try {
    parsed = parseSignature(signature);
  } catch {
    throw new AgentAuthorizationError("The wallet signature could not be verified.");
  }
  let response: Response;
  try {
    response = await fetcher(EXCHANGE_API_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: { ...action, nonce: Number(action.nonce) }, nonce: Number(action.nonce), signature: { r: parsed.r, s: parsed.s, v: Number(parsed.v) } }),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
  } catch {
    throw new AgentAuthorizationError("The approval could not be submitted.");
  }
  if (!response.ok) throw new AgentAuthorizationError("The approval could not be submitted.");
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new AgentAuthorizationError("The approval could not be confirmed.");
  }
  if (!body || typeof body !== "object" || (body as { status?: unknown }).status !== "ok" || (body as { response?: { type?: unknown } }).response?.type !== "default") {
    throw new AgentAuthorizationError("The approval could not be confirmed.");
  }
}
