import "server-only";

import {
  getHyperliquidPerformanceInputs,
  type HyperliquidFill,
  type HyperliquidFunding,
  type HyperliquidNonFundingLedgerUpdate,
  type HyperliquidPortfolioResponse,
  type HyperliquidAccountSnapshot
} from "@/lib/hyperliquid/info";

const DAY_MS = 24 * 60 * 60 * 1000;
const HISTORY_PAGE_LIMIT = 2_000;
const EPSILON = 1e-8;

type Valuation = { at: number; equityUsd: number };
type CashFlow = { at: number; depositsUsd: number; withdrawalsUsd: number };
type PerformanceEvent = CashFlow & { tradingPnlUsd: number; feesUsd: number; fundingUsd: number };

export type PerformanceBreakdown = {
  tradingPnlUsd: number;
  feesUsd: number;
  fundingUsd: number;
  depositsUsd: number;
  withdrawalsUsd: number;
};

export type PerformanceWindow = {
  available: boolean;
  reason: string | null;
  pnlUsd: number | null;
  returnPct: number | null;
  breakdown: PerformanceBreakdown | null;
};

export type HyperliquidAccountPerformance = {
  address: string;
  snapshot: HyperliquidAccountSnapshot;
  asOfMs: number;
  liveGenesisAtMs: number | null;
  liveGenesisDay: string | null;
  historyDays: number;
  totalLivePnlUsd: number | null;
  cashFlowAdjustedReturnPct: number | null;
  cashFlowAdjustedReturnAvailable: boolean;
  cashFlowAdjustedReturnReason: string | null;
  breakdown: PerformanceBreakdown | null;
  windows: { today: PerformanceWindow; "30d": PerformanceWindow; "90d": PerformanceWindow };
};

export type PerformanceCalculationInput = {
  address: string;
  snapshot: HyperliquidAccountSnapshot;
  asOfMs: number;
  portfolio: HyperliquidPortfolioResponse;
  fills: HyperliquidFill[];
  funding: HyperliquidFunding[];
  nonFundingLedgerUpdates: HyperliquidNonFundingLedgerUpdate[];
};

function finiteNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function eventTime(value: { time?: number; timestamp?: number }): number | null {
  const timestamp = finiteNumber(value.time ?? value.timestamp);
  return timestamp !== null && Number.isSafeInteger(timestamp) && timestamp >= 0 ? timestamp : null;
}

function emptyBreakdown(): PerformanceBreakdown {
  return { tradingPnlUsd: 0, feesUsd: 0, fundingUsd: 0, depositsUsd: 0, withdrawalsUsd: 0 };
}

function addBreakdown(target: PerformanceBreakdown, event: PerformanceEvent): void {
  target.tradingPnlUsd += event.tradingPnlUsd;
  target.feesUsd += event.feesUsd;
  target.fundingUsd += event.fundingUsd;
  target.depositsUsd += event.depositsUsd;
  target.withdrawalsUsd += event.withdrawalsUsd;
}

function rounded(value: number): number {
  return Math.round(value * 1e8) / 1e8;
}

function roundBreakdown(value: PerformanceBreakdown): PerformanceBreakdown {
  return {
    tradingPnlUsd: rounded(value.tradingPnlUsd),
    feesUsd: rounded(value.feesUsd),
    fundingUsd: rounded(value.fundingUsd),
    depositsUsd: rounded(value.depositsUsd),
    withdrawalsUsd: rounded(value.withdrawalsUsd)
  };
}

function utcDay(timestamp: number): string {
  return new Date(timestamp).toISOString().slice(0, 10);
}

function startOfUtcDay(timestamp: number): number {
  const day = new Date(timestamp);
  return Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate());
}

