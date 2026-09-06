import { type AccountState, type AuthorizedTarget, type ManagedAsset, type MarketSpec, type Plan, type PlannedAction } from "./types";

const MANAGED: readonly ManagedAsset[] = ["BTC", "ETH"];
const RESIDUAL_TOLERANCE_USD = 1;

function roundedSize(notional: number, market: MarketSpec): number {
  const unit = 10 ** market.sizeDecimals;
  return Math.floor((notional / market.markPrice) * unit) / unit;
}

function makeAction(action: PlannedAction["action"], asset: ManagedAsset, notional: number, market: MarketSpec, reduceOnly: boolean, leg: number): PlannedAction | null {
  const size = roundedSize(notional, market);
  return size > 0 ? { action, asset, requestedNotionalUsd: notional, size, reduceOnly, leg } : null;
}

export function buildPlan(target: AuthorizedTarget, account: AccountState, markets: Map<ManagedAsset, MarketSpec>): Plan {
  if (!Number.isFinite(account.equityUsd) || account.equityUsd < 0 || account.openOrderCount !== 0) return { state: "BLOCKED", actions: [], reason: "account state is ambiguous" };
  const positions = account.positions.filter((position) => position.size !== 0);
  if (positions.some((position) => !MANAGED.includes(position.asset as ManagedAsset) || position.size < 0)) return { state: "BLOCKED", actions: [], reason: "unsupported or short position present" };
  const managed = positions.filter((position) => MANAGED.includes(position.asset as ManagedAsset));
  if (managed.length > 1) return { state: "BLOCKED", actions: [], reason: "multiple managed positions present" };
  const current = managed[0];
  const targetNotional = account.equityUsd * target.exposure;
  if (target.asset === "CASH") {
    if (!current) return { state: "NO_ACTION", actions: [] };
    const market = markets.get(current.asset as ManagedAsset);
    if (!market) return { state: "BLOCKED", actions: [], reason: "missing market metadata" };
    const action = makeAction("EXIT", current.asset as ManagedAsset, Math.abs(current.size * current.markPrice), market, true, 0);
    return action ? { state: "EXIT", actions: [action] } : { state: "BLOCKED", actions: [], reason: "exit is below executable precision" };
  }
  const targetMarket = markets.get(target.asset);
  if (!targetMarket) return { state: "BLOCKED", actions: [], reason: "missing target metadata" };
  if (!current) {
    if (targetNotional < targetMarket.minNotionalUsd) return { state: "BLOCKED", actions: [], reason: "target is below exchange minimum" };
    const action = makeAction("ENTER", target.asset, targetNotional, targetMarket, false, 0);
    return action && action.size * targetMarket.markPrice >= targetMarket.minNotionalUsd ? { state: "ENTER", actions: [action] } : { state: "BLOCKED", actions: [], reason: "target is below exchange minimum" };
  }
  if (current.asset !== target.asset) {
    const currentMarket = markets.get(current.asset as ManagedAsset);
    if (!currentMarket || targetNotional < targetMarket.minNotionalUsd) return { state: "BLOCKED", actions: [], reason: "rotation cannot be executed safely" };
    const exit = makeAction("EXIT", current.asset as ManagedAsset, Math.abs(current.size * current.markPrice), currentMarket, true, 0);
    const enter = makeAction("ENTER", target.asset, targetNotional, targetMarket, false, 1);
    return exit && enter ? { state: "ROTATE", actions: [exit, enter] } : { state: "BLOCKED", actions: [], reason: "rotation precision is invalid" };
  }
  const currentNotional = Math.abs(current.size * current.markPrice);
  const delta = targetNotional - currentNotional;
  if (Math.abs(delta) <= RESIDUAL_TOLERANCE_USD) return { state: "NO_ACTION", actions: [] };
  if (Math.abs(delta) < targetMarket.minNotionalUsd) return { state: "NO_ACTION", actions: [], reason: "precision-limited residual below exchange minimum" };
  const action = makeAction("RESIZE", target.asset, Math.abs(delta), targetMarket, delta < 0, 0);
  return action ? { state: "RESIZE", actions: [action] } : { state: "BLOCKED", actions: [], reason: "resize precision is invalid" };
}
