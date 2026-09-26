"""Asset-resolved archaeology ledger, extended for timestamped spot 4h bars.
See ledger_changes.diff and tests for parent parity. No strategy logic here.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
CONTRACT=json.loads((HERE/'contract.json').read_text())
def spec():
    return {'costs':{'fee_bps':CONTRACT['accounting']['spot_fee_bps'],'slippage_bps':CONTRACT['accounting']['slippage_bps'],'funding_annual_debit':0.,'maintenance_ratio':0.,'liquidation_fee_bps':0.}}

def simulate(m,t,*,start=None,end=None,mult=1.,lag=2,fold_reset=True,terminal_exit=True,details=False,rebalance=False,capacity=True,capital_scale=1.):
    if lag<2: raise ValueError('Signal available after next open: two 4h rows minimum')
    s=spec();c=s['costs'];fee=c['fee_bps']*1e-4*mult;slip=c['slippage_bps']*1e-4*mult
    funding=c['funding_annual_debit']*mult/365.25
    dates=m['dates'];P=m['prices'];names=m['assets'];t=t.reindex(dates)
    if t[['asset','weight']].isna().any().any():raise ValueError('Missing signal')
    if not np.isfinite(t.weight).all() or (t.weight<0).any() or (t.weight>1).any():raise ValueError('Spot baseline exposure must be 0..1')
    mapping={a:i for i,a in enumerate(names)};mapping['CASH']=-1
    try: ids=np.array([mapping[a] for a in t.asset])
    except KeyError as exc:raise ValueError('Unresolved tradable identity') from exc
    weights=t.weight.to_numpy(float)
    if np.any((ids<0)&(weights!=0)):raise ValueError('Positive CASH exposure')
    begin=pd.Timestamp(start or dates[0]);finish=pd.Timestamp(end or dates[-1]);inds=np.flatnonzero((dates>=begin)&(dates<=finish))
    step=dates[1]-dates[0] if len(dates)>1 else pd.Timedelta(hours=4)
    nav=1.;q=0.;held=-1;mark=0.;peak=1.;dd=0.;ep=None;episodes=[];rows=[];fills=[];liquidations=0
    day_path=[];costs={};turn=0.
    def event(value,kind):
        nonlocal nav,peak,dd,ep
        before=nav;nav=float(value)
        if nav<=0:raise ValueError('Bankruptcy; fail closed instead of clipping return')
        if ep is not None: ep['log_growth']+=float(np.log(nav/before))
        day_path.append(nav);peak=max(peak,nav);dd=max(dd,1-nav/peak)
    def move(price):
        nonlocal mark
        if q:event(nav+q*(price-mark),'mark')
        mark=float(price)
    def fill(delta,price,kind):
        nonlocal q,turn
        if abs(delta)*price<1e-13:return
        before=nav;execution=price*(1+slip if delta>0 else 1-slip)
        if capacity and 'quote' in m:
            known=m['quote'][j,held]
            if not np.isfinite(known) or known<=0 or abs(delta)*execution*CONTRACT['accounting']['initial_usd']*capital_scale>known*CONTRACT['accounting']['max_participation_previous_bar_quote']:
                raise ValueError(f'Participation cap exceeded at {date}: {names[held]}; order_notional={abs(delta)*execution*CONTRACT["accounting"]["initial_usd"]*capital_scale:.6f}, known_quote={known:.6f}, cap_fraction={CONTRACT["accounting"]["max_participation_previous_bar_quote"]}')
            if P[i,held,4]<=0:raise ValueError('No actual volume at fill')
        fee_amount=abs(delta)*execution*fee;slip_amount=abs(delta)*(abs(execution-price))
        costs['fee']+=fee_amount/before;costs['slippage']+=slip_amount/before
        turn+=abs(delta)*execution/before
        event(nav-fee_amount-slip_amount,kind);q+=delta
        if details:fills.append(dict(date=str(date+step if kind=='fold_exit' else date),signal_date=str(dates[j]) if j>=0 else '',asset=names[held],side='buy' if delta>0 else 'sell',quantity=abs(delta),reference_price=price,fill_price=execution,fee=fee_amount,kind=kind,episode=ep['id'],available_at=str(dates[j]+step+pd.Timedelta(seconds=CONTRACT['accounting']['publication_latency_seconds']))))
    def flatten(price,kind):
        nonlocal q,held,ep
        fill(-q,price,kind);q=0.
        if ep is not None:
            # Open-to-open episodes exclude the exit day; scheduled close exit
            # includes it. Intraday liquidation duration is explicitly a bound.
            fraction=step/pd.Timedelta(days=1) if kind=='fold_exit' else step/pd.Timedelta(days=2) if kind=='intraday_liquidation' else 0.
            ep.update(exit=str(date),exit_kind=kind,holding_days=(date-pd.Timestamp(ep['entry']))/pd.Timedelta(days=1)+fraction);episodes.append(ep);ep=None
        held=-1
    period_begin=inds[0]
    for i in inds:
        date=dates[i];j=i-lag;before=nav;day_path=[nav];costs={'fee':0.,'slippage':0.,'funding':0.,'liquidation':0.};turn=0.
        if fold_reset and i>inds[0] and date.year!=dates[i-1].year:period_begin=i
        a=int(ids[j]) if j>=0 else -1;w=float(weights[j]) if j>=0 else 0.
        # A forced flat start creates a new order even if its target was already
        # long in warmup. Delay that initial order too, not only later signals.
        if i-period_begin<lag-2:a=-1;w=0.
        if a>=0 and not m['eligible'][j,a]:raise ValueError(f'Non-PIT admission {date} {names[a]}')
        for x in {a,held}-{-1}:
            if not np.isfinite(P[i,x,:4]).all() or np.any(P[i,x,:4]<=0):raise ValueError(f'Missing actual held/fill prices: {date} {names[x]}')
        if held>=0:
            move(P[i,held,0])
            if nav<=q*mark*c['maintenance_ratio']:
                costs['liquidation']+=q*mark*c['liquidation_fee_bps']*1e-4/nav
                event(nav-q*mark*c['liquidation_fee_bps']*1e-4,'liquidation');flatten(mark,'gap_liquidation');liquidations+=1;a=-1;w=0.
        if held!=a and held>=0:flatten(mark,'rotation_exit')
        if a>=0 and w>0:
            if held<0:
                held=a;mark=float(P[i,a,0]);ep=dict(id=len(episodes)+1,asset=names[a],entry=str(date),log_growth=0.)
            # Solve q_new * reference / NAV_after_cost = desired weight.
            old=q*mark;desired=w*nav;direction=1 if desired>=old else -1
            k=slip+fee*(1+slip if direction>0 else 1-slip)
            notional=w*(nav+direction*k*old)/(1+direction*w*k)
            if rebalance or q==0:
                fill(notional/mark-q,mark,'entry_or_resize')
            amount=q*mark*funding;costs['funding']+=amount/nav;event(nav-amount,'funding')
            high,low,close=P[i,a,1:4]
            # Conservative OHLC ordering for long equity drawdown. No new stops.
            move(high)
            trigger=(q*mark-nav)/(q*(1-c['maintenance_ratio'])) if q else -np.inf
            if q and low<=trigger<=mark:
                move(trigger);costs['liquidation']+=q*mark*c['liquidation_fee_bps']*1e-4/nav
                event(nav-q*mark*c['liquidation_fee_bps']*1e-4,'liquidation');flatten(mark,'intraday_liquidation');liquidations+=1
            else:move(low);move(close)
        if q and ((fold_reset and (date+step).year!=date.year) or (terminal_exit and i==inds[-1])):flatten(mark,'fold_exit')
        rows.append(dict(date=date,net_return=nav/before-1,equity=nav,turnover=turn,fee=costs['fee'],slippage=costs['slippage'],funding=costs['funding'],liquidation=costs['liquidation'],asset=names[held] if held>=0 else 'CASH',exposure=q*mark/nav if q else 0.,path=[v/before for v in day_path],signal_date=dates[j] if j>=0 else pd.NaT))
    frame=pd.DataFrame(rows).set_index('date')
    if ep is not None:ep.update(exit=None,holding_days=(finish-pd.Timestamp(ep['entry'])+step)/pd.Timedelta(days=1));episodes.append(ep)
    assert abs(sum(e['log_growth'] for e in episodes)-np.log(nav))<1e-9,'Episode attribution must reconcile'
    return dict(daily=frame,episodes=episodes,fills=fills,liquidations=liquidations)

def summarize(run):
    d=run['daily'];bar=d.net_return;daily=(1+bar).groupby(d.index.normalize()).prod()-1;r=daily.to_numpy();step=d.index[1]-d.index[0] if len(d)>1 else pd.Timedelta(hours=4);years=float((d.index[-1]-d.index[0]+step)/pd.Timedelta(days=365.25))
    total=float(np.log1p(r).sum());cagr=float(np.expm1(total/years));v=np.std(r,ddof=1)
    eq=1.;peak=1.;dd=0.
    for row in d.itertuples():
        for factor in row.path:
            value=eq*factor;peak=max(peak,value);dd=max(dd,1-value/peak)
        eq*=1+row.net_return
    eps=[x for x in run['episodes'] if x['exit'] is not None]
    folds={str(y):float(np.expm1(np.log1p(z.net_return).sum())) for y,z in d.groupby(d.index.year)}
    top=sorted([max(0.,x['log_growth']) for x in eps],reverse=True)[:3]
    return dict(cagr=cagr,mdd=dd,sharpe=float(np.mean(r)/v*np.sqrt(365.25)) if v>0 else 0.,calmar=cagr/dd if dd else 0.,turnover=float(d.turnover.sum()/years),costs=float(d[['fee','slippage','funding','liquidation']].sum().sum()/years),fee=float(d.fee.sum()/years),slippage=float(d.slippage.sum()/years),funding=float(d.funding.sum()/years),trades=len(eps),median_holding=float(np.median([x['holding_days'] for x in eps])) if eps else 0.,profitable_folds=sum(x>0 for x in folds.values()),fold_count=len(folds),worst_fold=min(folds.values()),fold_returns=folds,without_best_day=float(np.expm1((total-np.log1p(r.max()))/years)),without_three_trades=float(np.expm1((total-sum(top))/years)),liquidations=run['liquidations'],total_log_growth=total)
