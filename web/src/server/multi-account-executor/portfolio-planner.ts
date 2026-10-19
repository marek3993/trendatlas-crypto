import type { AccountState, AuthorizedTarget, MarketSpec, Plan, PlannedAction } from "./types";
export const CLEAN_STRATEGY = "trendatlas_clean_5050_v1";
export function validWeights(raw: unknown): raw is Record<string, number> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const entries = Object.entries(raw);
  return entries.every(([asset, weight]) => /^[A-Z0-9]+$/.test(asset) && asset !== "BASE" && typeof weight === "number" && Number.isFinite(weight) && weight >= 0) && entries.reduce((sum, [, w]) => sum + w, 0) <= 1 + 1e-12;
}
export const sizeDown = (size: number, decimals: number) => Math.floor(size * 10 ** decimals) / 10 ** decimals;
export function routeFor(asset: string): string { return asset === "BTC" || asset === "ETH" ? `SPOT:${asset}` : asset; }
const validMarket = (m?: MarketSpec): m is MarketSpec => !!m && Number.isFinite(m.markPrice) && m.markPrice > 0 && Number.isInteger(m.sizeDecimals) && m.sizeDecimals >= 0 && m.sizeDecimals <= 8;

/** Port of portfolio.py: cost-reserved NAV, independent EXITs, no invented routes. */
export function buildPortfolioPlan(target: AuthorizedTarget, account: AccountState, markets: Map<string, MarketSpec>): Plan {
  const block = (reason: string): Plan => ({state: "BLOCKED", actions: [], reason});
  if (target.strategyVersion !== CLEAN_STRATEGY || target.stale !== false || !target.signalId || !target.closedDay || !validWeights(target.weights)) return block("invalid Clean portfolio");
  if (!Number.isFinite(account.equityUsd) || account.equityUsd <= 0 || account.positions.some(p => !Number.isFinite(p.size) || !Number.isFinite(p.markPrice) || p.markPrice <= 0)) return block("account equity or positions unavailable");
  if (account.openOrderCount !== 0) return block("open orders require ownership reconciliation");
  if (new Set(account.positions.map(p=>p.asset)).size !== account.positions.length) return block("duplicate positions");
  const blockers = [...(account.entryBlockers ?? [])];
  const desired = new Map<string, number>();
  for (const [logical, weight] of Object.entries(target.weights).sort()) {
    if (logical === "CASH" || weight === 0) continue;
    const key = routeFor(logical), market = markets.get(key);
    if (!validMarket(market) || market.entryAvailable === false || (key.startsWith("SPOT:") && market.venue !== "spot")) blockers.push(`MARKET_UNAVAILABLE:${logical}`);
    else desired.set(key, weight);
  }
  const positions = new Map(account.positions.map(p=>[p.asset,p]));
  const keys = [...new Set([...positions.keys(), ...desired.keys()])].sort();
  let nav = account.equityUsd;
  for (let i=0;i<20;i++) {
    const turnover = keys.reduce((sum,key)=>sum+Math.abs((desired.get(key)??0)*nav-(positions.get(key)?.size??0)*(positions.get(key)?.markPrice??0)),0);
    const next = Math.max(0,account.equityUsd-turnover*0.006);
    if (Math.abs(next-nav)<1e-10) { nav=next; break; }
    nav=next;
  }
  const exits: PlannedAction[]=[], entries: PlannedAction[]=[], dust: NonNullable<Plan['dust']>=[];
  const exitBlockers:string[]=[];
  for (const key of keys) {
    const pos=positions.get(key), market=markets.get(key), current=pos?.size??0;
    if (!validMarket(market)) { if(current) exitBlockers.push(`EXIT_MARKET_UNAVAILABLE:${key}`); continue; }
    const qty=sizeDown((desired.get(key)??0)*nav/market.markPrice,market.sizeDecimals);
    const delta=qty-current, closing=qty===0 && current>0;
    if (current>=0 && !closing && Math.abs(delta*market.markPrice)<=Math.max(0.01,account.equityUsd*0.01)) continue;
    const exit=current<0 || delta<0, side=current<0 || delta>0 ? "buy":"sell";
    const size=sizeDown(current<0 ? -current:Math.abs(delta),market.sizeDecimals);
    const reduceOnly=exit && market.venue!=="spot";
    if(size<=0 || (size*market.markPrice<market.minNotionalUsd && !reduceOnly)) { dust.push({asset:key,notionalUsd:Math.abs(delta)*market.markPrice}); continue; }
    const action:PlannedAction={action:exit?"EXIT":"ENTER",asset:key,size,requestedNotionalUsd:size*market.markPrice,reduceOnly,side,leg:0,venue:market.venue??"perp",referencePrice:market.markPrice};
    (exit?exits:entries).push(action);
  }
  if(exits.length) return {state:"EXIT",actions:exits.map((a,i)=>({...a,leg:i})),entryBlockedReason:[...exitBlockers,...blockers].join("; ")||undefined,dust};
  if(exitBlockers.length) return block(exitBlockers.join("; "));
  if(blockers.length) return block(blockers.join("; "));
  for(const entry of entries) {
    const free=entry.venue==="spot"?account.spotCashFreeUsd:account.marginAvailableUsd;
    if(free===undefined || !Number.isFinite(free) || entry.requestedNotionalUsd*1.006>free) return block(`INSUFFICIENT_${entry.venue?.toUpperCase()}_COLLATERAL`);
  }
  return {state:entries.length?"ENTER":"NO_ACTION",actions:entries.map((a,i)=>({...a,leg:i})),dust};
}
