import "server-only";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {CLEAN_STRATEGY, validWeights} from "./portfolio-planner";
import type {AuthorizedTarget} from "./types";
/** Only the current closed UTC day is executable. No lag is applied here. */
export function parseCleanSignal(value: unknown, now = new Date()): AuthorizedTarget {
  if (!value || typeof value!=="object" || Array.isArray(value)) throw new Error("invalid Clean signal");
  const s=value as Record<string,unknown>, today=now.toISOString().slice(0,10);
  const yesterday=new Date(Date.parse(today)-86400000).toISOString().slice(0,10);
  const p=s.params as Record<string,unknown>|undefined;
  if(s.schema_version!==1 || s.strategy_id!==CLEAN_STRATEGY || s.mode!=="SIGNAL_ONLY" || s.decision_closed_day_utc!==yesterday || s.drzat_pocas_dna_utc!==today || s.rozhodnute_na_close_utc!==`${yesterday}T23:59:59.999Z` || !validWeights(s.ciel_vahy) || Object.keys(s.ciel_vahy).length===0 || !p || p.regime_min!==0.5 || p.universe_n!==10 || p.top_k!==1 || p.switch_h!==0.25 || p.btc_pref!==0.25 || !/^[0-9a-f]{64}$/.test(String(s.input_sha256)) || !/^[0-9a-f]{64}$/.test(String(s.code_sha256))) throw new Error("stale or invalid Clean signal");
  const weights=Object.fromEntries(Object.entries(s.ciel_vahy).filter(([a,w])=>a!=="CASH" && w>0).sort());
  const exposure=Object.values(weights).reduce((sum,w)=>sum+w,0);
  if(typeof s.gross_target_exposure!=="number" || Math.abs(s.gross_target_exposure-exposure)>1e-12) throw new Error("Clean exposure mismatch");
  const signalId=createHash("sha256").update(JSON.stringify({strategy:CLEAN_STRATEGY,closedDay:yesterday,weights,params:{regime_min:0.5,universe_n:10,top_k:1,switch_h:0.25,btc_pref:0.25}})).digest("hex");
  return {strategyVersion:CLEAN_STRATEGY,closedDay:yesterday,holdingDay:today,signalId,weights,asset:exposure?"PORTFOLIO":"CASH",exposure,stale:false,executionGate:"approved"};
}
export async function loadCleanTarget(file: string): Promise<AuthorizedTarget> { return parseCleanSignal(JSON.parse(await readFile(file,"utf8"))); }
