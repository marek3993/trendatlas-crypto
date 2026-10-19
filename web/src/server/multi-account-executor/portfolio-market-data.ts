import "server-only";
import type {AccountState, MarketSpec} from "./types";
export const INFO_URL="https://api.hyperliquid.xyz/info";
export async function info<T>(fetcher: typeof fetch, payload: object): Promise<T> {
  // Hyperliquid rate-limits bursts of info reads; retry 429/5xx with bounded backoff.
  for(let attempt=0;;attempt++) {
    const response=await fetcher(INFO_URL,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload),cache:"no-store",signal:AbortSignal.timeout(8000)});
    if(response.ok) return await response.json() as T;
    if(attempt>=4 || !(response.status===429 || response.status>=500)) throw new Error(`exchange read unavailable (HTTP ${response.status})`);
    await new Promise(resolve=>setTimeout(resolve,1000*2**attempt));
  }
}
type Context={coin?:string;markPx?:string;midPx?:string};
type PerpMeta={universe:Array<{name:string;szDecimals:number;isDelisted?:boolean;maxLeverage?:number}>};
type SpotMeta={tokens:Array<{name:string;index:number;szDecimals:number}>;universe:Array<{name:string;index:number;tokens:[number,number]}>};
export type PortfolioMarket = MarketSpec & {assetIndex:number;coin:string;tokenIndex?:number;dex?:string};
// One run fetches the catalog many times; reuse it briefly to stay under the info rate limit.
let marketCache:{at:number;fetcher:typeof fetch;value:Promise<Map<string,PortfolioMarket>>}|undefined;
export async function fetchPortfolioMarkets(fetcher:typeof fetch):Promise<Map<string,PortfolioMarket>> {
  const now=Date.now();
  if(marketCache && marketCache.fetcher===fetcher && now-marketCache.at<30000) return new Map([...(await marketCache.value)].map(([k,v])=>[k,{...v}]));
  const value=loadPortfolioMarkets(fetcher);
  marketCache={at:now,fetcher,value};
  value.catch(()=>{if(marketCache?.value===value)marketCache=undefined;});
  return new Map([...(await value)].map(([k,v])=>[k,{...v}]));
}
async function loadPortfolioMarkets(fetcher:typeof fetch):Promise<Map<string,PortfolioMarket>> {
  const [spot,dexs]=await Promise.all([info<[SpotMeta,Context[]]>(fetcher,{type:"spotMetaAndAssetCtxs"}),info<Array<{name:string}|null>>(fetcher,{type:"perpDexs"})]);
  if(!Array.isArray(dexs) || !Array.isArray(spot) || !Array.isArray(spot[0]?.tokens) || !Array.isArray(spot[0]?.universe)) throw new Error("invalid market catalog");
  const result=new Map<string,PortfolioMarket>(), tokens=new Map(spot[0].tokens.map(t=>[t.index,t])), contexts=new Map(spot[1].map(c=>[c.coin,c]));
  const candidates=new Map<string,PortfolioMarket[]>();
  for(const pair of spot[0].universe) {
    const base=tokens.get(pair.tokens[0]),quote=tokens.get(pair.tokens[1]),ctx=contexts.get(pair.name);
    if(!base || quote?.name!=="USDC" || !ctx) continue;
    const mark=Number(ctx.markPx??ctx.midPx);
    if(!Number.isFinite(mark)||mark<=0) continue;
    const logical=base.name==="UBTC"?"BTC":base.name==="UETH"?"ETH":base.name;
    const market:PortfolioMarket={asset:`SPOT:PAIR${pair.index}`,logical,venue:"spot",coin:pair.name,assetIndex:10000+pair.index,tokenIndex:base.index,sizeDecimals:base.szDecimals,markPrice:mark,minNotionalUsd:10,entryAvailable:false};
    result.set(market.asset,market);
    const list=candidates.get(base.name)??[];list.push(market);candidates.set(base.name,list);
  }
  for(const [name,logical] of [["UBTC","BTC"],["UETH","ETH"]]) {
    const matches=candidates.get(name)??[];
    if(matches.length===1) { const m=matches[0];result.delete(m.asset);m.asset=`SPOT:${logical}`;m.entryAvailable=true;result.set(m.asset,m); }
  }
  const names=dexs.map((d,i)=>({name:d?.name??"",offset:i===0?0:100000+(i-1)*10000}));
  const perps=await Promise.all(names.map(d=>info<[PerpMeta,Context[]]>(fetcher,{type:"metaAndAssetCtxs",dex:d.name})));
  perps.forEach(([meta,ctx],index)=>meta.universe.forEach((m,i)=>{
    const mark=Number(ctx[i]?.markPx); if(!Number.isFinite(mark)||mark<=0) return;
    result.set(m.name,{asset:m.name,logical:m.name,venue:"perp",coin:m.name,dex:names[index].name,assetIndex:names[index].offset+i,sizeDecimals:m.szDecimals,markPrice:mark,minNotionalUsd:10,maxLeverage:m.maxLeverage,entryAvailable:!m.isDelisted && index===0 && m.name!=="BTC" && m.name!=="ETH"});
  }));
  if([...result.values()].some(m=>!Number.isInteger(m.assetIndex)||!Number.isInteger(m.sizeDecimals)||m.sizeDecimals<0||m.sizeDecimals>8)) throw new Error("invalid market precision");
  return result;
}
type Clearing={marginSummary:{accountValue:string;totalMarginUsed:string};withdrawable:string;assetPositions:Array<{position:{coin:string;szi:string;positionValue:string;leverage:{value:number}}}>};
type Spot={balances:Array<{coin:string;token:number;total:string;hold:string}>};
type Order={coin:string;oid:number;cloid?:string;sz:string;side:string};
const numeric=(v:unknown)=>{if(v===null||v===undefined||v==="")throw new Error("missing account number");const n=Number(v);if(!Number.isFinite(n))throw new Error("invalid account number");return n;};
export async function readPortfolioAccount(user:string,fetcher:typeof fetch,markets:Map<string,PortfolioMarket>):Promise<AccountState> {
  const dexNames=[...new Set(["",...[...markets.values()].filter(m=>m.venue==="perp").map(m=>m.dex??"")])];
  const [spot,abstraction,states,orderGroups]=await Promise.all([
    info<Spot>(fetcher,{type:"spotClearinghouseState",user}),info<string>(fetcher,{type:"userAbstraction",user}),
    Promise.all(dexNames.map(dex=>info<Clearing>(fetcher,{type:"clearinghouseState",user,dex}))),
    Promise.all(dexNames.map(dex=>info<Order[]>(fetcher,{type:"openOrders",user,dex})))
  ]);
  const positions:AccountState['positions']=[],entryBlockers:string[]=[];
  let equity=0,cash=0;
  for(const b of spot.balances) {
    const qty=numeric(b.total),hold=numeric(b.hold);if(!qty)continue;
    if(qty<0)entryBlockers.push("NEGATIVE_SPOT_BALANCE");
    if(b.coin==="USDC") {equity+=qty;cash+=Math.max(0,qty-hold);continue;}
    const matches=[...markets.values()].filter(m=>m.venue==="spot" && m.tokenIndex===b.token);
    if(matches.length!==1) {entryBlockers.push(`UNVALUED_SPOT_BALANCE:${b.coin}`);continue;}
    const m=matches[0];equity+=qty*m.markPrice;positions.push({asset:m.asset,size:qty,markPrice:m.markPrice,venue:"spot"});
  }
  for(const state of states)for(const {position:p} of state.assetPositions) {
    const size=numeric(p.szi);if(!size)continue;
    const mark=Math.abs(numeric(p.positionValue)/size);
    positions.push({asset:p.coin,size,markPrice:mark,venue:"perp",leverage:numeric(p.leverage.value)});
  }
  let margin=0;
  if(abstraction==="default" || abstraction==="disabled") {equity+=states.reduce((sum,s)=>sum+numeric(s.marginSummary.accountValue),0);margin=Math.max(0,numeric(states[0].withdrawable));}
  else if(abstraction==="unifiedAccount") margin=cash;
  else entryBlockers.push(`UNSUPPORTED_ABSTRACTION_FOR_ENTRY:${abstraction}`);
  // Unified holds are already excluded from cash. Never subtract margin twice.
  const byCoin=new Map([...markets.values()].map(m=>[m.coin,m.asset]));
  const uniqueOrders=[...new Map(orderGroups.flat().map(o=>[o.oid,o])).values()];
  const openOrders=uniqueOrders.map(o=>({asset:byCoin.get(o.coin)??o.coin,orderId:String(o.oid),cloid:o.cloid,size:numeric(o.sz),side:o.side==="B"?"buy" as const:"sell" as const}));
  return {equityUsd:equity,positions,openOrders,openOrderCount:openOrders.length,spotCashFreeUsd:cash,marginAvailableUsd:margin,abstraction,entryBlockers};
}
