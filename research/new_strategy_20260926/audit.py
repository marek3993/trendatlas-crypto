"""Independent invariance, publication, lineage and frozen-selection checks."""
import ast,copy,io,json,zipfile
import numpy as np
import pandas as pd
from common import HERE,ROOT,digest,write,candidate_id
import market,signals,ledger,designer

def main():
    out=HERE/'results';freeze=json.loads((out/'freeze.json').read_text())
    for p,h in freeze['hashes'].items():assert digest(HERE/p)==h,p
    trials=[json.loads(x) for x in (out/'development.jsonl').read_text().splitlines()]
    assert len(trials)==330
    assert all(r['scope']=='development' and r['year']==r['origin']-1 for r in trials)
    gens=json.loads((out/'generations.json').read_text());assert len(gens)==60
    for g in gens:
        assert len(g['population'])==10 and len(set(g['population']))==10
        assert len(g['survivors'])==6 and set(g['survivors'])<=set(g['population'])
        if g['generation']<3:
            nex=next(x for x in gens if x['origin']==g['origin'] and x['family']==g['family'] and x['generation']==g['generation']+1)
            assert set(g['survivors'])<=set(nex['population'])
            assert len(set(nex['population'])-set(g['population']))==4
    cfgs={}
    for p in sorted(out.glob('origin_*_frozen.json')):
        c=json.loads(p.read_text())['champion']['candidate'];cfgs[candidate_id(c)]=c
    final=json.loads((out/'finalists_frozen.json').read_text())
    for r in final['slots'].values():
        if r:cfgs[r['candidate_id']]=r['candidate']
    cut=pd.Timestamp('2023-07-17 12:00:00');full=market.load();short=market.load(str(cut));changed=copy.deepcopy(full)
    future=changed['dates']>cut;changed['prices'][future,:,:4]*=1.7;changed['quote'][future]*=.01;changed['eligible'][future]=False
    changed['close'].loc[changed['close'].index>cut.normalize()]*=1.9
    checks=[]
    for cid,c in cfgs.items():
        ref=signals.target(full,c).loc[:cut];a=signals.target(short,c);b=signals.target(changed,c).loc[:cut]
        pd.testing.assert_frame_equal(ref,a);pd.testing.assert_frame_equal(ref,b)
        checks.append(dict(candidate_id=cid,prefix=True,future_perturbation=True,rows=len(ref)))
    # An added entirely unavailable name must never change old ranks or votes.
    dc=full['close'];q=pd.DataFrame({a:f.quote_volume for a,f in full['daily'].items()});obs=dc.notna()
    one=market.eligibility(dc,q,obs);dc=dc.copy();q=q.copy();obs=obs.copy();dc['FUTURE']=np.nan;q['FUTURE']=np.nan;obs['FUTURE']=False
    two=market.eligibility(dc,q,obs);pd.testing.assert_frame_equal(one,two[one.columns])
    # Frozen OOS fills are inspected against the actual input price array.
    total=0;episodes=0
    with zipfile.ZipFile(out/'ledgers.zip') as z:
        for name in z.namelist():
            if not name.endswith('/fills.csv'):continue
            raw=z.read(name)
            if len(raw.strip())<3:continue
            f=pd.read_csv(io.BytesIO(raw));stem=name[:-len('fills.csv')]
            if not len(f):continue
            for r in f.itertuples():
                d=pd.Timestamp(r.date);a=full['assets'].index(r.asset)
                bar=d-pd.Timedelta(hours=4) if r.kind=='fold_exit' else d
                i=full['dates'].get_loc(bar);ref=full['prices'][i,a,3 if r.kind=='fold_exit' else 0]
                assert abs(r.reference_price/ref-1)<1e-11
                assert d>pd.Timestamp(r.available_at)
                if r.side=='buy':assert r.fill_price>=r.reference_price
                else:assert r.fill_price<=r.reference_price
                total+=1
            bars=pd.read_csv(io.BytesIO(z.read(stem+'bars.csv')))
            trade=pd.read_csv(io.BytesIO(z.read(stem+'episodes.csv')))
            assert abs(np.log1p(bars.net_return).sum()-trade.log_growth.sum())<1e-9
            episodes+=len(trade)
    logs=[json.loads(x) for x in (out/'access_log.jsonl').read_text().splitlines()]
    assert logs[0]['event']=='all_fold_and_forward_nominees_frozen'
    assert [x['year'] for x in logs[1:]]==[2022,2023,2024,2025]
    assert final['forward_opened'] is False
    # Strategy/proposer dependency closure cannot import any production modules.
    allowed={'numpy','pandas','common','json','os','random','itertools','urllib'}
    imports={}
    for file in ['signals.py','designer.py']:
        tree=ast.parse((HERE/file).read_text());names=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):names.extend(a.name.split('.')[0] for a in n.names)
            if isinstance(n,ast.ImportFrom):names.append(n.module.split('.')[0])
        assert set(names)<=allowed,(file,names);imports[file]=sorted(set(names))
    write(HERE/'causality_audit.json',dict(status='PASS_COMPUTATIONAL_AUDIT',frozen_code_and_data_verified=True,unique_search_evaluations=330,generation_transitions_verified=len(gens),invariance=checks,unavailable_symbol_invariance=True,fills_checked=total,episodes_reconciled=episodes,import_allowlist=imports,fold_nominees_frozen_before_oos=True,forward_opened=False,perpetual_venue_model='NOT_VERIFIED_NOT_SCORED',historical_admin_listing_dates='PARTIAL; first traded minute evidence separate from official administrative notice'))
    print(f'Audit PASS: {len(checks)} frozen configurations, {total} fills, {episodes} episodes',flush=True)

if __name__=='__main__':main()
