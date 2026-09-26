"""Prefix, future-perturbation and source-lineage checks on the fresh replay."""
import copy, io, json, time, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import engine as e
import rules

HERE=Path(__file__).resolve().parent
def write(x):(HERE/'causality_audit.json').write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
def market_prefix(m,cut):
    out=copy.deepcopy(m);keep=m['dates']<=cut;n=int(keep.sum());out['dates']=m['dates'][:n]
    out['prices']=m['prices'][:n].copy();out['eligible']=m['eligible'][:n].copy()
    out['raw']={a:f.loc[:cut].copy() for a,f in m['raw'].items()};out['macro']=m['macro'].loc[:cut].copy()
    out['etf']=m['etf'][pd.to_datetime(m['etf'].date)<=cut].copy()
    return out
def future_mutation(m,cut):
    out=copy.deepcopy(m);future=out['dates']>cut;out['prices'][future,:,:4]*=1.35
    for a,f in out['raw'].items():f.loc[f.index>cut,['open','high','low','close']]*=1.35
    out['macro'].loc[out['macro'].index>cut]+=11.
    f=out['etf'];mask=pd.to_datetime(f.date)>cut;f.loc[mask,'flow_3d_sum_usd']=-1e12
    f.loc[mask,'flow_2_of_last_3_positive_flag']=False
    return out
def main():
    started=time.time();cut=pd.Timestamp('2024-09-19');m=e.load();z=zipfile.ZipFile(HERE/'results/ledgers.zip')
    names=sorted(n.split('/')[0] for n in z.namelist() if n.endswith('/signals.csv'))
    full={n:pd.read_csv(io.BytesIO(z.read(n+'/signals.csv')),index_col=0,parse_dates=True) for n in names}
    checks={}
    for label,modified in [('prefix',market_prefix(m,cut)),('future_perturbation',future_mutation(m,cut))]:
        print('AUDIT '+label,flush=True);rebuilt,_=rules.build(modified,progress=True)
        for name,t in rebuilt.items():
            expected=full[name].loc[:cut];actual=t.loc[:cut,['asset','weight']]
            pd.testing.assert_index_equal(expected.index,actual.index,check_names=False)
            assert expected.asset.equals(actual.asset),(label,name,'asset')
            assert np.allclose(expected.weight,actual.weight,atol=1e-13,rtol=0),(label,name,'weight')
        checks[label]={'passed':True,'strategies':len(rebuilt),'through':str(cut.date()),'signal_rows_per_strategy':len(expected)}
        write(dict(status='running',checks=checks))
    # Every published fill: same concrete instrument, adverse price, and
    # strictly after assumed signal publication; accounting reconciles trades.
    fill_count=0
    for name in names:
        f=pd.read_csv(io.BytesIO(z.read(name+'/fills.csv')))
        if len(f):
            entries=f[f.kind.eq('entry_or_resize')]
            assert (pd.to_datetime(entries.date)>=pd.to_datetime(entries.signal_date)+pd.Timedelta(days=2)).all()
            assert set(f.asset)<=set(m['assets'])
            assert (f.loc[f.side.eq('buy'),'fill_price']>=f.loc[f.side.eq('buy'),'reference_price']).all()
            assert (f.loc[f.side.eq('sell'),'fill_price']<=f.loc[f.side.eq('sell'),'reference_price']).all()
            fill_count+=len(f)
        d=pd.read_csv(io.BytesIO(z.read(name+'/daily.csv')))
        tr=pd.read_csv(io.BytesIO(z.read(name+'/trades.csv')))
        assert abs(np.log1p(d.net_return).sum()-tr.log_growth.sum())<1e-9
    checks['fill_lineage_and_log_pnl_reconciliation']={'passed':True,'fills_checked':fill_count,'strategies':len(names)}
    write(dict(status='passed_computational_checks_with_evidence_gaps',checks=checks,seconds=time.time()-started,
               point_in_time_market_membership='UNVERIFIED: historical delisted membership missing',
               macro_etf_publication_vintages='UNVERIFIED',historical_venue_fills_and_funding='UNVERIFIED: common proxies only',sealed_oos='UNAVAILABLE: previously researched history'))
    print('Causal checks passed; unavailable historical evidence remains unverified.',flush=True)
if __name__=='__main__':main()
