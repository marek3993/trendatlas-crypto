import {safeExecutionError} from "@/server/multi-account-executor/safe-error";
import {readFile,writeFile,rename} from "node:fs/promises";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {loadCleanTarget} from "@/server/multi-account-executor/clean-authority";
import {SupabaseExecutionRepository} from "@/server/multi-account-executor/repository";
import {HyperliquidDryRunGateway} from "@/server/multi-account-executor/dry-run-gateway";
import {preflightMultiAccountCandidates} from "@/server/multi-account-executor/live-preflight";
import {isolateDuplicateWallets} from "@/server/multi-account-executor/batch";
import {MultiAccountExecutor} from "@/server/multi-account-executor/engine";
async function main() {
 if(process.argv.slice(2).some(arg=>arg!=="--no-submit" && arg!=="--execute-live") || process.argv.includes("--no-submit")===process.argv.includes("--execute-live"))throw new Error("select exactly --no-submit or --execute-live");
 const stateDir=process.env.TRENDATLAS_CLEAN_STATE_DIR;
 const config=process.env.TRENDATLAS_CLEAN_CONFIG;
 if(!stateDir || !config || process.env.TRENDATLAS_CLEAN_WORKER!=="1")throw new Error("Clean orchestrator context missing");
 const noSubmit=process.argv.includes("--no-submit");
 const guard=async()=>{
  const policy=JSON.parse(await readFile(config,"utf8"));
  if(policy.strategy_id!=="trendatlas_clean_5050_v1" || policy.execution_backend!=="multi_account")throw new Error("Clean policy invalid");
  if(!noSubmit && (policy.kill_switch!==false || policy.trading_enabled!==true))throw new Error("Clean emergency switch active");
  const old=JSON.parse(await readFile("/opt/trendatlas-production/current/execution/config/execution_mode.json","utf8"));
  if(old.kill_switch!==true || old.trading_enabled!==false)throw new Error("phase68g is not disabled");
  for(const unit of ["mrv1-production.timer","mrv1-production.service"]) {
   const r=spawnSync("systemctl",["is-active",unit],{encoding:"utf8"});
   if(!["inactive","failed"].includes(r.stdout.trim()))throw new Error("phase68g is active or unknown");
  }
 };
 await guard();
 const target=await loadCleanTarget(path.join(stateDir,"signal.json"));
 const repository=new SupabaseExecutionRepository(noSubmit),readOnly=new HyperliquidDryRunGateway(fetch,true);
 const candidates=await repository.listMultiAccountCandidates();
 const preflight=isolateDuplicateWallets(candidates,await preflightMultiAccountCandidates(candidates,target,readOnly,repository));
 let results:unknown[]=[],passed=preflight.length>0 && preflight.every(p=>["READY","ALIGNED","ENTRY_BLOCKED"].includes(p.status));
 if(!noSubmit) {
  await guard();
  const {HyperliquidLiveGateway}=await import("@/server/multi-account-executor/hyperliquid-live-gateway");
  const blockedIds=new Set(preflight.filter(p=>!["READY","ALIGNED","ENTRY_BLOCKED"].includes(p.status)).map(p=>p.accountId));
  const original=repository.listMultiAccountCandidates.bind(repository);
  repository.listMultiAccountCandidates=async()=> (await original()).filter(c=>!blockedIds.has(c.accountId));
  for(const failed of preflight.filter(p=>blockedIds.has(p.accountId))) {
    const candidate=candidates.find(c=>c.accountId===failed.accountId)!;
    const id=await repository.createRun(candidate,target,failed.accountEquityUsd??null,"BLOCKED");
    await repository.finishRun(id,"BLOCKED",failed.accountEquityUsd??null,failed.reason);
    await repository.setAccountStatus(candidate.authorizationId,"blocked");
  }
  const policy=JSON.parse(await readFile(config,"utf8"));
  const makerWaitMs=Number(policy.policy?.maker_wait_seconds)*1000;
  if(!Number.isFinite(makerWaitMs)||makerWaitMs<0||makerWaitMs>3600000)throw new Error("invalid maker timeout");
  const runtime={now:Date.now,wait:(ms:number)=>new Promise<void>(resolve=>setTimeout(resolve,ms)),makerWaitMs};
  const executed=await new MultiAccountExecutor(repository,new HyperliquidLiveGateway(fetch,true,guard),"live",1,runtime).runAllForTarget(target);
  results=[...executed,...preflight.filter(p=>blockedIds.has(p.accountId))];
  passed=candidates.length>0 && blockedIds.size===0 && executed.length===candidates.length && executed.every(r=>["NO_ACTION","FILLED_AND_ALIGNED"].includes(r.status));
 }
 const report={schema_version:1,mode:noSubmit?"READ_ONLY_PREFLIGHT":"CLEAN_MULTI_ACCOUNT",signal_id:target.signalId,weights:target.weights,closed_day:target.closedDay,account_count:candidates.length,preflight,results,all_accounts_aligned:!noSubmit&&passed,preflight_passed:noSubmit&&passed,generated_at_utc:new Date().toISOString()};
 const file=path.join(stateDir,noSubmit?"multi_account_preflight.json":"multi_account_receipt.json"),temp=`${file}.${process.pid}.tmp`;
 await writeFile(temp,JSON.stringify(report,null,2),{mode:0o600});await rename(temp,file);
 console.log(JSON.stringify({status:passed?"CLEAN_ACCOUNTS_VERIFIED":"CLEAN_ACCOUNT_ATTENTION_REQUIRED",mode:report.mode,account_count:candidates.length,receipt:file}));
 if(!passed)process.exitCode=2;
}
main().catch(error=>{console.error(JSON.stringify({event:"CLEAN_WORKER_ERROR",reason:safeExecutionError(error,"worker")}));process.exitCode=2;});
