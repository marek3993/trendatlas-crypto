"""Independent saved-fill cash reconciliation, causality and PIT lineage checks."""
import io,json,zipfile,ast,importlib.util
import numpy as np
import pandas as pd
from common import HERE,OLD,ROOT,SPEC,write,digest,now,config
from data import load,frames,daily_universe
from signals import targets,trend
from designer import safe_rows,util

def intervals(index):
    out=[];start=last=None
    for t in index:
        if last is not None and t-last!=pd.Timedelta(hours=4):out.append([str(start),str(last)]);start=t
        if start is None:start=t
        last=t
    if start is not None:out.append([str(start),str(last)])
    return out

def data_audit():
    freeze=json.loads((HERE/'data_freeze.json').read_text())
    for name,h in freeze['inputs'].items():assert digest(ROOT/name)==h
    evidence=[];required=set(json.loads((HERE/'acquisition_universe.json').read_text())['symbols'])
    for kind in ['perp_trade','perp_mark']:
        present=frames(HERE/(kind+'.zip'))
        for a,f in present.items():
            expected=pd.date_range(f.index.min(),f.index.max(),freq='4h');missing=expected.difference(f.index)
            evidence.append(dict(component=kind,asset=a,first=str(f.index.min()),last=str(f.index.max()),rows=len(f),missing_intervals=intervals(missing)))
        for a in sorted(required-set(present)):evidence.append(dict(component=kind,asset=a,first=None,last=None,rows=0,missing_intervals=[['2019-01-01 00:00:00','2025-12-31 20:00:00']],reason='No exact-symbol perpetual archive; no spot or 1000x contract substitute. Not admitted.'))
    spec=importlib.util.spec_from_file_location('funding_coverage_ancestor',OLD/'perpetual_gate.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    with zipfile.ZipFile(HERE/'funding.zip') as z:
        for n in z.namelist():
            f=pd.read_csv(io.BytesIO(z.read(n)));start=pd.to_datetime(f.calc_time.min(),unit='ms');end=pd.to_datetime(f.calc_time.max(),unit='ms');gaps,transitions=old.funding_coverage(f,start,end)
            evidence.append(dict(component='funding',asset=n[:-4],rows=len(f),first=str(start),last=str(end),missing_intervals=gaps,interval_changes=transitions))
        for a in sorted(required-{n[:-4] for n in z.namelist()}):evidence.append(dict(component='funding',asset=a,first=None,last=None,rows=0,missing_intervals=[['2019-01-01 00:00:00','2025-12-31 23:59:59']],reason='No exact-symbol funding archive acquired; not fabricated.'))
    u=daily_universe();elig=u['eligible'];assert int(elig.sum(axis=1).max())<=5
    observed=u['close'].gt(0)&u['quote'].gt(0);assert not (elig&~observed).any().any();assert not (elig&(observed.cumsum()<365)).any().any()
    long=elig.stack();membership=long[long].reset_index();membership.columns=['signal_day','asset','eligible'];membership.to_csv(HERE/'pit_membership.csv',index=False)
    write(HERE/'data_audit.json',dict(utc=now(),input_hashes_pass=True,all_historical_identities=len(elig.columns),max_members=int(elig.sum(axis=1).max()),eligible_union=list(elig.columns[elig.any()]),venue_certified=False,contract_evidence_missing=[dict(component=c,interval=['2019-01-01','2025-12-31']) for c in ['complete_historical_margin_brackets','historical_liquidation_rules_and_filters','complete_administrative_perp_listing_delisting_notices','historical_Hyperliquid_prices_before_venue_existed']],market_evidence=evidence))

def prefix_audit(markets=None):
    final=json.loads((HERE/'results/finalists_frozen.json').read_text());markets=markets or {t:load(t) for t in ['spot','perp']};prefix=[]
    for t in ['spot','perp']:
        full=markets[t];cut=load(t,'2021-12-31')
        candidates=[c for c in final['unique'].values() if ('perp' if c['family']=='D' else 'spot')==t]
        if t=='spot':candidates += [config(signal=s) for s in SPEC['schema']['signal']]
        for c in candidates:
            a,ae=targets(full,c);b,be=targets(cut,c);ix=[full['assets'].index(n) for n in cut['assets']]
            np.testing.assert_allclose(a[:len(b),ix],b,rtol=0,atol=1e-12);np.testing.assert_array_equal(ae[:len(be)],be)
            extra=[j for j,n in enumerate(full['assets']) if n not in cut['assets']];assert not np.any(a[:len(b),extra])
            prefix.append(dict(track=t,candidate=c,end='2021-12-31',pass_prefix=True))
    write(HERE/'prefix_audit.json',dict(utc=now(),status='PASS',engine_sha256=digest(HERE/'engine_freeze.json'),data_sha256=digest(HERE/'data_freeze.json'),finalists_sha256=digest(HERE/'results/finalists_frozen.json'),prefix=prefix))
    print('PREFIX AUDIT PASS',len(prefix),flush=True);return prefix

def main():
    out=HERE/'results';assert (out/'completed.json').exists()
    data_audit();freeze=json.loads((HERE/'engine_freeze.json').read_text())
    for n,h in freeze['files'].items():assert digest(HERE/n)==h
    markets={t:load(t) for t in ['spot','perp']};final=json.loads((out/'finalists_frozen.json').read_text());audit=[]
    archive=out/'ledgers.zip'
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist())==len(set(z.namelist())),'Duplicate evidence members'
        for member in [n for n in z.namelist() if n.endswith('/bars.csv')]:
            stem=member[:-9];daily=pd.read_csv(io.BytesIO(z.read(stem+'/daily.csv')),index_col=0,parse_dates=True);bars=pd.read_csv(io.BytesIO(z.read(member)),index_col=0,parse_dates=True);qs=pd.read_csv(io.BytesIO(z.read(stem+'/quantities.csv')),index_col=0,parse_dates=True);fills=json.loads(z.read(stem+'/fills.json'));eps=json.loads(z.read(stem+'/episodes.json'));metrics=json.loads(z.read(stem+'/metrics.json'))
            track=fills[0]['venue'] if fills else ('perp' if stem.startswith('D_') or '_perp/' in stem else 'spot');m=markets[track];capital=float(stem.split('/')[1]);cash=capital;q=np.zeros(len(m['assets']));bydate={}
            for f in fills:bydate.setdefault(pd.Timestamp(f['date']),[]).append(f)
            marks=np.zeros(len(q));maxerr=0.;fillcount=0;capacity={};funderr=0.;identity=stem.split('/')[0];cfg=final['unique'].get(identity);stress=stem.split('/')[2];fundmap={}
            for t,j,r in m['funding']:
                bi=(t.value-m['dates'][0].value)//pd.Timedelta(hours=4).value;fundmap.setdefault(bi,[]).append((t,j,r))
            for date,row in bars.iterrows():
                i=m['dates'].get_loc(date);before_q=q.copy();op=m['mark'][i,:,0];open_marks=np.where(np.isfinite(op)&(op>0),op,marks);new=m['mark'][i,:,3];marks=np.where(np.isfinite(new)&(new>0),new,open_marks)
                for f in bydate.get(date,[]):
                    a=m['assets'].index(f['asset']);assert pd.Timestamp(f['available_at'])<date;assert abs(f['reference']-m['prices'][i,a,0])<max(1e-8,abs(f['reference'])*1e-10);assert m['prices'][i,a,4]>0
                    if stress=='delay':
                        valid=(m['dates']>pd.Timestamp(f['available_at']))&np.isfinite(m['prices'][:,a,0])&(m['prices'][:,a,4]>0)
                        actual=np.flatnonzero(valid);assert len(actual)>=2 and i>=actual[1],(stem,'delay not beyond first executable bar',f)
                    delta=f['quantity']
                    if f['signal_kind']=='strategy' and (q[a]==0 or delta*q[a]>0):
                        day=pd.Timestamp(f['signal_day']);standalone=cfg is None or (cfg['family']=='F' and cfg['scope']!='liquid5') or (cfg['family']=='D' and cfg['recipe']=='btc_regime') or (cfg['family']=='G' and f['asset']=='BTCUSDT')
                        assert bool(m['base' if standalone else 'eligible'].loc[day,f['asset']]),'Non-PIT entry'
                    if f['signal_kind']!='strategy':assert abs(q[a]+delta)<=abs(q[a])+1e-8,'Risk intent cannot open/increase exposure'
                    cash-=delta*f['price']+f['fee'];q[a]+=delta;fillcount+=1
                    capacity[(i,a)]=capacity.get((i,a),0)+abs(delta)*f['reference']
                    assert capacity[(i,a)]<=m['quote'][i-2,a]*.001+1e-5,'Reference participation budget'
                debit=credit=0.
                for t,a,rate in fundmap.get(i,[]):
                    amount=-(before_q[a] if t<=date else q[a])*open_marks[a]*rate
                    if amount<0:debit-=amount*(2 if stress=='double_cost' else 1)
                    elif stress!='funding_adverse':credit+=amount
                if stress=='funding_adverse':debit+=float(np.abs(q*open_marks).sum())*.1/(365.25*6)
                funderr=max(funderr,abs(debit-row.funding_debit),abs(credit-row.funding_credit))
                cash+=row.funding_credit-row.funding_debit
                expected=cash+q@marks;maxerr=max(maxerr,abs(expected-row.nav));np.testing.assert_allclose(q,qs.loc[date].to_numpy(),rtol=1e-9,atol=1e-8)
            assert maxerr<max(1e-5,capital*1e-8),(stem,maxerr)
            assert funderr<max(1e-7,capital*1e-9),(stem,'funding',funderr)
            elog=json.loads(z.read(stem+'/episode_logs.json'));totals={}
            for e in elog:totals[e['episode']]=totals.get(e['episode'],0)+e['log_growth']
            for ep in eps:assert abs(totals.get(ep['id'],0)-ep['log_growth'])<1e-9
            top=sorted([e for e in eps if e['closed'] and e['log_growth']>0],key=lambda e:e['log_growth'],reverse=True)[:3]
            expected=np.exp((np.log(metrics['final_nav']/capital)-sum(e['log_growth'] for e in top))/(len(daily)/365.25))-1
            assert abs(expected-metrics['no_top3_cagr'])<1e-8
            audit.append(dict(evidence=stem,track=track,fills=fillcount,max_cash_quantity_nav_error_usd=maxerr,max_independent_funding_error_usd=funderr,entry_PIT_pass=True,whole_episode_removal_pass=True))
    # Real prefix test: truncate every input, recompute risk features and signals.
    if (HERE/'prefix_audit.json').exists():
        saved=json.loads((HERE/'prefix_audit.json').read_text());assert saved['engine_sha256']==digest(HERE/'engine_freeze.json') and saved['data_sha256']==digest(HERE/'data_freeze.json') and saved['finalists_sha256']==digest(HERE/'results/finalists_frozen.json');prefix=saved['prefix']
    else:prefix=prefix_audit(markets)
    events=[json.loads(s) for s in (out/'designer_events.jsonl').read_text().splitlines()]
    for e in events:
        assert e['scope']=='development'
        if e.get('payload'):
            payload=json.loads(e['payload']['messages'][1]['content']);assert set(payload)=={'schema','development','seen'}
            assert all(set(r)=={'candidate','reliable','cagr','mdd','sharpe','calmar','turnover'} for r in payload['development'])
        if e.get('original_payload'):
            original=json.loads(e['original_payload']['messages'][1]['content']);assert set(original)=={'schema','development','seen'}
            assert all(set(r)=={'candidate','reliable','cagr','mdd','sharpe','calmar','turnover'} for r in original['development'])
    try:safe_rows([dict(scope='oos')]);raise AssertionError('Designer accepted OOS')
    except ValueError:pass
    # No execution route or arbitrary generated code; code path has no historical PnL consumer.
    forbidden=[]
    for name in ['common.py','data.py','signals.py','ledger.py','evaluate.py','designer.py','run.py']:
        tree=ast.parse((HERE/name).read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ['eval','exec']:forbidden.append(name+':'+n.func.id)
    assert not forbidden
    write(HERE/'audit_results.json',dict(utc=now(),status='PASS',engine_hashes_pass=True,ledger_reconciliations=audit,prefix_tests=prefix,deepseek_development_boundary=True,forbidden_dynamic_code=forbidden,orders_api_called=False,production_changed=False,forward_opened=False))
    print('AUDIT PASS',len(audit),'detailed books',sum(a['fills'] for a in audit),'fills',len(prefix),'prefix tests')

if __name__=='__main__':main()
