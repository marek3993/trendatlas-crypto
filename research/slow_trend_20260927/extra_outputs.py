"""Complete cost, residual, concentration and exposure disclosures from saved books."""
import io,json,zipfile
import numpy as np
import pandas as pd
from common import HERE,OLD,write,now
from data import frames,split

def main():
    out=HERE/'results';assert (out/'completed.json').exists();final=json.loads((out/'finalists_frozen.json').read_text());rows=json.loads((out/'oos.json').read_text());ids=list(final['unique'])+['BTC_SMA200_spot','BTC_SMA200_perp'];concentration=[];exposure=[];costs=[];residual=[];fidelity=[]
    prices={'spot':split(frames(OLD/'spot_4h.zip'),4),'perp':split(frames(HERE/'perp_trade.zip'),4)}
    with zipfile.ZipFile(out/'ledgers.zip') as z:
        for identity in ids:
            stem=identity+'/100/nominal/none';eps=json.loads(z.read(stem+'/episodes.json'));fills=json.loads(z.read(stem+'/fills.json'));m=json.loads(z.read(stem+'/metrics.json'));positive=sum(max(0,e['pnl_usd']) for e in eps);total_turn=sum(abs(f['quantity'])*f['price'] for f in fills)
            for e in eps:
                concentration.append(dict(candidate_id=identity,level='episode',key=e['id'],asset=e['asset'],side=e['side'],closed=e['closed'],entry=e['entry'],exit=e['exit'],pnl_usd=e['pnl_usd'],account_log_growth=e['log_growth'],positive_profit_share=max(0,e['pnl_usd'])/positive if positive else None,holding_days=e['holding_days']))
                if not e['closed']:residual.append(dict(candidate_id=identity,**e))
            for asset in sorted({e['asset'] for e in eps}):
                es=[e for e in eps if e['asset']==asset];fs=[f for f in fills if f['asset']==asset]
                concentration.append(dict(candidate_id=identity,level='asset',key=asset,asset=asset,pnl_usd=sum(e['pnl_usd'] for e in es),account_log_growth=sum(e['log_growth'] for e in es),positive_profit_share=sum(max(0,e['pnl_usd']) for e in es)/positive if positive else None,turnover_share=sum(abs(f['quantity'])*f['price'] for f in fs)/total_turn if total_turn else None,fee_usd=sum(f['fee'] for f in fs),slippage_usd=sum(f['slippage'] for f in fs)))
        for n in [n for n in z.namelist() if n.endswith('/bars.csv')]:
            stem=n[:-9];parts=stem.split('/');b=pd.read_csv(io.BytesIO(z.read(n)),index_col=0,parse_dates=True);d=pd.read_csv(io.BytesIO(z.read(stem+'/daily.csv')),index_col=0,parse_dates=True);c=final['unique'].get(parts[0]);target=c['gross'] if c and c['family']=='D' else 1.
            exposure.append(dict(candidate_id=parts[0],capital=float(parts[1]),stress=parts[2],overlay=parts[3],target_gross_ceiling=target,mean_gross=float(b.gross.mean()),maximum_4h_close_gross=float(b.gross.max()),minimum_net=float(b.net.min()),maximum_net=float(b.net.max()),bars_above_target_due_market_drift=int((b.gross>target+1e-6).sum()),fraction_above_target=float((b.gross>target+1e-6).mean()),maximum_residual_usd=float(b.residual_usd.max()),end_residual_usd=float(b.residual_usd.iloc[-1]),remaining_target_orders=json.loads(z.read(stem+'/orders.json'))[-1:] if False else None))
            for year,part in d.groupby(d.index.year):
                costs.append(dict(candidate_id=parts[0],capital=float(parts[1]),stress=parts[2],overlay=parts[3],year=int(year),fee_usd=float(part.fee.sum()),slippage_usd=float(part.slippage.sum()),funding_debit_usd=float(part.funding_debit.sum()),funding_credit_usd=float(part.funding_credit.sum()),net_cost_usd=float((part.fee+part.slippage+part.funding_debit-part.funding_credit).sum()),traded_notional_usd=float(part.traded_usd.sum()),turnover_nav=float(part.turnover.sum()),mean_exposure=float(part.gross.mean()),end_nav=float(part.nav.iloc[-1])))
        for n in [n for n in z.namelist() if n.endswith('/orders.json')]:
            stem=n[:-12];parts=stem.split('/')
            if parts[0] not in ids:continue
            track='perp' if parts[0].startswith('D_') or parts[0]=='BTC_SMA200_perp' else 'spot';orders=json.loads(z.read(n));req=filled=small=0.;fallback=0
            for order in orders:
                delta=order['filled_quantity']+order['unfilled_quantity'];before=order['target_quantity']-delta;reduction=min(abs(delta),abs(before)) if delta*before<0 else 0.;entry=max(0,abs(delta)-reduction);entry_filled=min(entry,max(0,abs(order['filled_quantity'])-reduction))
                if not entry:continue
                f=prices[track][order['asset']];t=pd.Timestamp(order['submitted']);ref=float(f.loc[t,'open']) if t in f.index else np.nan
                if not np.isfinite(ref) or ref<=0:
                    prior=f.loc[f.index<t,'close'];ref=float(prior.iloc[-1]) if len(prior) else 0.;fallback+=1
                req+=entry*ref;filled+=entry_filled*ref
                if entry*ref<10:small+=entry*ref
            metric=json.loads(z.read(stem+'/metrics.json'))
            fidelity.append(dict(candidate_id=parts[0],capital=float(parts[1]),stress=parts[2],overlay=parts[3],requested_addition_usd_at_submission_reference=req,filled_addition_usd_same_reference=filled,addition_fill_fraction=filled/req if req else None,below_minimum_requested_usd=small,reference_fallback_orders=fallback,reliable=metric['reliable'],mean_exposure=metric['exposure'],cagr=metric['cagr'],mdd=metric['mdd'],note='Order-delta reconstruction; not a venue certificate. Same-asset prior trade close fallback when submission open absent; count explicit. No fidelity threshold changes strategy PASS.'))
    for name,value in [('concentration',concentration),('exposure',exposure),('dollar_costs',costs),('open_positions',residual),('capacity_fidelity',fidelity)]:
        write(out/(name+'.json'),value);pd.DataFrame(value).to_csv(out/(name+'.csv'),index=False)
    print('SUPPLEMENTARY TABLES',len(concentration),'concentration rows',len(costs),'annual dollar cost rows')

if __name__=='__main__':main()
