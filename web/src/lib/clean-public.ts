import "server-only";
import {validWeights} from "@/server/multi-account-executor/portfolio-planner";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import path from "node:path";
export type Summary={cagr_pct:number;max_drawdown_pct:number;sharpe:number|null;total_return_pct:number;funding_proxy_days:number;unpriced_execution_proxy_days:number};
export type CleanMetrics={schema_version:1;strategy_id:string;kind:string;window:{start:string;end:string;days:number};since_2021:Summary;last_12_months:Summary;btc_last_12_months_pct:number;cash_days_pct:number;annual:Array<{year:number;return_pct:number;btc_return_pct:number;partial_year:boolean}>;timeseries_sha256:string;universe:{kind:string;symbol_count:number}};
export type CleanPublic={metrics:CleanMetrics;series:Array<{date:string;clean:number;btc:number}>;signal:{decision_closed_day_utc:string;drzat_pocas_dna_utc:string;ciel_vahy:Record<string,number>};stale:boolean};
export function parseCleanPublic(metricsText:string,csv:string,signalText:string,now=new Date()):CleanPublic {
  const m=JSON.parse(metricsText) as CleanMetrics,signal=JSON.parse(signalText);
  if(m.schema_version!==1 || m.strategy_id!=="trendatlas_clean_5050_v1" || m.kind!=="HISTORICAL_BACKTEST_AFTER_COSTS" || m.window.start!=="2021-01-01" || createHash("sha256").update(csv).digest("hex")!==m.timeseries_sha256 || signal.strategy_id!==m.strategy_id || signal.decision_closed_day_utc!==m.window.end || !validWeights(signal.ciel_vahy) || Object.keys(signal.ciel_vahy).length===0 || Date.parse(signal.drzat_pocas_dna_utc)-Date.parse(signal.decision_closed_day_utc)!==86400000)throw new Error("Clean publication mismatch");
  for(const summary of [m.since_2021,m.last_12_months]) {
    if(!summary || ![summary.cagr_pct,summary.max_drawdown_pct,summary.total_return_pct,summary.funding_proxy_days,summary.unpriced_execution_proxy_days].every(Number.isFinite) || !(summary.sharpe===null || Number.isFinite(summary.sharpe)))throw new Error("Clean metrics incomplete");
  }
  if(!Array.isArray(m.annual)||!Number.isFinite(m.cash_days_pct)||!Number.isFinite(m.btc_last_12_months_pct))throw new Error("Clean metrics incomplete");
  const [header,...rows]=csv.trim().split(/\r?\n/),columns=header.split(",");
  const series=rows.map(row=>{const v=row.split(",");return {date:v[columns.indexOf("date")],clean:Number(v[columns.indexOf("clean_equity")]),btc:Number(v[columns.indexOf("btc_equity")])};});
  if(series.length!==m.window.days || series[0]?.date!==m.window.start || series.at(-1)?.date!==m.window.end || series.some(r=>!Number.isFinite(r.clean)||r.clean<=0||!Number.isFinite(r.btc)||r.btc<=0))throw new Error("Clean series incomplete");
  for(let i=1;i<series.length;i++)if(Date.parse(series[i].date)-Date.parse(series[i-1].date)!==86400000)throw new Error("Clean dates incomplete");
  return {metrics:m,series,signal,stale:signal.drzat_pocas_dna_utc!==now.toISOString().slice(0,10)};
}
export async function loadCleanPublic():Promise<CleanPublic|null> {
  try {
    const dir=process.env.TRENDATLAS_CLEAN_PUBLIC_DIR;
    const names=["clean5050_metrics.json","clean5050_timeseries.csv","signal.json"];
    let texts:string[];
    // Optional external runtime artifacts must not trace the whole repo into a web deployment.
    if(dir)texts=await Promise.all(names.map(n=>readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dir,n),"utf8")));
    else {
      const origin=process.env.NEXT_PUBLIC_SUPABASE_URL;
      if(!origin)return null;
      const base=`${origin}/storage/v1/object/public/trendatlas-clean-public`;
      const latest=await fetch(`${base}/latest.json`,{cache:"no-store",signal:AbortSignal.timeout(8000)});
      if(!latest.ok)return null;
      const manifest=await latest.json();if(!/^[0-9a-f]{64}$/.test(manifest.version))return null;
      texts=await Promise.all(names.map(async n=>{const r=await fetch(`${base}/${manifest.version}/${n}`,{cache:"no-store",signal:AbortSignal.timeout(8000)});if(!r.ok)throw new Error("missing publication");return r.text();}));
    }
    return parseCleanPublic(texts[0],texts[1],texts[2]);
  }catch{return null;}
}
