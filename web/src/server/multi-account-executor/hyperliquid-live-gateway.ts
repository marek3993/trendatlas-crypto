import "server-only";

import { isAddress } from "viem";
import { validateHyperliquidAddress } from "@/lib/hyperliquid/address";
import {
  fetchHyperliquidMarketIndex,
  HYPERLIQUID_INFO_API_URL,
  HYPERLIQUID_REQUEST_TIMEOUT_MS,
  HyperliquidDryRunGateway
} from "./dry-run-gateway";
import type { ExchangeOrder, KnownOrder } from "./engine";
import { buildSignedHyperliquidIocPayload } from "./hyperliquid-l1-signing";

const EXCHANGE_API_URL = "https://api.hyperliquid.xyz/exchange";

export class HyperliquidLiveGatewayError extends Error {
  constructor() {
    super("Hyperliquid live order could not be verified safely.");
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function orderIdFrom(value: unknown): string | undefined {
  const record = asRecord(value);
  const order = asRecord(record?.order);
  const candidate = order?.oid ?? record?.oid;
  return typeof candidate === "string" || typeof candidate === "number"
    ? String(candidate)
    : undefined;
}

export function normalizeHyperliquidOrderStatus(value: unknown): KnownOrder {
  if (Array.isArray(value)) {
    return value.length > 0 ? normalizeHyperliquidOrderStatus(value[0]) : { state: "unknown" };
  }
  const record = asRecord(value);
  if (!record) return { state: "unknown" };
  if (record.data !== undefined) return normalizeHyperliquidOrderStatus(record.data);
  if (Array.isArray(record.statuses) && record.statuses.length > 0) {
    return normalizeHyperliquidOrderStatus(record.statuses[0]);
  }

  const order = asRecord(record.order);
  const rawStatus = record.status ?? order?.status;
  if (typeof rawStatus !== "string") return { state: "unknown", orderId: orderIdFrom(record) };
  const status = rawStatus.replace(/[^a-z0-9]/gi, "").toLowerCase();
  const orderId = orderIdFrom(record);
  if (status === "unknownoid" || status === "notfound" || status === "missing") return null;
  if (status === "filled") return { state: "filled", orderId };
  if (status === "open") return { state: "open", orderId };
  if (status.includes("reject") || status.includes("cancel") || status === "error") {
    return { state: "rejected", orderId };
  }
  return { state: "unknown", orderId };
}

/**
 * Server-only order gateway. No browser route, server action, scheduler, or live
 * runner imports this class; deployment stays inert until a separate rollout.
 */
export class HyperliquidLiveGateway extends HyperliquidDryRunGateway {
  constructor(private readonly liveFetcher: typeof fetch = fetch) {
    super(liveFetcher);
  }

  override async findByCloid(masterAddress: string, cloid: string): Promise<KnownOrder> {
    const validation = validateHyperliquidAddress(masterAddress);
    if (!validation.ok || !/^0x[0-9a-f]{32}$/.test(cloid)) throw new HyperliquidLiveGatewayError();
    try {
      const response = await this.liveFetcher(HYPERLIQUID_INFO_API_URL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ type: "orderStatus", user: validation.address, oid: cloid }),
        cache: "no-store",
        signal: AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)
      });
      if (!response.ok) return { state: "unknown" };
      return normalizeHyperliquidOrderStatus(await response.json() as unknown);
    } catch {
      return { state: "unknown" };
    }
  }

  override async writeIoc(order: ExchangeOrder): Promise<{ orderId?: string }> {
    if (!isAddress(order.masterAddress, { strict: false }) || !isAddress(order.agentAddress, { strict: false })) {
      throw new HyperliquidLiveGatewayError();
    }
    const markets = await fetchHyperliquidMarketIndex(this.liveFetcher);
    const market = markets.get(order.asset);
    if (!market) throw new HyperliquidLiveGatewayError();
    const payload = await buildSignedHyperliquidIocPayload(order, market);

    let response: Response;
    try {
      response = await this.liveFetcher(EXCHANGE_API_URL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        cache: "no-store",
        signal: AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)
      });
    } catch {
      throw new HyperliquidLiveGatewayError();
    }
    if (!response.ok) throw new HyperliquidLiveGatewayError();

    let body: unknown;
    try {
      body = await response.json() as unknown;
    } catch {
      throw new HyperliquidLiveGatewayError();
    }
    const root = asRecord(body);
    const exchangeResponse = asRecord(root?.response);
    const data = asRecord(exchangeResponse?.data);
    const statuses = data?.statuses;
    if (root?.status !== "ok" || exchangeResponse?.type !== "order" || !Array.isArray(statuses) || statuses.length !== 1) {
      throw new HyperliquidLiveGatewayError();
    }
    const status = asRecord(statuses[0]);
    const filled = asRecord(status?.filled);
    const orderId = orderIdFrom(filled);
    if (!filled || !orderId) throw new HyperliquidLiveGatewayError();
    return { orderId };
  }
}
