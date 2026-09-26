import "server-only";
import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";
import { normalizeHyperliquidOrderStatus } from "./order-status";

import {
  getHyperliquidAgentAuthorization,
  getHyperliquidAccountSnapshot,
  getHyperliquidUserRole
} from "@/lib/hyperliquid/info";
import type {
  ExchangeGateway,
  ExchangeOrder,
  KnownOrder,
  ExchangeCancellation
} from "./engine";
import type {
  ManagedAsset,
  MarketSpec
} from "./types";

export const HYPERLIQUID_INFO_API_URL = "https://api.hyperliquid.xyz/info";
export const HYPERLIQUID_REQUEST_TIMEOUT_MS = 8_000;
const MIN_NOTIONAL_USD = 10;

export type HyperliquidMarketRow = {
  assetIndex: number;
  markPrice: number;
  sizeDecimals: number;
  maxLeverage?: number;
};

type MetaEntry = {
  name?: unknown;
  szDecimals?: unknown;
  maxLeverage?: unknown;
  isDelisted?: unknown;
};

type AssetContext = {
  markPx?: unknown;
};

export async function fetchHyperliquidMarketIndex(fetcher: typeof fetch = fetch): Promise<Map<string, HyperliquidMarketRow>> {
  const response = await fetcher(HYPERLIQUID_INFO_API_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ type: "metaAndAssetCtxs" }),
    cache: "no-store",
    signal: AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)
  });

  if (!response.ok) {
    throw new Error("Hyperliquid market metadata is unavailable.");
  }

  const payload = await response.json() as unknown;
  if (!Array.isArray(payload) || payload.length !== 2) {
    throw new Error("Hyperliquid market metadata is invalid.");
  }

  const meta = payload[0] as { universe?: MetaEntry[] };
  const contexts = payload[1] as AssetContext[];

  if (!Array.isArray(meta?.universe) || !Array.isArray(contexts)) {
    throw new Error("Hyperliquid market metadata is invalid.");
  }

  const markets = new Map<string, HyperliquidMarketRow>();

  meta.universe.forEach((entry, index) => {
    const name = typeof entry?.name === "string"
      ? entry.name.trim().toUpperCase()
      : "";
    const sizeDecimals = Number(entry?.szDecimals);
    const markPrice = Number(contexts[index]?.markPx);

    if (
      name && entry.isDelisted !== true &&
      Number.isInteger(sizeDecimals) &&
      sizeDecimals >= 0 &&
      Number.isFinite(markPrice) &&
      markPrice > 0
    ) {
      const maxLeverage = Number(entry.maxLeverage);
      markets.set(name, { assetIndex: index, markPrice, sizeDecimals, ...(Number.isFinite(maxLeverage) && maxLeverage >= 1 ? { maxLeverage } : {}) });
    }
  });

  if (markets.size === 0) throw new Error("Hyperliquid market metadata is empty.");

  return markets;
}

/**
 * Strictly read-only gateway for the first multi-account dry run.
 * CLOID inspection is read-only; order and cancellation writes fail closed.
 */
export class HyperliquidDryRunGateway implements ExchangeGateway {
  constructor(private readonly fetcher: typeof fetch = fetch) {}

  protected marketIndex(): Promise<Map<string, HyperliquidMarketRow>> {
    return fetchHyperliquidMarketIndex(this.fetcher);
  }

  async readAccount(masterAddress: string) {
    const [snapshot, markets] = await Promise.all([
      getHyperliquidAccountSnapshot(masterAddress),
      this.marketIndex()
    ]);

    const positions = snapshot.positions.map((position) => {
      const asset = position.coin.toUpperCase();
      const market = markets.get(asset);

      if (!market) {
        throw new Error("An account position could not be valued safely.");
      }

      return {
        asset,
        size: position.size,
        markPrice: market.markPrice
      };
    });

    return {
      equityUsd: snapshot.accountEquityUsd,
      positions,
      openOrderCount: snapshot.openOrderCount,
      openOrders: snapshot.openOrders,
      marginAvailableUsd: snapshot.marginAvailableUsd
    };
  }

  async readMarkets(): Promise<Map<ManagedAsset, MarketSpec>> {
    const markets = await this.marketIndex();
    const result = new Map<ManagedAsset, MarketSpec>();

    for (const [asset, market] of markets) {
      result.set(asset, {
        asset,
        markPrice: market.markPrice,
        minNotionalUsd: MIN_NOTIONAL_USD,
        sizeDecimals: market.sizeDecimals,
        maxLeverage: market.maxLeverage
      });
    }

    return result;
  }

  async userRole(agentAddress: string) {
    return getHyperliquidUserRole(agentAddress);
  }

  async agentAuthorization(masterAddress: string, agentAddress: string, agentName: string) {
    return getHyperliquidAgentAuthorization(masterAddress, agentAddress, agentName);
  }

  async findByCloid(
    masterAddress: string,
    cloid: string
  ): Promise<KnownOrder> {
    const validation = validateHyperliquidAddress(masterAddress);
    if (!validation.ok || !/^0x[0-9a-f]{32}$/.test(cloid)) throw new Error("order lookup identity is invalid");
    try {
      const response = await this.fetcher(HYPERLIQUID_INFO_API_URL, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ type: "orderStatus", user: validation.address, oid: cloid }),
        cache: "no-store", signal: AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)
      });
      if (!response.ok) return { state: "unknown" };
      return normalizeHyperliquidOrderStatus(await response.json());
    } catch { return { state: "unknown" }; }
  }

  async writeIoc(
    _order: ExchangeOrder
  ): Promise<{ orderId?: string }> {
    void _order;
    throw new Error("Dry-run gateway cannot submit orders.");
  }

  async cancelOrder(_order: ExchangeCancellation): Promise<void> {
    void _order;
    throw new Error("Dry-run gateway cannot cancel orders.");
  }
}
