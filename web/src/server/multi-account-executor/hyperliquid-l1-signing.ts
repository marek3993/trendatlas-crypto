import "server-only";

import { encode } from "@msgpack/msgpack";
import { isAddress, keccak256, parseSignature, zeroAddress, type Address, type Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { normalizeHyperliquidAddress } from "@/lib/hyperliquid/address";
import type { ExchangeOrder } from "./engine";
import type { HyperliquidMarketRow } from "./dry-run-gateway";

const MAX_UINT64 = 18_446_744_073_709_551_615n;
const MAX_NONCE_CLOCK_SKEW_MS = 30_000;
const EXPIRES_AFTER_MS = 180_000;
const IOC_SLIPPAGE = 0.01;

type OrderWire = {
  a: number;
  b: boolean;
  p: string;
  s: string;
  r: boolean;
  t: { limit: { tif: "Ioc" } };
  c: string;
};

export type HyperliquidOrderAction = {
  type: "order";
  orders: [OrderWire];
  grouping: "na";
};

export type SignedIocPayload = {
  action: HyperliquidOrderAction;
  nonce: number;
  signature: { r: Hex; s: Hex; v: number };
  expiresAfter: number;
};

export class HyperliquidSigningError extends Error {
  constructor() {
    super("Hyperliquid order signing failed safely.");
  }
}

function uint64Bytes(value: bigint): Buffer {
  if (value < 0n || value > MAX_UINT64) throw new HyperliquidSigningError();
  const result = Buffer.alloc(8);
  result.writeBigUInt64BE(value);
  return result;
}

function floatToWire(value: number): string {
  if (!Number.isFinite(value) || value <= 0) throw new HyperliquidSigningError();
  const rounded = value.toFixed(8);
  if (Math.abs(Number(rounded) - value) >= 1e-12) throw new HyperliquidSigningError();
  return rounded.replace(/0+$/, "").replace(/\.$/, "");
}

function roundToSignificant(value: number, digits: number): number {
  if (!Number.isFinite(value) || value <= 0) throw new HyperliquidSigningError();
  return Number(value.toPrecision(digits));
}

export function computeHyperliquidIocLimitPrice(markPrice: number, isBuy: boolean, sizeDecimals: number): number {
  if (!Number.isInteger(sizeDecimals) || sizeDecimals < 0) throw new HyperliquidSigningError();
  const adjusted = markPrice * (isBuy ? 1 + IOC_SLIPPAGE : 1 - IOC_SLIPPAGE);
  const decimals = Math.max(0, 6 - sizeDecimals);
  const decimalFactor = 10 ** decimals;
  return Math.round(roundToSignificant(adjusted, 5) * decimalFactor) / decimalFactor;
}

export function assertAgentPrivateKeyMatches(agentPrivateKey: Hex, expectedAgentAddress: string): Address {
  if (!/^0x[0-9a-fA-F]{64}$/.test(agentPrivateKey) || !isAddress(expectedAgentAddress, { strict: false })) {
    throw new HyperliquidSigningError();
  }
  let actual: Address;
  try {
    actual = normalizeHyperliquidAddress(privateKeyToAccount(agentPrivateKey).address) as Address;
  } catch {
    throw new HyperliquidSigningError();
  }
  if (actual !== normalizeHyperliquidAddress(expectedAgentAddress)) throw new HyperliquidSigningError();
  return actual;
}

export function hyperliquidActionHash(action: HyperliquidOrderAction, nonce: bigint, expiresAfter: bigint): Hex {
  const encodedAction = Buffer.from(encode(action));
  const encoded = Buffer.concat([
    encodedAction,
    uint64Bytes(nonce),
    Buffer.from([0]),
    Buffer.from([0]),
    uint64Bytes(expiresAfter)
  ]);
  return keccak256(`0x${encoded.toString("hex")}`);
}

export async function buildSignedHyperliquidIocPayload(
  order: ExchangeOrder,
  market: HyperliquidMarketRow,
  nowMs = Date.now()
): Promise<SignedIocPayload> {
  const expectedAgentAddress = assertAgentPrivateKeyMatches(order.agentPrivateKey, order.agentAddress);
  if (!isAddress(order.masterAddress, { strict: false })) throw new HyperliquidSigningError();
  if (!/^0x[0-9a-f]{32}$/.test(order.cloid)) throw new HyperliquidSigningError();
  if (!Number.isSafeInteger(nowMs) || nowMs < 0) throw new HyperliquidSigningError();
  if (order.nonce < BigInt(nowMs - MAX_NONCE_CLOCK_SKEW_MS) || order.nonce > BigInt(nowMs + MAX_NONCE_CLOCK_SKEW_MS)) {
    throw new HyperliquidSigningError();
  }
  if (!Number.isInteger(market.assetIndex) || market.assetIndex < 0 || !Number.isFinite(order.size) || order.size <= 0) {
    throw new HyperliquidSigningError();
  }
  if ((order.action === "ENTER" && order.reduceOnly) || (order.action === "EXIT" && !order.reduceOnly)) {
    throw new HyperliquidSigningError();
  }

  const isBuy = !order.reduceOnly;
  const limitPrice = computeHyperliquidIocLimitPrice(market.markPrice, isBuy, market.sizeDecimals);
  const action: HyperliquidOrderAction = {
    type: "order",
    orders: [{
      a: market.assetIndex,
      b: isBuy,
      p: floatToWire(limitPrice),
      s: floatToWire(order.size),
      r: order.reduceOnly,
      t: { limit: { tif: "Ioc" } },
      c: order.cloid
    }],
    grouping: "na"
  };
  const expiresAfter = order.nonce + BigInt(EXPIRES_AFTER_MS);
  const connectionId = hyperliquidActionHash(action, order.nonce, expiresAfter);
  const signatureHex = await privateKeyToAccount(order.agentPrivateKey).signTypedData({
    domain: { chainId: 1337, name: "Exchange", verifyingContract: zeroAddress, version: "1" },
    types: { Agent: [{ name: "source", type: "string" }, { name: "connectionId", type: "bytes32" }] },
    primaryType: "Agent",
    message: { source: "a", connectionId }
  });
  const parsed = parseSignature(signatureHex);
  const v = Number(parsed.v ?? BigInt((parsed.yParity ?? 0) + 27));
  const nonce = Number(order.nonce);
  const expiresAfterNumber = Number(expiresAfter);
  if (!Number.isSafeInteger(nonce) || !Number.isSafeInteger(expiresAfterNumber) || (v !== 27 && v !== 28)) {
    throw new HyperliquidSigningError();
  }
  if (expectedAgentAddress !== normalizeHyperliquidAddress(order.agentAddress)) throw new HyperliquidSigningError();

  return { action, nonce, signature: { r: parsed.r, s: parsed.s, v }, expiresAfter: expiresAfterNumber };
}
