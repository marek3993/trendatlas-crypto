"""Portfolio extension of the asset-resolved archaeology ledger.

Cash/own-symbol quantities replace the former single held slot. The immutable
ancestor metric function is reused. No return stream, synthetic identity,
paper equity or current account state is an input.
"""
import importlib.util
import numpy as np
import pandas as pd
from common import PARENT,SPEC
_s=importlib.util.spec_from_file_location('immutable_ancestor_metrics',PARENT/'ledger.py')
_parent=importlib.util.module_from_spec(_s);_s.loader.exec_module(_parent)

class UnsafeExecution(ValueError):
    def __init__(self,message,partial=None):super().__init__(message);self.partial=partial

def simulate(m,t,*,start,end,capital=100.,mult=1.,lag=2,details=False,liquidate=True):
    e=SPEC['execution'];dates=m['dates'];P=m['prices'];names=m['assets'];W=t['weights'];N=len(names)
    if W.shape!=(len(dates),N) or not np.isfinite(W).all() or np.any(W<0) or np.any(W.sum(axis=1)>1+1e-10):raise ValueError('Invalid concrete spot portfolio')
    if lag<2:raise ValueError('Publication latency requires lag>=2')
    ix=np.flatnonzero((dates>=pd.Timestamp(start))&(dates<=pd.Timestamp(end)))
    if not len(ix):raise ValueError('Empty interval')
    cash=float(capital);nav=cash;q=np.zeros(N);mark=np.zeros(N);active={};episodes=[];fills=[];orders=[];pending={};rows=[];next_episode=0
    fee=e['fee_bps']*1e-4*mult;slip=e['slippage_bps']*1e-4*mult
    scheduled_start=max(ix[0],ix[-1]-e['exit_ttl_bars']+1)+(lag-2)
    forced=False;last_target=np.zeros(N);entry_requested=entry_filled=0.;partials=0
    def pack(status='VALID',reason=None):
        all_eps=episodes+[dict(ep,exit=None,holding_days=(date-pd.Timestamp(ep['entry']))/pd.Timedelta(days=1)) for ep in active.values()]
        frame=pd.DataFrame(rows)
        if len(frame):frame=frame.set_index('date')
        return dict(status=status,reason=reason,daily=frame,episodes=all_eps,fills=fills,orders=orders,liquidations=0,capital=capital,ending_cash=cash,ending_nav=nav,residual_positions={names[a]:float(q[a]) for a in range(N) if q[a]>0},entry_requested=entry_requested,entry_filled=entry_filled,partial_fills=partials)
    def fail(message):raise UnsafeExecution(message,pack('UNSAFE_EXECUTION',message))
    def change(delta):
        nonlocal nav
        total=float(sum(delta.values()));before=nav;after=before+total
        if after<=0:fail('Bankruptcy; no return clipping')
        factor=float(np.log1p(total/before)/total) if abs(total)>1e-12 else 1/before
        for a,value in delta.items():
            if a in active:active[a]['log_growth']+=float(value*factor)
            elif abs(value)>1e-9:raise AssertionError('Unattributed own-asset PnL')
        nav=after
    def mark_at(prices):
        ids=np.flatnonzero(q>0)
        if len(ids):
            if not np.isfinite(prices[ids]).all() or (prices[ids]<=0).any():fail(f'Missing actual held quote at {date}: '+','.join(names[a] for a in ids if not np.isfinite(prices[a]) or prices[a]<=0))
            change({int(a):float(q[a]*(prices[a]-mark[a])) for a in ids});mark[ids]=prices[ids]
    def cancel(order,reason):
        order['status']=reason;order['cancelled_at']=str(date);order['unfilled_quantity']=order['remaining'];order['average_price']=order['filled_notional']/order['filled_quantity'] if order['filled_quantity'] else None
    def plan(weights,known_index):
        nonlocal entry_requested
        prior_deadline={a:o['expires_i'] for a,o in pending.items() if o['must_exit']}
        for o in pending.values():cancel(o,'CANCELLED_REPLACED_TARGET')
        pending.clear()
        for a in range(N):
            if weights[a]>0 and not m['eligible'][known_index,a]:raise ValueError('Non-PIT target '+names[a])
            if weights[a]<=0 and q[a]<=0:continue
            price=float(P[i,a,0])
            if not np.isfinite(price) or price<=0:price=float(P[known_index,a,3])
            if not np.isfinite(price) or price<=0:
                if q[a]>0:fail('Cannot price held exit '+names[a])
                continue
            desired=weights[a]*nav/(price*(1+slip)*(1+fee));delta=desired-q[a]
            if abs(delta)*price<e['min_order_usd'] and weights[a]>0:continue
            if abs(delta)<1e-12:continue
            side='buy' if delta>0 else 'sell';ttl=e['entry_ttl_bars'] if side=='buy' else e['exit_ttl_bars'];must_exit=side=='sell' and weights[a]==0
            expires=i+ttl-1
            if must_exit and a in prior_deadline:expires=min(expires,prior_deadline[a])
            order=dict(id=len(orders)+1,asset=names[a],side=side,created_at=str(date),signal_at=str(dates[known_index]),available_at=str(dates[known_index]+pd.Timedelta(hours=4,seconds=e['publication_latency_seconds'])),created_i=int(i),expires_i=int(expires),ttl_bars=ttl,requested_quantity=float(abs(delta)),requested_notional=float(abs(delta)*price),remaining=float(abs(delta)),filled_quantity=0.,filled_notional=0.,status='OPEN',must_exit=must_exit,reference_price=price)
            orders.append(order);pending[a]=order
            if side=='buy':entry_requested+=order['requested_notional']
    def execute(a,quantity):
        nonlocal cash,partials,entry_filled,next_episode,fee_bar,slip_bar,turn_bar,fee_usd,slip_usd,turn_usd
        order=pending[a];sign=1 if order['side']=='buy' else -1;price=P[i,a,0];execution=price*(1+sign*slip)
        notional=quantity*execution
        if notional+1e-9<e['min_order_usd']:return
        if sign>0 and notional*(1+fee)>cash+1e-7:raise AssertionError('Unfunded buy')
        if sign<0 and quantity>q[a]+1e-10:raise AssertionError('Spot short')
        if a not in active:
            next_episode+=1;active[a]=dict(id=next_episode,asset=names[a],entry=str(date),exit=None,log_growth=0.,dollar_pnl=0.,buy_notional=0.,sell_notional=0.)
        before=nav;charge=notional*fee;slippage=quantity*abs(execution-price)
        cash-=sign*notional+charge;q[a]+=sign*quantity;mark[a]=price
        active[a]['dollar_pnl']-=sign*notional+charge
        active[a]['buy_notional' if sign>0 else 'sell_notional']+=notional
        change({a:-charge-slippage});fee_bar+=charge/before;slip_bar+=slippage/before;turn_bar+=notional/before
        fee_usd+=charge;slip_usd+=slippage;turn_usd+=notional
        partial=quantity<order['remaining']-1e-10
        if partial:partials+=1
        order['remaining']=max(0.,order['remaining']-quantity);order['filled_quantity']+=quantity;order['filled_notional']+=notional
        order['average_price']=order['filled_notional']/order['filled_quantity']
        if sign>0:entry_filled+=quantity*order['reference_price']
        if details:fills.append(dict(date=str(date),order_id=order['id'],asset=names[a],side=order['side'],quantity=float(quantity),reference_price=float(price),fill_price=float(execution),notional=float(notional),fee=float(charge),slippage=float(slippage),partial=bool(partial),remaining_quantity=order['remaining'],available_at=order['available_at'],signal_at=order['signal_at'],capacity_quote=float(m['quote'][i-2,a]),episode=active[a]['id']))
        if order['remaining']<=max(1e-12,order['requested_quantity']*1e-12):
            order['status']='FILLED';order['unfilled_quantity']=order['remaining'];order['completed_at']=str(date);pending.pop(a)
        if q[a]<=max(1e-12,quantity*1e-12):
            # Floating subtraction residue only, never a minimum-notional writeoff.
            assert abs(q[a]*price)<1e-7;q[a]=0.
            ep=active.pop(a);ep.update(exit=str(date),holding_days=(date-pd.Timestamp(ep['entry']))/pd.Timedelta(days=1));episodes.append(ep)
    date=dates[ix[0]]
    for i in ix:
        date=dates[i];before=nav;fee_bar=slip_bar=turn_bar=fee_usd=slip_usd=turn_usd=0.;path=[1.];mark_at(P[i,:,0]);path.append(nav/before)
        if liquidate and i>=scheduled_start and not forced:
            forced=True;plan(np.zeros(N),max(0,i-lag))
        elif not forced and i>=ix[0]+lag-2:
            j=i-lag
            if j>=0 and (i==ix[0]+lag-2 or t['event'][j] or not np.array_equal(W[j],last_target)):
                plan(W[j],j);last_target=W[j].copy()
        cap={}
        for a,order in list(pending.items()):
            if i>order['expires_i']:
                cancel(order,'CANCELLED_TTL');pending.pop(a)
                if order['must_exit'] and q[a]*mark[a]>.01:fail(f'Exit TTL exhausted at {date}: {names[a]}, residual {q[a]*mark[a]:.8f} USD')
                continue
            price=P[i,a,0];known=m['quote'][i-2,a] if i>=2 else np.nan
            if not np.isfinite(price) or price<=0 or not np.isfinite(known) or known<=0 or P[i,a,4]<=0:continue
            execution=price*(1+slip if order['side']=='buy' else 1-slip)
            cap[a]=min(order['remaining'],known*e['participation']/execution,q[a] if order['side']=='sell' else np.inf)
        for a in sorted(cap):
            if a in pending and pending[a]['side']=='sell':execute(a,cap[a])
        buys={a:cap[a] for a in sorted(cap) if a in pending and pending[a]['side']=='buy'}
        required=sum(v*P[i,a,0]*(1+slip)*(1+fee) for a,v in buys.items());scale=min(1.,max(0.,cash)/required) if required>0 else 0.
        for a,amount in buys.items():execute(a,amount*scale)
        path.append(nav/before)
        held=np.flatnonzero(q>0)
        if len(held):
            if not np.isfinite(P[i,held,:4]).all() or (P[i,held,:4]<=0).any():fail('Missing actual held OHLC '+str(date))
            path += [(cash+float(np.dot(q[held],P[i,held,k])))/before for k in [1,2]]
        mark_at(P[i,:,3]);path.append(nav/before)
        identity=cash+float(np.dot(q[held],mark[held]))
        if abs(identity-nav)>max(1e-6,abs(nav)*1e-10):raise AssertionError('Cash/quantity NAV reconciliation')
        rows.append(dict(date=date,net_return=nav/before-1,equity=nav/capital,nav_usd=nav,cash_usd=cash,turnover=turn_bar,fee=fee_bar,slippage=slip_bar,funding=0.,liquidation=0.,path=path,gross_exposure=(nav-cash)/nav,fee_usd=fee_usd,slippage_usd=slip_usd,turnover_usd=turn_usd))
    for a,order in list(pending.items()):cancel(order,'CANCELLED_WINDOW_END')
    if liquidate and np.dot(q,mark)>.01:fail(f'Window end cannot safely close: {np.dot(q,mark):.8f} USD remains')
    result=pack();attribution=sum(ep['log_growth'] for ep in result['episodes'])
    assert abs(attribution-np.log(nav/capital))<1e-8,'Episode attribution must reconcile actual NAV'
    return result

