import { normalizeTargetAsset, type AccountState, type AuthorizedTarget, type MarketSpec, type Plan, type PlannedAction } from "./types";

const RESIDUAL_TOLERANCE_USD = 1;

function validMarket(market: MarketSpec | undefined): market is MarketSpec {
  return !!market && Number.isFinite(market.markPrice) && market.markPrice > 0 && Number.isInteger(market.sizeDecimals) && market.sizeDecimals >= 0 && market.sizeDecimals <= 8 && Number.isFinite(market.minNotionalUsd) && market.minNotionalUsd >= 0;
}

function roundedSize(notional: number, market: MarketSpec): number {
  const unit = 10 ** market.sizeDecimals;
  return Math.floor((notional / market.markPrice) * unit + 1e-9) / unit;
}

export function validTarget(target: AuthorizedTarget): boolean {
  return normalizeTargetAsset(target.asset) === target.asset && target.stale === false && !!target.signalId && !!target.closedDay && !!target.strategyVersion && Number.isFinite(target.exposure) && (target.asset === "CASH" ? target.exposure === 0 : target.exposure > 0) && (target.executionGate === "approved" || target.executionGate === "no_action");
}

/** EXIT metadata is evaluated independently; ENTRY is indicative until fresh read-back. */
export function buildPlan(target: AuthorizedTarget, account: AccountState, markets: Map<string, MarketSpec>): Plan {
  if (!validTarget(target)) return { state: "BLOCKED", actions: [], reason: "strategy target is invalid" };
  if (!Number.isFinite(account.equityUsd) || !Array.isArray(account.positions) || account.positions.some((position) => !Number.isFinite(position.size) || !Number.isFinite(position.markPrice) || position.markPrice <= 0 || normalizeTargetAsset(position.asset) !== position.asset)) return { state: "BLOCKED", actions: [], reason: "account state is ambiguous" };
  if (account.openOrderCount !== 0) return { state: "BLOCKED", actions: [], reason: "open orders require ownership reconciliation" };
  const positions = account.positions.filter(({ size }) => size !== 0).sort((a, b) => a.asset.localeCompare(b.asset));
  if (new Set(positions.map(({ asset }) => asset)).size !== positions.length) return { state: "BLOCKED", actions: [], reason: "duplicate account positions are ambiguous" };
  const unwanted = positions.filter(({ asset, size }) => target.asset === "CASH" || asset !== target.asset || size < 0);
  const exits: PlannedAction[] = [];
  for (const position of unwanted) {
    const market = markets.get(position.asset);
    if (!validMarket(market)) return { state: exits.length ? "EXIT" : "BLOCKED", actions: exits, reason: "exit market metadata is unavailable" };
    // Close the exact position, including dust; reduce-only closes need no entry minimum.
    const size = Number(Math.abs(position.size).toFixed(market.sizeDecimals));
    if (size <= 0 || Math.abs(size - Math.abs(position.size)) > 1e-10) return { state: exits.length ? "EXIT" : "BLOCKED", actions: exits, reason: "exit precision is invalid" };
    exits.push({ action: "EXIT", asset: position.asset, requestedNotionalUsd: size * market.markPrice, size, reduceOnly: true, side: position.size < 0 ? "buy" : "sell", leg: exits.length });
  }
  if (target.asset === "CASH") return { state: exits.length ? "EXIT" : "NO_ACTION", actions: exits };
  const blocked = (reason: string): Plan => exits.length ? { state: "ROTATE", actions: exits, entryBlockedReason: reason } : { state: "BLOCKED", actions: [], reason };
  const market = markets.get(target.asset);
  if (!validMarket(market)) return blocked("target market metadata is unavailable");
  const current = positions.find(({ asset, size }) => asset === target.asset && size > 0);
  const targetNotional = account.equityUsd * target.exposure;
  if (!Number.isFinite(targetNotional) || targetNotional <= 0) return blocked("target sizing is invalid");
  const currentNotional = current ? current.size * market.markPrice : 0;
  const delta = targetNotional - currentNotional;
  if (current && Math.abs(delta) <= RESIDUAL_TOLERANCE_USD) return { state: exits.length ? "EXIT" : "NO_ACTION", actions: exits };
  if (current && Math.abs(delta) < market.minNotionalUsd) return { state: exits.length ? "EXIT" : "NO_ACTION", actions: exits, reason: "precision-limited residual below exchange minimum" };
  const size = roundedSize(Math.abs(delta), market);
  if (size <= 0 || size * market.markPrice < market.minNotionalUsd) return blocked("target is below exchange minimum or precision");
  // Maximum leverage supplies a lower bound; exchange validates actual account leverage.
  // Reductions and EXIT previews never consult available entry margin.
  if (delta > 0 && exits.length === 0 && account.marginAvailableUsd !== undefined) {
    const required = market.maxLeverage && market.maxLeverage > 0 ? size * market.markPrice / market.maxLeverage : 0;
    if (!Number.isFinite(account.marginAvailableUsd) || account.marginAvailableUsd <= 0 || required > account.marginAvailableUsd) return blocked("entry margin is insufficient");
  }
  const action: PlannedAction = { action: current ? "RESIZE" : "ENTER", asset: target.asset, requestedNotionalUsd: Math.abs(delta), size, reduceOnly: delta < 0, side: delta < 0 ? "sell" : "buy", leg: exits.length };
  return { state: exits.length ? "ROTATE" : current ? "RESIZE" : "ENTER", actions: [...exits, action] };
}