function allTimeValuations(portfolio: HyperliquidPortfolioResponse, current: Valuation): Valuation[] {
  const allTime = portfolio.find(([period]) => period === "allTime")?.[1]?.accountValueHistory;
  const byTimestamp = new Map<number, number>();
  for (const row of Array.isArray(allTime) ? allTime : []) {
    const timestamp = finiteNumber(row[0]);
    const equityUsd = finiteNumber(row[1]);
    if (timestamp !== null && equityUsd !== null && timestamp >= 0 && equityUsd >= 0) byTimestamp.set(timestamp, equityUsd);
  }
  byTimestamp.set(current.at, current.equityUsd);
  return [...byTimestamp.entries()]
    .map(([at, equityUsd]) => ({ at, equityUsd }))
    .sort((left, right) => left.at - right.at);
}

function eventsFromInput(input: PerformanceCalculationInput): PerformanceEvent[] {
  const events: PerformanceEvent[] = [];
  for (const fill of input.fills) {
    const at = eventTime(fill);
    if (at === null) continue;
    events.push({
      at,
      tradingPnlUsd: finiteNumber(fill.closedPnl) ?? 0,
      feesUsd: -(Math.abs(finiteNumber(fill.fee) ?? 0)),
      fundingUsd: 0,
      depositsUsd: 0,
      withdrawalsUsd: 0
    });
  }
  for (const funding of input.funding) {
    const at = eventTime(funding);
    const amount = finiteNumber(funding.delta?.usdc ?? funding.usdc);
    if (at === null || amount === null) continue;
    events.push({ at, tradingPnlUsd: 0, feesUsd: 0, fundingUsd: amount, depositsUsd: 0, withdrawalsUsd: 0 });
  }
  const address = input.address.toLowerCase();
  for (const update of input.nonFundingLedgerUpdates) {
    const at = eventTime(update);
    const delta = update.delta;
    const kind = delta?.type?.trim() ?? "";
    const amount = finiteNumber(delta?.usdc ?? delta?.usdcValue ?? delta?.amount);
    if (at === null || amount === null || !kind) continue;
    const incomingSend = kind === "send" && delta?.destination?.toLowerCase() === address;
    const outgoingSend = kind === "send" && delta?.user?.toLowerCase() === address;
    events.push({
      at,
      tradingPnlUsd: 0,
      feesUsd: 0,
      fundingUsd: 0,
      depositsUsd: kind === "deposit" || incomingSend ? Math.abs(amount) : 0,
      withdrawalsUsd: kind === "withdraw" || outgoingSend ? Math.abs(amount) : 0
    });
  }
  return events.sort((left, right) => left.at - right.at);
}

function valuationAtOrBefore(valuations: Valuation[], timestamp: number): Valuation | null {
  for (let index = valuations.length - 1; index >= 0; index -= 1) {
    if (valuations[index].at <= timestamp) return valuations[index];
  }
  return null;
}

function eventsAfter(events: PerformanceEvent[], startExclusive: number, endInclusive: number): PerformanceEvent[] {
  return events.filter((event) => event.at > startExclusive && event.at <= endInclusive);
}

function sumBreakdown(events: PerformanceEvent[]): PerformanceBreakdown {
  const result = emptyBreakdown();
  events.forEach((event) => addBreakdown(result, event));
  return roundBreakdown(result);
}

function unavailable(reason: string): PerformanceWindow {
  return { available: false, reason, pnlUsd: null, returnPct: null, breakdown: null };
}

function calculateWindow(
  valuations: Valuation[],
  events: PerformanceEvent[],
  asOfMs: number,
  historyDays: number,
  requiredDays: number
): PerformanceWindow {
  if (historyDays < requiredDays) return unavailable("insufficient_live_history");
  const windowStart = startOfUtcDay(asOfMs) - (requiredDays - 1) * DAY_MS;
  const start = valuationAtOrBefore(valuations, windowStart);
  const end = valuations.at(-1);
  if (!start || !end || end.at <= start.at) return unavailable("insufficient_equity_valuation_points");
  const windowEvents = eventsAfter(events, start.at, end.at);
  const breakdown = sumBreakdown(windowEvents);
  const pnlUsd = rounded(end.equityUsd - start.equityUsd - breakdown.depositsUsd + breakdown.withdrawalsUsd);
  const hasCashFlow = Math.abs(breakdown.depositsUsd - breakdown.withdrawalsUsd) > EPSILON;
  if (hasCashFlow) {
    return { available: true, reason: "cash_flow_without_intraday_valuation", pnlUsd, returnPct: null, breakdown };
  }
  if (start.equityUsd <= EPSILON) {
    return { available: true, reason: "invalid_starting_equity", pnlUsd, returnPct: null, breakdown };
  }
  return {
    available: true,
    reason: null,
    pnlUsd,
    returnPct: rounded(((end.equityUsd / start.equityUsd) - 1) * 100),
    breakdown
  };
}