def summarize(run):
    row=_parent.summarize(run);eps=run['episodes'];asset={s:sum(e['log_growth'] for e in eps if e['asset']==s) for s in sorted({e['asset'] for e in eps})}
    total=sum(asset.values());positive=sum(max(0.,e['log_growth']) for e in eps)
    row.update(asset_concentration=max([max(0.,v)/total for v in asset.values()],default=0.) if total>0 else None,trade_concentration=max([max(0.,e['log_growth'])/total for e in eps],default=0.) if total>0 else None,positive_profit_asset_share=max([sum(max(0.,e['log_growth']) for e in eps if e['asset']==s)/positive for s in asset],default=0.) if positive>0 else None,positive_profit_trade_share=max([max(0.,e['log_growth'])/positive for e in eps],default=0.) if positive>0 else None,asset_log_growth=asset,asset_dollar_pnl={s:sum(e['dollar_pnl'] for e in eps if e['asset']==s) for s in asset},partial_fills=run['partial_fills'],entry_fill_ratio=min(1.,run['entry_filled']/run['entry_requested']) if run['entry_requested']>0 else 1.,cancelled_orders=sum(o['status'].startswith('CANCELLED') for o in run['orders']),unfilled_quantity_by_asset={s:sum(o.get('unfilled_quantity',0.) for o in run['orders'] if o['asset']==s) for s in asset},residual_positions=run['residual_positions'])
    row.update(fee_usd=float(run['daily'].fee_usd.sum()),slippage_usd=float(run['daily'].slippage_usd.sum()),funding_usd=0.,turnover_usd=float(run['daily'].turnover_usd.sum()),fill_count=sum(o['filled_quantity']>0 for o in run['orders']),ending_nav=run['ending_nav'])
    return row
