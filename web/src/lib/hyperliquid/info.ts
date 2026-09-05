import "server-only";

import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";

const INFO_API_URL = "https://api.hyperliquid.xyz/info";
const REQUEST_TIMEOUT_MS = 8_000;

/**
 * This is intentionally an Info-only allowlist. Every member is required for
 * the read-only account view or cash-flow-adjusted performance calculation.
 */
export const ALLOWED_INFO_REQUEST_TYPES = [
  "clearinghouseState",
  "spotClearinghouseState",
  "openOrders",
  "portfolio",
  "userFillsByTime",
  "userFunding",
  "userNonFundingLedgerUpdates",
  "userRole"
] as const;
type AllowedInfoRequestType = (typeof ALLOWED_INFO_REQUEST_TYPES)[number];

type ClearinghouseState = {
  marginSummary?: { accountValue?: string; totalMarginUsed?: string };
  withdrawable?: string;
  assetPositions?: Array<{ position?: { coin?: string; szi?: string; entryPx?: string } }>;
};

type SpotClearinghouseState = {
  balances?: Array<{ coin?: string; total?: string }>;
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

export type HyperliquidUserRole = "missing" | "user" | "agent" | "vault" | "subAccount";

function isAllowedInfoRequestType(value: string): value is AllowedInfoRequestType {
  return (ALLOWED_INFO_REQUEST_TYPES as readonly string[]).includes(value);
}

function numberOrNull(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

type HistoryRequest = { startTime: number; endTime: number };

async function requestInfo<T>(type: string, user: string, history?: HistoryRequest): Promise<T> {
  if (!isAllowedInfoRequestType(type)) throw new HyperliquidInfoError();
  if (history && (!Number.isSafeInteger(history.startTime) || !Number.isSafeInteger(history.endTime) || history.startTime < 0 || history.endTime < history.startTime)) {
    throw new HyperliquidInfoError();
  }

  let response: Response;
  try {
    response = await fetch(INFO_API_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type, user, ...(history ?? {}) }),
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
export async function requestReadOnlyInfoForTest(type: string, user: string, history?: HistoryRequest): Promise<unknown> {
  return requestInfo<unknown>(type, user, history);
}

/** Reads only the exchange role binding; it never authorizes or changes account state. */
export async function getHyperliquidUserRole(rawAddress: string): Promise<{ role: HyperliquidUserRole; user: string | null }> {
  const validation = validateHyperliquidAddress(rawAddress);
  if (!validation.ok) throw new HyperliquidInfoError();
  const result = await requestInfo<{ role?: unknown; data?: { user?: unknown } }>("userRole", validation.address);
  const role = result?.role;
  if (role !== "missing" && role !== "user" && role !== "agent" && role !== "vault" && role !== "subAccount") {
    throw new HyperliquidInfoError();
  }
  const user = typeof result.data?.user === "string" ? validateHyperliquidAddress(result.data.user) : null;
  return { role, user: user?.ok ? user.address : null };
}

export type HyperliquidPortfolioResponse = Array<[
  string,
  { accountValueHistory?: Array<[number, string | number]> }
]>;

export type HyperliquidFill = { time?: number; timestamp?: number; closedPnl?: string | number; fee?: string | number };
export type HyperliquidFunding = { time?: number; timestamp?: number; usdc?: string | number; delta?: { usdc?: string | number } };
export type HyperliquidNonFundingLedgerUpdate = {
  time?: number;
  timestamp?: number;
  hash?: string;
  delta?: { type?: string; usdc?: string | number; usdcValue?: string | number; amount?: string | number; destination?: string; user?: string };
};

export async function getHyperliquidAccountSnapshot(rawAddress: string): Promise<HyperliquidAccountSnapshot> {
  const validation = validateHyperliquidAddress(rawAddress);
  if (!validation.ok) throw new HyperliquidInfoError();

  const [state, spotState, openOrders] = await Promise.all([
    requestInfo<ClearinghouseState>("clearinghouseState", validation.address),
    requestInfo<SpotClearinghouseState>("spotClearinghouseState", validation.address),
    requestInfo<OpenOrder[]>("openOrders", validation.address)
  ]);
  const perpsAccountEquityUsd = numberOrNull(state.marginSummary?.accountValue);
  if (perpsAccountEquityUsd === null || perpsAccountEquityUsd < 0 || !Array.isArray(state.assetPositions) || !Array.isArray(spotState.balances) || !Array.isArray(openOrders)) {
    throw new HyperliquidInfoError();
  }

  const spotUsdcBalance = spotState.balances.find(({ coin }) => coin === "USDC");
  const spotUsdcUsd = spotUsdcBalance ? numberOrNull(spotUsdcBalance.total) : 0;
  if (spotUsdcUsd === null || spotUsdcUsd < 0) {
    throw new HyperliquidInfoError();
  }

  const accountEquityUsd = perpsAccountEquityUsd + spotUsdcUsd;
  const perpsWithdrawableUsd = numberOrNull(state.withdrawable);
  const withdrawableUsd = perpsWithdrawableUsd !== null && perpsWithdrawableUsd >= 0
    ? perpsWithdrawableUsd + spotUsdcUsd
    : spotUsdcUsd;
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

/** Fetches only documented read-only history required by the performance ledger. */
export async function getHyperliquidPerformanceInputs(rawAddress: string): Promise<{
  snapshot: HyperliquidAccountSnapshot;
  portfolio: HyperliquidPortfolioResponse;
  fills: HyperliquidFill[];
  funding: HyperliquidFunding[];
  nonFundingLedgerUpdates: HyperliquidNonFundingLedgerUpdate[];
  asOfMs: number;
}> {
  const validation = validateHyperliquidAddress(rawAddress);
  if (!validation.ok) throw new HyperliquidInfoError();

  const [snapshot, portfolio] = await Promise.all([
    getHyperliquidAccountSnapshot(validation.address),
    requestInfo<HyperliquidPortfolioResponse>("portfolio", validation.address)
  ]);
  if (!Array.isArray(portfolio)) throw new HyperliquidInfoError();

  const allTime = portfolio.find(([period]) => period === "allTime")?.[1]?.accountValueHistory;
  const timestamps = Array.isArray(allTime)
    ? allTime.map(([timestamp]) => timestamp).filter((timestamp) => Number.isSafeInteger(timestamp) && timestamp >= 0)
    : [];
  const earliest = timestamps.length > 0 ? Math.min(...timestamps) : Number.NaN;
  const asOfMs = Date.now();
  if (!Number.isSafeInteger(earliest) || earliest > asOfMs) {
    return { snapshot, portfolio, fills: [], funding: [], nonFundingLedgerUpdates: [], asOfMs };
  }

  const history = { startTime: earliest, endTime: asOfMs };
  const fullLedgerHistory = { startTime: 0, endTime: asOfMs };
  const [fills, funding, nonFundingLedgerUpdates] = await Promise.all([
    requestInfo<HyperliquidFill[]>("userFillsByTime", validation.address, history),
    requestInfo<HyperliquidFunding[]>("userFunding", validation.address, history),
    requestInfo<HyperliquidNonFundingLedgerUpdate[]>("userNonFundingLedgerUpdates", validation.address, fullLedgerHistory)
  ]);
  if (!Array.isArray(fills) || !Array.isArray(funding) || !Array.isArray(nonFundingLedgerUpdates)) throw new HyperliquidInfoError();
  return { snapshot, portfolio, fills, funding, nonFundingLedgerUpdates, asOfMs };
}