function unavailablePerformance(input: PerformanceCalculationInput): HyperliquidAccountPerformance {
  const noHistory = unavailable("insufficient_live_history");
  return {
    address: input.address,
    snapshot: input.snapshot,
    asOfMs: input.asOfMs,
    liveGenesisAtMs: null,
    liveGenesisDay: null,
    historyDays: 0,
    totalLivePnlUsd: null,
    cashFlowAdjustedReturnPct: null,
    cashFlowAdjustedReturnAvailable: false,
    cashFlowAdjustedReturnReason: "insufficient_live_history",
    breakdown: null,
    windows: { today: noHistory, "30d": noHistory, "90d": noHistory }
  };
}

/**
 * Calculates only from the selected account's documented exchange responses.
 * A response that reaches the documented 2,000-item history limit is rejected
 * as incomplete instead of being used to manufacture an all-time result.
 */
export function calculateHyperliquidAccountPerformance(input: PerformanceCalculationInput): HyperliquidAccountPerformance {
  if (input.fills.length >= HISTORY_PAGE_LIMIT || input.funding.length >= HISTORY_PAGE_LIMIT || input.nonFundingLedgerUpdates.length >= HISTORY_PAGE_LIMIT) {
    return unavailablePerformance(input);
  }
  const valuations = allTimeValuations(input.portfolio, { at: input.asOfMs, equityUsd: input.snapshot.accountEquityUsd });
  const genesis = valuations[0];
  const end = valuations.at(-1);
  if (!genesis || !end || end.at <= genesis.at) return unavailablePerformance(input);

  const events = eventsFromInput(input);
  const historyDays = Math.floor((startOfUtcDay(end.at) - startOfUtcDay(genesis.at)) / DAY_MS) + 1;
  const inceptionEvents = eventsAfter(events, genesis.at, end.at);
  const breakdown = sumBreakdown(inceptionEvents);
  const totalLivePnlUsd = rounded(end.equityUsd - genesis.equityUsd - breakdown.depositsUsd + breakdown.withdrawalsUsd);
  const hasCashFlow = Math.abs(breakdown.depositsUsd - breakdown.withdrawalsUsd) > EPSILON;
  const returnAvailable = !hasCashFlow && genesis.equityUsd > EPSILON;
  const cashFlowAdjustedReturnPct = returnAvailable ? rounded(((end.equityUsd / genesis.equityUsd) - 1) * 100) : null;
  const returnReason = returnAvailable ? null : (hasCashFlow ? "cash_flow_without_intraday_valuation" : "invalid_starting_equity");

  return {
    address: input.address,
    snapshot: input.snapshot,
    asOfMs: input.asOfMs,
    liveGenesisAtMs: genesis.at,
    liveGenesisDay: utcDay(genesis.at),
    historyDays,
    totalLivePnlUsd,
    cashFlowAdjustedReturnPct,
    cashFlowAdjustedReturnAvailable: returnAvailable,
    cashFlowAdjustedReturnReason: returnReason,
    breakdown,
    windows: {
      today: calculateWindow(valuations, events, input.asOfMs, historyDays, 1),
      "30d": calculateWindow(valuations, events, input.asOfMs, historyDays, 30),
      "90d": calculateWindow(valuations, events, input.asOfMs, historyDays, 90)
    }
  };
}

export async function getHyperliquidAccountPerformance(rawAddress: string): Promise<HyperliquidAccountPerformance> {
  const inputs = await getHyperliquidPerformanceInputs(rawAddress);
  return calculateHyperliquidAccountPerformance({ address: inputs.snapshot.address, ...inputs });
}
