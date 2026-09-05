import "server-only";

import {
  getHyperliquidAccountSnapshot,
  getHyperliquidUserRole
} from "@/lib/hyperliquid/info";
import type {
  ExchangeGateway,
  ExchangeOrder,
  KnownOrder
} from "./engine";
import type {
  ManagedAsset,
  MarketSpec
} from "./types";

const INFO_API_URL = "https://api.hyperliquid.xyz/info";
const REQUEST_TIMEOUT_MS = 8_000;
const MIN_NOTIONAL_USD = 10;
const MANAGED_ASSETS: readonly ManagedAsset[] = ["BTC", "ETH"];

type MarketRow = {
  markPrice: number;
  sizeDecimals: number;
};

type MetaEntry = {
  name?: unknown;
  szDecimals?: unknown;
};

type AssetContext = {
  markPx?: unknown;
};

async function fetchMarketIndex(): Promise<Map<string, MarketRow>> {
  const response = await fetch(INFO_API_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ type: "metaAndAssetCtxs" }),
    cache: "no-store",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
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

  const markets = new Map<string, MarketRow>();

  meta.universe.forEach((entry, index) => {
    const name = typeof entry?.name === "string"
      ? entry.name.trim().toUpperCase()
      : "";
    const sizeDecimals = Number(entry?.szDecimals);
    const markPrice = Number(contexts[index]?.markPx);

    if (
      name &&
      Number.isInteger(sizeDecimals) &&
      sizeDecimals >= 0 &&
      Number.isFinite(markPrice) &&
      markPrice > 0
    ) {
      markets.set(name, { markPrice, sizeDecimals });
    }
  });

  for (const asset of MANAGED_ASSETS) {
    if (!markets.has(asset)) {
      throw new Error("Required Hyperliquid market metadata is unavailable.");
    }
  }

  return markets;
}

/**
 * Strictly read-only gateway for the first multi-account dry run.
 * Both order-related methods fail closed.
 */
export class HyperliquidDryRunGateway implements ExchangeGateway {
  private marketIndexPromise: Promise<Map<string, MarketRow>> | null = null;

  private marketIndex(): Promise<Map<string, MarketRow>> {
    this.marketIndexPromise ??= fetchMarketIndex();
    return this.marketIndexPromise;
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
      openOrderCount: snapshot.openOrderCount
    };
  }

  async readMarkets(): Promise<Map<ManagedAsset, MarketSpec>> {
    const markets = await this.marketIndex();
    const result = new Map<ManagedAsset, MarketSpec>();

    for (const asset of MANAGED_ASSETS) {
      const market = markets.get(asset);
      if (!market) {
        throw new Error("Required Hyperliquid market metadata is unavailable.");
      }

      result.set(asset, {
        asset,
        markPrice: market.markPrice,
        minNotionalUsd: MIN_NOTIONAL_USD,
        sizeDecimals: market.sizeDecimals
      });
    }

    return result;
  }

  async userRole(agentAddress: string) {
    return getHyperliquidUserRole(agentAddress);
  }

  async findByCloid(
    _masterAddress: string,
    _cloid: string
  ): Promise<KnownOrder> {
    void _masterAddress;
    void _cloid;
    throw new Error("Dry-run gateway cannot inspect executable orders.");
  }

  async writeIoc(
    _order: ExchangeOrder
  ): Promise<{ orderId?: string }> {
    void _order;
    throw new Error("Dry-run gateway cannot submit orders.");
  }
}