import {describe,it,expect} from "vitest";
import {fetchPortfolioMarkets,readPortfolioAccount} from "@/server/multi-account-executor/portfolio-market-data";
function fixture(abstraction="unifiedAccount") {
 const responses:Record<string,unknown>={perpDexs:[null],metaAndAssetCtxs:[{universe:[{name:"BTC",szDecimals:5},{name:"SOL",szDecimals:2}]},[{markPx:"50000"},{markPx:"100"}]],spotMetaAndAssetCtxs:[{tokens:[{index:0,name:"USDC",szDecimals:8},{index:1,name:"USDH",szDecimals:8},{index:197,name:"UBTC",szDecimals:5}],universe:[{name:"@234",index:234,tokens:[197,1]},{name:"@142",index:142,tokens:[197,0]}]},[{coin:"@234",markPx:"50000"},{coin:"@142",markPx:"50000"}]],spotClearinghouseState:{balances:[{coin:"USDC",token:0,total:"50",hold:"10"},{coin:"UBTC",token:197,total:".001",hold:"0"}]},userAbstraction:abstraction,clearinghouseState:{marginSummary:{accountValue:"999",totalMarginUsed:"0"},withdrawable:"30",assetPositions:[]},openOrders:[]};
 const fetcher=(async(_u:unknown,init?:RequestInit)=>{const q=JSON.parse(String(init?.body));return new Response(JSON.stringify(responses[q.type]));}) as typeof fetch;
 return {fetcher,responses};
}
describe("Clean exchange identity and equity",()=>{
 it("uses metadata UBTC/USDC spot index and never BTC perp as fallback",async()=>{const f=fixture(),markets=await fetchPortfolioMarkets(f.fetcher);expect(markets.get("SPOT:BTC")).toMatchObject({assetIndex:10142,venue:"spot",coin:"@142"});expect(markets.get("BTC")?.entryAvailable).toBe(false);expect(markets.get("SOL")?.entryAvailable).toBe(true);});
 it("values unified spot equity exactly once",async()=>{const f=fixture(),m=await fetchPortfolioMarkets(f.fetcher),a=await readPortfolioAccount("wallet",f.fetcher,m);expect(a.equityUsd).toBe(100);expect(a.spotCashFreeUsd).toBe(40);expect(a.marginAvailableUsd).toBe(40);expect(a.positions[0]).toMatchObject({asset:"SPOT:BTC",size:.001});});
 it("keeps standard spot and perp collateral separate",async()=>{const f=fixture("default"),m=await fetchPortfolioMarkets(f.fetcher),a=await readPortfolioAccount("wallet",f.fetcher,m);expect(a.equityUsd).toBe(1099);expect(a.marginAvailableUsd).toBe(30);expect(a.spotCashFreeUsd).toBe(40);});
 it("blocks entry in borrowing modes",async()=>{const f=fixture("portfolioMargin"),m=await fetchPortfolioMarkets(f.fetcher),a=await readPortfolioAccount("wallet",f.fetcher,m);expect(a.entryBlockers).toContain("UNSUPPORTED_ABSTRACTION_FOR_ENTRY:portfolioMargin");});
});
