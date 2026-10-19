import "server-only";
import {safeExecutionError} from "./safe-error";
import {randomUUID} from "node:crypto";
import {createEnvironmentAgentSecretProtector, type EncryptedAgentSecret} from "@/lib/hyperliquid/agent-authorization";
import {assertAgentPrivateKeyMatches, HYPERLIQUID_ORDER_EXPIRY_MS, HYPERLIQUID_EXPIRY_READBACK_SKEW_MS} from "./hyperliquid-l1-signing";
import {deterministicCloid} from "./cloid";
import {buildPortfolioPlan} from "./portfolio-planner";
import type {AccountResult, ExchangeGateway, ExecutionRepository, JournalAction, KnownOrder} from "./engine";
import type {AccountState, AuthorizedTarget, EligibleAccount, FinalStatus, PlannedAction} from "./types";

type Candidate=EligibleAccount & {encryptedSecret?:EncryptedAgentSecret};
export type PortfolioRuntime={now:()=>number;wait:(ms:number)=>Promise<void>;makerWaitMs:number};
const defaults:PortfolioRuntime={now:Date.now,wait:ms=>new Promise(resolve=>setTimeout(resolve,ms)),makerWaitMs:300000};
class UnknownSubmission extends Error { override name="UnknownSubmission"; }
export async function runPortfolioAccount(repo:ExecutionRepository,exchange:ExchangeGateway,candidate:Candidate,target:AuthorizedTarget,runtime:PortfolioRuntime=defaults):Promise<AccountResult> {
  const holder=randomUUID();let locked=false,runId:string|undefined,state:AccountState|undefined,requested=false,possible=false,exited=false;
  let stage="tryAcquire";
  const secrets=[process.env.TRENDATLAS_AGENT_KEK_B64,candidate.encryptedSecret?.encryptedPrivateKey,candidate.encryptedSecret?.encryptionNonce];
  const at=async<T>(name:string,call:()=>Promise<T>):Promise<T>=>{stage=name;return await call();};
  const diagnostic=(error:unknown,event="CLEAN_EXECUTION_ERROR")=>{
    const reason=safeExecutionError(error,stage,secrets);
    console.error(JSON.stringify({event,accountId:candidate.accountId,runId,reason}));
    return reason;
  };
  const readAccount=()=>at("readAccount",()=>exchange.readAccount(candidate.masterAddress));
  const reserveNonce=()=>at("reserveNonce",()=>repo.reserveNonce(candidate.agentAddress));
  const finish=async(status:FinalStatus,reason?:string):Promise<AccountResult>=>{
    if(runId)await at("finishRun",()=>repo.finishRun(runId!,status,state?.equityUsd??null,reason));
    await at("setAccountStatus",()=>repo.setAccountStatus(candidate.authorizationId,["NO_ACTION","FILLED_AND_ALIGNED"].includes(status)?"aligned":"blocked"));
    return {accountId:candidate.accountId,status,orderRequested:possible?null:requested,reason,readback:state};
  };
  try {
    if(!await at("tryAcquire",()=>repo.tryAcquire(candidate.accountId,holder)))return {accountId:candidate.accountId,status:"BLOCKED",orderRequested:false,reason:"account lease held"};
    locked=true;
    if(!repo.renewLease || !repo.readActions || !repo.readUnresolvedActions || !repo.markActionVerified || !repo.isManagedOrder || !exchange.prepareOrder || !exchange.cancelOrder || !exchange.setLeverageOne)throw new Error("portfolio recovery capabilities unavailable");
    const renew=async()=>{if(!await at("renewLease",()=>repo.renewLease!(candidate.accountId,holder)))throw new Error("account lease lost");};
    const freshConsent=async()=>{
      const current=(await at("readConsent",()=>repo.listMultiAccountCandidates())).find(a=>a.accountId===candidate.accountId && a.authorizationId===candidate.authorizationId && a.agentAddress===candidate.agentAddress);
      if(!current?.autoTradingRequested || current.authorizationStatus!=="authorized" || current.executionStatus==="disabled_by_user")throw new Error("account consent changed");
      if(new Date(runtime.now()).toISOString().slice(0,10)!==target.holdingDay)throw new Error("signal holding day expired");
      await renew();
    };
    await freshConsent();
    stage="agentAuthorization";
    const [role,authorization]=await Promise.all([exchange.userRole(candidate.agentAddress),exchange.agentAuthorization(candidate.masterAddress,candidate.agentAddress,candidate.agentName)]);
    if(role.role!=="agent" || role.user?.toLowerCase()!==candidate.masterAddress.toLowerCase() || !authorization.authorized || !authorization.validUntilMs || authorization.validUntilMs<=runtime.now())return await finish("BLOCKED","agent binding unavailable or expired");
    if(!candidate.encryptedSecret)throw new Error("missing signer");
    stage="decryptAgent";
    const key=createEnvironmentAgentSecretProtector(process.env.TRENDATLAS_AGENT_KEK_B64).decrypt(candidate.encryptedSecret);
    secrets.push(key);stage="assertAgentPrivateKeyMatches";
    assertAgentPrivateKeyMatches(key,candidate.agentAddress);
    const identity={masterAddress:candidate.masterAddress,agentAddress:candidate.agentAddress,agentPrivateKey:key};
    state=await readAccount();
    runId=await at("createRun",()=>repo.createRun(candidate,target,state!.equityUsd,"NO_ACTION"));
    const wasCompleted=await at("isRunCompleted",async()=>await repo.isRunCompleted?.(runId!)??false);
    const journal=await at("readActions",()=>repo.readActions!(runId!));
    const all=[...new Map([...journal,...await at("readUnresolvedActions",()=>repo.readUnresolvedActions!(candidate.accountId))].map(j=>[j.cloid,j])).values()];
    const cloidFor=(action:PlannedAction,attempt:number,orderId?:string)=>deterministicCloid({userId:candidate.userId,accountId:candidate.accountId,signalId:target.signalId,closedDay:target.closedDay,target:target.asset,action:action.action,asset:action.asset,side:action.side,leg:action.leg,attempt,orderId});
    const setLeverage=async(asset:string)=>{
      const nonce=await reserveNonce();
      await at("setLeverageOne",()=>exchange.setLeverageOne!({asset,nonce,...identity}));
    };
    const cancel=async(entry:JournalAction,oid:string)=>{
      await renew();
      if(!await repo.isManagedOrder!(candidate.accountId,entry.cloid,oid))throw new Error("unowned resting order");
      const action:PlannedAction={...entry.action,action:"CANCEL",size:0,requestedNotionalUsd:0,leg:journal.length,tif:undefined,limitPrice:undefined,makerDeadlineMs:undefined};
      const cloid=cloidFor(action,0,oid);
      await repo.recordAction(runId!,action,cloid,"NOT_SUBMITTED",oid);
      await repo.recordAction(runId!,action,cloid,"AMBIGUOUS",oid);
      try {await exchange.cancelOrder!({asset:entry.action.asset,orderId:oid,nonce:await reserveNonce(),...identity});} catch {/* Readback is authoritative. */}
      const known=await exchange.findByCloid(candidate.masterAddress,entry.cloid);
      state=await readAccount();
      if(!known || known.state==="open" || known.state==="unknown" || state.openOrders?.some(o=>o.orderId===oid))throw new UnknownSubmission();
      await repo.recordAction(runId!,action,cloid,"KNOWN",oid);await repo.markActionVerified!(cloid);
      return known;
    };
    const settle=async(entry:JournalAction):Promise<Exclude<KnownOrder,null>>=>{
      let known=await exchange.findByCloid(candidate.masterAddress,entry.cloid);
      // Bound maker wait by the persisted deadline and keep the account lease alive.
      while(known?.state==="open" && entry.action.tif==="Alo" && entry.runId===runId && runtime.now()<(entry.action.makerDeadlineMs??0)) {
        await renew();await runtime.wait(Math.min(5000,entry.action.makerDeadlineMs!-runtime.now()));
        known=await exchange.findByCloid(candidate.masterAddress,entry.cloid);
      }
      if(known?.state==="open") {if(!known.orderId)throw new UnknownSubmission();known=await cancel(entry,known.orderId);}
      state=await readAccount();
      if(!known && (entry.state==="NOT_SUBMITTED" || entry.state==="REJECTED"))known={state:"cancelled"};
      if(!known && Number.isSafeInteger(entry.expiresAtMs) && runtime.now()>entry.expiresAtMs!+HYPERLIQUID_EXPIRY_READBACK_SKEW_MS && state.openOrderCount===0)known={state:"cancelled"};
      if(!known || known.state==="unknown")throw new UnknownSubmission();
      entry.state=known.state==="filled"?"KNOWN":"REJECTED";
      await repo.recordAction(entry.runId??runId!,entry.action,entry.cloid,entry.state,known.orderId);
      await repo.markActionVerified!(entry.cloid);return known;
    };
    for(const entry of all) {
      if(entry.action.action==="CANCEL")continue;
      possible=entry.state!=="NOT_SUBMITTED";await settle(entry);possible=false;
      const local=journal.find(j=>j.cloid===entry.cloid);if(local)local.state=entry.state;
    }
    state=await readAccount();
    // Unknown or manual orders are never cancelled just to make an entry fit.
    if(state.openOrderCount!==0)return await finish("BLOCKED","unreconciled or unowned open orders");
    for(let step=0;step<64;step++) {
      await freshConsent();
      if(authorization.validUntilMs<=runtime.now())throw new Error("agent expired");
      const markets=await at("readMarkets",()=>exchange.readMarkets());
      let plan=buildPortfolioPlan(target,state,markets);
      if(wasCompleted)return await finish(plan.state==="NO_ACTION" && !state.positions.some(p=>p.size!==0 && p.venue!=="spot" && (target.weights?.[p.asset]??0)>0 && p.leverage!==1)?"NO_ACTION":"PARTIAL","same-day completed run: readback only");
      // Enforce 1x on retained target perps too; never silently call a 10x position aligned.
      const wrongLeverage=state.positions.find(p=>p.size>0 && p.venue!=="spot" && (target.weights?.[p.asset]??0)>0 && p.leverage!==1);
      if(!plan.actions.some(a=>a.action==="EXIT") && wrongLeverage) {
        await setLeverage(wrongLeverage.asset);
        state=await readAccount();
        if(state.positions.find(p=>p.asset===wrongLeverage.asset)?.leverage!==1)throw new Error("1x leverage readback failed");
        plan=buildPortfolioPlan(target,state,markets);
      }
      if(plan.state==="NO_ACTION")return await finish(requested?"FILLED_AND_ALIGNED":"NO_ACTION",plan.dust?.length?"aligned with visible exchange minimum dust":undefined);
      if(plan.state==="BLOCKED" || !plan.actions.length)return await finish(exited && state.positions.every(p=>p.size===0)?"EXITED_ENTRY_FAILED_STAYING_CASH":"BLOCKED",plan.reason);
      const planned=plan.actions[0];
      const prior=journal.filter(j=>j.action.action===planned.action && j.action.asset===planned.asset && j.action.side===planned.side);
      if(prior.length>=3)return await finish("PARTIAL","bounded residual attempts exhausted");
      const reference=prior[0]?.action.referencePrice??planned.referencePrice;
      let action=await at("prepareOrder",()=>exchange.prepareOrder!({...planned,referencePrice:reference,tif:prior.length?"Ioc":"Alo",leg:journal.length,makerDeadlineMs:runtime.now()+runtime.makerWaitMs}));
      if(action.action==="ENTER" && action.venue==="perp") {
        await setLeverage(action.asset);
        state=await readAccount();
        const freshPlan=buildPortfolioPlan(target,state,markets);
        if(freshPlan.actions[0]?.asset!==action.asset || freshPlan.actions[0]?.action!=="ENTER")return await finish("BLOCKED","account changed before entry");
        action={...action,size:Math.min(action.size,freshPlan.actions[0].size)};
      }
      const cloid=cloidFor(action,prior.length);
      stage="recordActionIntent";
      await repo.recordAction(runId,action,cloid,"NOT_SUBMITTED");
      stage="findByCloid";
      if(await exchange.findByCloid(candidate.masterAddress,cloid))throw new UnknownSubmission();
      const nonce=await reserveNonce(),expiresAtMs=Number(nonce)+HYPERLIQUID_ORDER_EXPIRY_MS;
      stage="recordActionBeforeSubmit";
      await repo.recordAction(runId,action,cloid,"AMBIGUOUS",undefined,expiresAtMs);
      const entry:JournalAction={action,cloid,state:"AMBIGUOUS",runId,expiresAtMs};journal.push(entry);requested=true;possible=true;
      try {
        stage="submitOrder";
        const response=await exchange.writeIoc({...action,cloid,nonce,expiresAtMs,...identity});
        await repo.recordAction(runId,action,cloid,"SUBMITTED",response.orderId);entry.state="SUBMITTED";
      } catch(error) {
        const known=await exchange.findByCloid(candidate.masterAddress,cloid);
        if(!known && error && typeof error==="object" && "definiteRejection" in error && error.definiteRejection===true) {
          entry.state="REJECTED";await repo.recordAction(runId,action,cloid,"REJECTED");await repo.markActionVerified(cloid);possible=false;
          state=await readAccount();
          if(action.tif==="Alo")continue;
          return await finish("PARTIAL","IOC rejected; account retained after readback");
        }
        if(!known || known.state==="unknown")throw new UnknownSubmission("Order acknowledgement unavailable",{cause:error});
      }
      await settle(entry);possible=false;
      if(action.action==="EXIT")exited=true;
      state=await readAccount();
      if(state.openOrderCount!==0)throw new UnknownSubmission();
    }
    return await finish("PARTIAL","bounded portfolio reconciliation exhausted");
  } catch(error) {
    const status=error instanceof UnknownSubmission || possible?"UNKNOWN_SUBMISSION_STATE":"FAILED";
    const reason=diagnostic(error);
    try{return await finish(status,reason);}catch(journalError){
      diagnostic(journalError,"CLEAN_EXECUTION_JOURNAL_ERROR");
      return {accountId:candidate.accountId,status,orderRequested:possible?null:requested,reason,readback:state};
    }
  } finally {if(locked)try{await repo.release(candidate.accountId,holder);}catch{/* Lease expires. */}}
}
