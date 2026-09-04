import "server-only";

import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";

const INFO_API_URL = "https://api.hyperliquid.xyz/info";
const REQUEST_TIMEOUT_MS = 8_000;

export const ALLOWED_INFO_REQUEST_TYPES = ["clearinghouseState", "openOrders"] as const;
type AllowedInfoRequestType = (typeof ALLOWED_INFO_REQUEST_TYPES)[number];

type ClearinghouseState = {
  marginSummary?: { accountValue?: string; totalMarginUsed?: string };
  withdrawable?: string;
  assetPositions?: Array<{ position?: { coin?: string; szi?: string; entryPx?: string } }>;
};

type OpenOrder = { oid?: number | string };

export type HyperliquidAccountSnapshot = {
  address: string;
  accountEquityUsd: number;
  withdrawableUsd: number | null;
  positions: Array<{ coin: string; size: number; entryPrice: number | null }>;
  openOrderCount: number;
};

export class HyperliquidInfoError extends Error {
  constructor() {
    super("Hyperliquid account data is unavailable.");
  }
}

function isAllowedInfoRequestType(value: string): value is AllowedInfoRequestType {
  return (ALLOWED_INFO_REQUEST_TYPES as readonly string[]).includes(value);
}

function numberOrNull(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function requestInfo<T>(type: string, user: string): Promise<T> {
  if (!isAllowedInfoRequestType(type)) throw new HyperliquidInfoError();

  let response: Response;
  try {
    response = await fetch(INFO_API_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type, user }),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
  } catch {
    throw new HyperliquidInfoError();
  }

  if (!response.ok) throw new HyperliquidInfoError();
  try {
    return await response.json() as T;
  } catch {
    throw new HyperliquidInfoError();
  }
}

/** Exported for regression tests; unknown request types fail before any fetch. */
export async function requestReadOnlyInfoForTest(type: string, user: string): Promise<unknown> {
  return requestInfo<unknown>(type, user);
}

export async function getHyperliquidAccountSnapshot(rawAddress: string): Promise<HyperliquidAccountSnapshot> {
  const validation = validateHyperliquidAddress(rawAddress);
  if (!validation.ok) throw new HyperliquidInfoError();

  const [state, openOrders] = await Promise.all([
    requestInfo<ClearinghouseState>("clearinghouseState", validation.address),
    requestInfo<OpenOrder[]>("openOrders", validation.address)
  ]);
  const accountEquityUsd = numberOrNull(state.marginSummary?.accountValue);
  if (accountEquityUsd === null || accountEquityUsd < 0 || !Array.isArray(state.assetPositions) || !Array.isArray(openOrders)) {
    throw new HyperliquidInfoError();
  }

  const withdrawableUsd = numberOrNull(state.withdrawable);
  const positions = state.assetPositions.flatMap(({ position }) => {
    const size = numberOrNull(position?.szi);
    if (!position?.coin || size === null || size === 0) return [];
    return [{ coin: position.coin, size, entryPrice: numberOrNull(position.entryPx) }];
  });

  return {
    address: validation.address,
    accountEquityUsd,
    withdrawableUsd: withdrawableUsd !== null && withdrawableUsd >= 0 ? withdrawableUsd : null,
    positions,
    openOrderCount: openOrders.length
  };
}
