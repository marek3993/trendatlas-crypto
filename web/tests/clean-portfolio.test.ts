import {afterEach,describe,expect,it,vi} from "vitest";
import {privateKeyToAccount} from "viem/accounts";
import {createEnvironmentAgentSecretProtector} from "@/lib/hyperliquid/agent-authorization";
import {parseCleanSignal} from "@/server/multi-account-executor/clean-authority";
import {buildPortfolioPlan,validWeights} from "@/server/multi-account-executor/portfolio-planner";
import {runPortfolioAccount} from "@/server/multi-account-executor/portfolio-engine";
import {preflightMultiAccountCandidates} from "@/server/multi-account-executor/live-preflight";
import {portfolioPrice,buildSignedHyperliquidIocPayload} from "@/server/multi-account-executor/hyperliquid-l1-signing";
import type {ExchangeGateway,ExecutionRepository,ExchangeOrder,JournalAction,KnownOrder} from "@/server/multi-account-executor/engine";
import type {AccountState,AuthorizedTarget,MarketSpec} from "@/server/multi-account-executor/types";
const now=Date.parse("2026-10-18T00:10:00Z");
const target=(weights:Record<string,number>):AuthorizedTarget=>({weights,strategyVersion:"trendatlas_clean_5050_v1",closedDay:"2026-10-17",holdingDay:"2026-10-18",asset:"PORTFOLIO",exposure:Object.values(weights).reduce((s,w)=>s+w,0),signalId:"clean-day",stale:false,executionGate:"approved"});
const markets=new Map<string,MarketSpec>(["SPOT:BTC","SPOT:ETH","SOL","BTC","DOGE"].map(asset=>[asset,{asset,venue:asset.startsWith("SPOT:")?"spot":"perp",sizeDecimals:4,markPrice:100,minNotionalUsd:10}]));
const account=(equityUsd=1000):AccountState=>({equityUsd,positions:[],openOrders:[],openOrderCount:0,spotCashFreeUsd:equityUsd,marginAvailableUsd:equityUsd,abstraction:"unifiedAccount"});
const key=`0x${"11".repeat(32)}` as const,agent=privateKeyToAccount(key).address,master=`0x${"aa".repeat(20)}`;
const oldKek=process.env.TRENDATLAS_AGENT_KEK_B64;
afterEach(()=>{vi.restoreAllMocks();if(oldKek===undefined)delete process.env.TRENDATLAS_AGENT_KEK_B64;else process.env.TRENDATLAS_AGENT_KEK_B64=oldKek;});
function harness(initial=account()) {
  process.env.TRENDATLAS_AGENT_KEK_B64=Buffer.alloc(32,7).toString("base64");
  const candidate={userId:"u",accountId:"a",masterAddress:master,agentAddress:agent,agentName:"TA-test",authorizationId:"auth",connectionStatus:"read_only_connected",authorizationStatus:"authorized",ownershipVerifiedAt:"yes",agentAuthorizedAt:"yes",autoTradingRequested:true,executionStatus:"ready" as const,hasEncryptedSecret:true,encryptedSecret:createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).encrypt(key)};
  let state=structuredClone(initial), clock=now;
  const journal=new Map<string,JournalAction>(),known=new Map<string,KnownOrder>(),events:string[]=[],orders:ExchangeOrder[]=[];
  const repo:ExecutionRepository={listMultiAccountCandidates:async()=>[candidate],tryAcquire:async()=>true,renewLease:async()=>true,release:async()=>{},reserveNonce:async()=>BigInt(clock),createRun:async()=>"run",isRunCompleted:async()=>false,readActions:async()=>[...journal.values()],readUnresolvedActions:async()=>[],markActionVerified:async()=>{},isManagedOrder:async()=>true,finishRun:async()=>{},setAccountStatus:async()=>{},recordAction:async(runId,action,cloid,submission,orderId,expiresAtMs)=>{events.push(`journal:${submission}`);const old=journal.get(cloid);journal.set(cloid,{runId,action,cloid,state:submission,orderId:orderId??old?.orderId,expiresAtMs:expiresAtMs??old?.expiresAtMs});}};
  const fill=(o:ExchangeOrder,fraction=1)=>{const p=state.positions.find(p=>p.asset===o.asset);const size=(p?.size??0)+(o.side==="sell"?-1:1)*o.size*fraction;state.positions=state.positions.filter(p=>p.asset!==o.asset);if(Math.abs(size)>1e-9)state.positions.push({asset:o.asset,size,markPrice:100,venue:o.venue,leverage:1});};
  const exchange:ExchangeGateway={readAccount:async()=>{events.push("read");return structuredClone(state);},readMarkets:async()=>new Map(markets),userRole:async()=>({role:"agent",user:master}),agentAuthorization:async()=>({authorized:true,validUntilMs:now+86400000}),prepareOrder:async a=>({...a,limitPrice:100}),setLeverageOne:async()=>{events.push("1x");},findByCloid:async(_u,c)=>known.get(c)??null,cancelOrder:async o=>{events.push("cancel");const match=[...known].find(([,k])=>k?.orderId===o.orderId);if(match)known.set(match[0],{state:"cancelled",orderId:o.orderId});state.openOrders=[];state.openOrderCount=0;},writeIoc:async o=>{expect(journal.get(o.cloid)?.state).toBe("AMBIGUOUS");orders.push(o);events.push(`write:${o.action}:${o.tif}`);fill(o);known.set(o.cloid,{state:"filled",orderId:String(orders.length)});return {orderId:String(orders.length)};}};
  const runtime={now:()=>clock,wait:async(ms:number)=>{clock+=ms;},makerWaitMs:10000};
  return {repo,exchange,candidate,journal,known,events,orders,runtime,fill,get state(){return state;},set state(v){state=v;},run:(t:AuthorizedTarget)=>runPortfolioAccount(repo,exchange,candidate,t,runtime)};
}
describe("Clean portfolio contract",()=>{
  it("accepts exact D-close targets for D+1 without shifting",()=>{const signal={schema_version:1,strategy_id:"trendatlas_clean_5050_v1",mode:"SIGNAL_ONLY",decision_closed_day_utc:"2026-10-17",rozhodnute_na_close_utc:"2026-10-17T23:59:59.999Z",drzat_pocas_dna_utc:"2026-10-18",ciel_vahy:{BTC:.5,ETH:.5},gross_target_exposure:1,params:{regime_min:.5,universe_n:10,top_k:1,switch_h:.25,btc_pref:.25},input_sha256:"a".repeat(64),code_sha256:"b".repeat(64)};expect(parseCleanSignal(signal,new Date(now)).weights).toEqual({BTC:.5,ETH:.5});expect(()=>parseCleanSignal({...signal,drzat_pocas_dna_utc:"2026-10-19"},new Date(now))).toThrow();expect(()=>parseCleanSignal(signal,new Date(now+86400000))).toThrow();});
  it.each([{BTC:1.1},{BTC:-.1},{BTC:NaN},{BASE:1},{BTC:.5,CASH:.6}])("rejects invalid weights %j",weights=>expect(validWeights(weights)).toBe(false));
  it("scales spot weights to individual equity after cost reserve",()=>{const a=buildPortfolioPlan(target({BTC:.5,ETH:.5}),account(1000),markets),b=buildPortfolioPlan(target({BTC:.5,ETH:.5}),account(2000),markets);expect(a.actions.map(x=>x.asset)).toEqual(["SPOT:BTC","SPOT:ETH"]);expect(a.actions.reduce((s,x)=>s+x.requestedNotionalUsd,0)).toBeLessThan(1000);expect(b.actions[0].size/a.actions[0].size).toBeCloseTo(2,3);});
  it("exits old BTC perp before buying BTC spot and independent exits survive missing entries",()=>{const a=account();a.positions=[{asset:"BTC",size:5,markPrice:100,venue:"perp",leverage:10},{asset:"DOGE",size:-2,markPrice:100,venue:"perp",leverage:5}];const p=buildPortfolioPlan(target({BTC:.5,UNKNOWN:.5}),a,markets);expect(p.actions.map(x=>[x.asset,x.side,x.reduceOnly])).toEqual([["BTC","sell",true],["DOGE","buy",true]]);expect(p.entryBlockedReason).toContain("UNKNOWN");});
  it("reduces an overweight spot with no reduce-only flag",()=>{const a=account();a.positions=[{asset:"SPOT:BTC",size:8,markPrice:100,venue:"spot"}];expect(buildPortfolioPlan(target({BTC:.5}),a,markets).actions[0]).toMatchObject({action:"EXIT",reduceOnly:false,side:"sell"});});
  it("blocks missing spot cash without transferring from perps",()=>{const a=account();a.spotCashFreeUsd=0;expect(buildPortfolioPlan(target({BTC:1}),a,markets).reason).toContain("COLLATERAL");});
  it("reports dust and closes tiny perp positions reduce-only",()=>{const a=account();a.positions=[{asset:"SPOT:BTC",size:.01,markPrice:100,venue:"spot"},{asset:"DOGE",size:.01,markPrice:100,venue:"perp"}];const p=buildPortfolioPlan(target({}),a,markets);expect(p.dust).toHaveLength(1);expect(p.actions[0]).toMatchObject({asset:"DOGE",reduceOnly:true});});
});
describe("portfolio execution recovery",()=>{
  it.each(["NOT_SUBMITTED","AMBIGUOUS"] as const)("preflight distinguishes a %s intent after a crash",async state=>{
    vi.spyOn(Date,"now").mockReturnValue(now);
    const h=harness(),action=buildPortfolioPlan(target({BTC:1}),h.state,markets).actions[0];
    h.repo.readUnresolvedActions=async()=>[{action,cloid:"prepared-only",state}];
    const result=await preflightMultiAccountCandidates([h.candidate],target({BTC:1}),h.exchange,h.repo);
    expect(result[0].status).toBe(state==="NOT_SUBMITTED"?"READY":"FAILED");
    expect(h.orders).toHaveLength(0);
  });
  it.each(["readActions","readUnresolvedActions","reserveNonce","prepareOrder","setLeverageOne"])("records a safe %s error in receipt, DB journal and systemd journal",async step=>{
    const h=harness(),log=vi.spyOn(console,"error").mockImplementation(()=>{}),finish=vi.spyOn(h.repo,"finishRun");
    const error=new TypeError(`failure key ${key} nonce ${"ab".repeat(32)} kek ${process.env.TRENDATLAS_AGENT_KEK_B64}`);
    const owner=step in h.repo?h.repo:h.exchange;
    Object.assign(owner,{[step]:async()=>{throw error;}});
    const result=await h.run(target({BTC:.5,SOL:.5}));
    expect(result).toMatchObject({status:"FAILED",orderRequested:false});
    expect(result.reason).toContain(`${step}: TypeError: failure`);
    expect(result.reason!.length).toBeLessThanOrEqual(200);
    expect(result.reason).not.toContain(key);expect(result.reason).not.toContain(process.env.TRENDATLAS_AGENT_KEK_B64);
    expect(finish).toHaveBeenCalledWith("run","FAILED",1000,result.reason);
    expect(JSON.parse(log.mock.calls[0][0])).toMatchObject({event:"CLEAN_EXECUTION_ERROR",reason:result.reason});
    expect(h.orders).toHaveLength(0);
  });
  it("retains the original receipt error if finalizing the journal also fails",async()=>{
    const h=harness(),log=vi.spyOn(console,"error").mockImplementation(()=>{});
    h.exchange.prepareOrder=async()=>{throw new Error("book unavailable");};
    h.repo.finishRun=async()=>{throw new Error("database unavailable");};
    const result=await h.run(target({BTC:1}));
    expect(result.reason).toBe("prepareOrder: Error: book unavailable");
    expect(result.orderRequested).toBe(false);
    expect(log.mock.calls.map(c=>JSON.parse(c[0]).event)).toEqual(["CLEAN_EXECUTION_ERROR","CLEAN_EXECUTION_JOURNAL_ERROR"]);
  });
  it("completes reductions before entries and sets 1x",async()=>{const h=harness();h.state.positions=[{asset:"DOGE",size:5,markPrice:100,venue:"perp",leverage:5}];const r=await h.run(target({BTC:.5,SOL:.5}));expect(r.status).toBe("FILLED_AND_ALIGNED");expect(h.orders[0].action).toBe("EXIT");expect(h.events).toContain("1x");expect(h.orders.map(o=>o.asset)).toEqual(["DOGE","SOL","SPOT:BTC"]);});
  it("waits, cancels, verifies and sends only residual IOC after partial maker fill",async()=>{const h=harness();const normal=h.exchange.writeIoc;h.exchange.writeIoc=async o=>{if(o.tif==="Ioc")return normal(o);h.orders.push(o);h.fill(o,.4);h.known.set(o.cloid,{state:"open",orderId:"10"});h.state.openOrders=[{asset:o.asset,orderId:"10",cloid:o.cloid}];h.state.openOrderCount=1;return {orderId:"10"};};expect((await h.run(target({BTC:1}))).status).toBe("FILLED_AND_ALIGNED");expect(h.events).toContain("cancel");expect(h.orders[1].tif).toBe("Ioc");expect(h.orders[1].size).toBeLessThan(h.orders[0].size*.62);});
  it("recovers an accepted fill despite a lost HTTP response",async()=>{const h=harness(),normal=h.exchange.writeIoc;h.exchange.writeIoc=async o=>{await normal(o);throw new Error("lost");};expect((await h.run(target({BTC:1}))).status).toBe("FILLED_AND_ALIGNED");expect(h.orders).toHaveLength(1);});
  it("never resubmits an ambiguous request across restart",async()=>{const h=harness();h.exchange.writeIoc=async o=>{h.orders.push(o);throw new Error("timeout");};expect((await h.run(target({BTC:1}))).status).toBe("UNKNOWN_SUBMISSION_STATE");expect((await h.run(target({BTC:1}))).status).toBe("UNKNOWN_SUBMISSION_STATE");expect(h.orders).toHaveLength(1);});
  it("blocks unowned open orders",async()=>{const h=harness();h.state.openOrderCount=1;h.state.openOrders=[{asset:"SOL",orderId:"99"}];expect((await h.run(target({BTC:1}))).status).toBe("BLOCKED");expect(h.orders).toHaveLength(0);});
  it("completed same-day run only reads back even if equity changed",async()=>{const h=harness();h.repo.isRunCompleted=async()=>true;expect((await h.run(target({BTC:1}))).status).toBe("PARTIAL");expect(h.orders).toHaveLength(0);});
  it("a revoked account cannot enter",async()=>{const h=harness();h.candidate.autoTradingRequested=false;expect((await h.run(target({BTC:1}))).status).toBe("FAILED");expect(h.orders).toHaveLength(0);});
});
describe("spot signing and price bounds",()=>{
 it("rounds spot bounds inward at the venue precision",()=>{expect(portfolioPrice(.12345678,3,true,false)).toBe(.12345);expect(portfolioPrice(.12345678,3,true,true)).toBe(.12346);});
 it("allows a spot sell with r=false and exact spot asset index",async()=>{const payload=await buildSignedHyperliquidIocPayload({action:"EXIT",asset:"SPOT:BTC",venue:"spot",side:"sell",size:.01,reduceOnly:false,leg:0,requestedNotionalUsd:1,referencePrice:100,limitPrice:100,tif:"Alo",cloid:`0x${"ab".repeat(16)}`,nonce:BigInt(now),expiresAtMs:now+180000,masterAddress:master,agentAddress:agent,agentPrivateKey:key},{assetIndex:10042,markPrice:100,sizeDecimals:5,venue:"spot"},now);expect(payload.action.orders[0]).toMatchObject({a:10042,b:false,r:false,t:{limit:{tif:"Alo"}}});});
});
