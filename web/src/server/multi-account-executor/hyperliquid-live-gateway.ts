import "server-only";
import {safeExecutionError} from "./safe-error";
import {fetchPortfolioMarkets,info} from "./portfolio-market-data";
import {portfolioPrice,signLeverageOne} from "./hyperliquid-l1-signing";
import type {PlannedAction} from "./types";

import { isAddress } from "viem";

import {
  HYPERLIQUID_REQUEST_TIMEOUT_MS,
  HyperliquidDryRunGateway
} from "./dry-run-gateway";
import type { ExchangeOrder, ExchangeCancellation } from "./engine";
import { buildSignedHyperliquidIocPayload, buildSignedHyperliquidCancelPayload } from "./hyperliquid-l1-signing";

const EXCHANGE_API_URL = "https://api.hyperliquid.xyz/exchange";

export class HyperliquidLiveGatewayError extends Error {
  constructor(message="Hyperliquid live order could not be verified safely.") {
    super(message);
    this.name="HyperliquidLiveGatewayError";
  }
}

export class HyperliquidOrderRejectedError extends Error {
  readonly definiteRejection = true;
  constructor() { super("Hyperliquid rejected the order."); }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function orderIdFrom(value: unknown): string | undefined {
  const record = asRecord(value);
  const order = asRecord(record?.order);
  const innerOrder = asRecord(order?.order);
  const candidate = innerOrder?.oid ?? order?.oid ?? record?.oid;
  return typeof candidate === "string" || typeof candidate === "number"
    ? String(candidate)
    : undefined;
}

export { normalizeHyperliquidOrderStatus } from "./order-status";

/**
 * Server-only IOC/cancellation gateway, reachable through the locked canonical
 * production runner. Browser routes and no-submit runs cannot instantiate it.
 */
export class HyperliquidLiveGateway extends HyperliquidDryRunGateway {
  constructor(private readonly liveFetcher: typeof fetch = fetch, portfolio = false, private readonly writeGuard?: () => Promise<void>) {
    super(liveFetcher, portfolio);
  }

  override async writeIoc(order: ExchangeOrder): Promise<{ orderId?: string }> {
    if(this.portfolio && !this.writeGuard) throw new HyperliquidLiveGatewayError();
    await this.writeGuard?.();
    if (!isAddress(order.masterAddress, { strict: false }) || !isAddress(order.agentAddress, { strict: false })) {
      throw new HyperliquidLiveGatewayError();
    }
    const markets = await this.marketIndex();
    const market = markets.get(order.asset);
    if (!market) throw new HyperliquidLiveGatewayError();
    let payload;
    try { payload = await buildSignedHyperliquidIocPayload(order, market); } catch { throw new HyperliquidOrderRejectedError(); }

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
    if (root?.status === "err" || (Array.isArray(statuses) && statuses.some((item) => typeof asRecord(item)?.error === "string"))) throw new HyperliquidOrderRejectedError();
    if (root?.status !== "ok" || exchangeResponse?.type !== "order" || !Array.isArray(statuses) || statuses.length !== 1) {
      throw new HyperliquidLiveGatewayError();
    }
    const status = asRecord(statuses[0]);
    const filled = asRecord(status?.filled) ?? (order.tif === "Alo" ? asRecord(status?.resting) : null);
    const orderId = orderIdFrom(filled);
    if (!filled || !orderId) throw new HyperliquidLiveGatewayError();
    return { orderId };
  }

  async prepareOrder(action:PlannedAction):Promise<PlannedAction> {
    const market=(await fetchPortfolioMarkets(this.liveFetcher)).get(action.asset);
    if(!market || !action.referencePrice || !action.tif)throw new HyperliquidOrderRejectedError();
    const buy=action.side==="buy";
    const bound=portfolioPrice(action.referencePrice*(buy?1.005:0.995),market.sizeDecimals,market.venue==="spot",!buy);
    let price=bound;
    if(action.tif==="Alo") {
      const book=await info<{levels:Array<Array<{px:string}>>}>(this.liveFetcher,{type:"l2Book",coin:market.coin});
      const raw=Number(book.levels[buy?0:1]?.[0]?.px);
      price=portfolioPrice(buy?Math.min(raw,bound):Math.max(raw,bound),market.sizeDecimals,market.venue==="spot",!buy);
    }
    return {...action,limitPrice:price};
  }
  async setLeverageOne(order:{asset:string;nonce:bigint;masterAddress:string;agentAddress:string;agentPrivateKey:`0x${string}`}):Promise<void> {
    if(!this.writeGuard)throw new HyperliquidLiveGatewayError();
    await this.writeGuard();
    const market=(await fetchPortfolioMarkets(this.liveFetcher)).get(order.asset);
    if(!market)throw new HyperliquidOrderRejectedError();
    const payload=await signLeverageOne(order,market);
    const response=await this.liveFetcher(EXCHANGE_API_URL,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload),cache:"no-store",signal:AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)});
    if(!response.ok)throw new HyperliquidLiveGatewayError(`updateLeverage HTTP ${response.status}`);
    const body=asRecord(await response.json());
    if(body?.status!=="ok")throw new HyperliquidLiveGatewayError(safeExecutionError({
      name:"ExchangeRejection",message:typeof body?.response==="string"?body.response:"updateLeverage response missing status ok"
    },"updateLeverage",[order.agentPrivateKey]));
  }
  override async cancelOrder(order: ExchangeCancellation): Promise<void> {
    if(this.portfolio && !this.writeGuard) throw new HyperliquidLiveGatewayError();
    await this.writeGuard?.();
    const markets = await this.marketIndex();
    const market = markets.get(order.asset);
    if (!market) throw new HyperliquidLiveGatewayError();
    const payload = await buildSignedHyperliquidCancelPayload(order, market);
    const response = await this.liveFetcher(EXCHANGE_API_URL, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload), cache: "no-store", signal: AbortSignal.timeout(HYPERLIQUID_REQUEST_TIMEOUT_MS)
    });
    if (!response.ok) throw new HyperliquidLiveGatewayError();
    const root = asRecord(await response.json());
    const exchangeResponse = asRecord(root?.response);
    const statuses = asRecord(exchangeResponse?.data)?.statuses;
    if (root?.status !== "ok" || exchangeResponse?.type !== "cancel" || !Array.isArray(statuses) || statuses.length !== 1 || statuses[0] !== "success") throw new HyperliquidLiveGatewayError();
  }
}
