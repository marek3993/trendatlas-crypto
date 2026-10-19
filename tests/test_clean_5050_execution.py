"""Synthetic exchange tests. No HTTP or real credential is used."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trendatlas_clean.core import STRATEGY_ID
from trendatlas_clean.execution import Engine
from trendatlas_clean.execution_cli import validate_signal
from trendatlas_clean.hyperliquid import Broker, account_from, catalog_from, normalize_status
from trendatlas_clean.journal import Journal, ConfirmedRejection, NoSubmission, target_binding
from trendatlas_clean.portfolio import Account, Catalog, Market, Policy, Position, normalized_weights, order_price, plan, reconcile


def markets():
    ms = [Market('spot:@142', 'BTC', 'spot', '@142', 10142, 5, 50000, token_index=197),
          Market('spot:@151', 'ETH', 'spot', '@151', 10151, 4, 2500, token_index=221),
          Market('perp:BTC', 'BTC', 'perp', 'BTC', 0, 5, 50000),
          Market('perp:SOL', 'SOL', 'perp', 'SOL', 5, 2, 100),
          Market('perp:ZEC', 'ZEC', 'perp', 'ZEC', 30, 2, 50)]
    return Catalog({m.key:m for m in ms}, {'BTC':'spot:@142','ETH':'spot:@151','SOL':'perp:SOL','ZEC':'perp:ZEC'})


def signal(weights, day='2026-10-17'):
    return {'strategy_id': STRATEGY_ID, 'decision_closed_day_utc':day, 'drzat_pocas_dna_utc':'2026-10-18', 'ciel_vahy':weights}


class FakeBroker:
    def __init__(self, positions=None, *, behavior='fill', catalog=None):
        self.cat = catalog or markets()
        self.positions = deepcopy(positions or {})
        self.cash = 100 - sum(p.quantity*p.mark for p in self.positions.values() if p.venue=='spot')
        self.orders, self.actions = {}, []
        self.behavior = behavior
        self.counter = 0
    def catalog(self):
        return self.cat
    def snapshot(self):
        equity = self.cash + sum(p.quantity*p.mark for p in self.positions.values() if p.venue=='spot')
        held = sum(abs(p.quantity*p.mark) for p in self.positions.values() if p.venue=='perp')
        open_orders = [{'cloid':c} for c,o in self.orders.items() if o['state']=='OPEN']
        return Account(equity, deepcopy(self.positions), max(0,self.cash-held), max(0,self.cash-held), open_orders=open_orders)
    def quote(self, m):
        return m.mark*.9999, m.mark*1.0001
    def _fill(self, payload, fraction=1):
        m=self.cat.markets[payload['market_key']]
        old=self.positions.get(m.key)
        q=payload['quantity']*fraction*(1 if payload['side']=='BUY' else -1)
        qty=(old.quantity if old else 0)+q
        self.positions[m.key]=Position(m.key,qty,m.mark,m.logical,m.venue,(old.leverage if old else 1) if m.venue=='perp' else None)
        if m.venue=='spot': self.cash-=q*m.mark
    def place(self,payload,cloid):
        self.counter+=1
        self.actions.append(('place',deepcopy(payload),cloid))
        order={'state':'OPEN','remaining':payload['quantity'],'oid':self.counter}
        self.orders[cloid]=order
        if self.behavior=='unknown':
            del self.orders[cloid]
            raise TimeoutError('synthetic')
        if payload['tif']=='Ioc' or self.behavior in {'fill','lost_fill'}:
            self._fill(payload)
            order.update(state='FILLED',remaining=0)
        elif self.behavior=='partial':
            self._fill(payload, .5)
            order['remaining']*=.5
        if self.behavior=='lost_fill': raise TimeoutError('synthetic')
        return deepcopy(order)
    def order_status(self,cloid):
        return deepcopy(self.orders.get(cloid,{'state':'NOT_FOUND'}))
    def cancel(self,key,cloid):
        self.actions.append(('cancel',key,cloid))
        if self.behavior!='uncancelable': self.orders[cloid]['state']='CANCELED'
    def set_leverage(self,m,value):
        self.actions.append(('leverage',m.key,value))
        if m.key in self.positions:
            self.positions[m.key]=replace(self.positions[m.key],leverage=value)


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.cat=markets(); self.policy=Policy(maker_wait_seconds=0,poll_seconds=.001)
    def test_cash_to_two_legs(self):
        p=plan({'BTC':.5,'SOL':.5},Account(100,{},100,100),self.cat)
        self.assertFalse(p.exits)
        self.assertEqual({t.market_key for t in p.entries},{'spot:@142','perp:SOL'})
        self.assertLessEqual(sum(t.notional for t in p.entries),100)
    def test_sol_to_zec_keeps_btc(self):
        positions={'spot:@142':Position('spot:@142',.001,50000,'BTC','spot'), 'perp:SOL':Position('perp:SOL',.5,100,'SOL','perp',1)}
        p=plan({'BTC':.5,'ZEC':.5},Account(100,positions,50,0),self.cat)
        self.assertEqual([t.logical for t in p.exits],['SOL'])
        self.assertEqual([t.logical for t in p.entries],['ZEC'])
    def test_cash_closes_all_venues_and_shorts(self):
        positions={'spot:@142':Position('spot:@142',.001,50000,'BTC','spot'),'perp:SOL':Position('perp:SOL',-.5,100,'SOL','perp',2)}
        p=plan({'CASH':1},Account(100,positions,50,50),self.cat)
        self.assertEqual(len(p.exits),2)
        self.assertEqual(next(t for t in p.exits if t.logical=='SOL').side,'BUY')
        self.assertFalse(p.entries)
    def test_missing_market_does_not_erase_exit(self):
        positions={'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',1)}
        p=plan({'BTC':.5,'TRX':.5},Account(100,positions,0,0),self.cat)
        self.assertEqual([t.logical for t in p.exits],['SOL'])
        self.assertIn('MARKET_UNAVAILABLE:TRX',p.entry_blockers)
        self.assertEqual([t.logical for t in p.entries],['BTC'])
    def test_legacy_btc_perp_is_replaced_by_spot(self):
        p=plan({'BTC':1},Account(100,{'perp:BTC':Position('perp:BTC',.002,50000,'BTC','perp',10)},100,0),self.cat)
        self.assertEqual(p.exits[0].market_key,'perp:BTC')
        self.assertEqual(p.entries[0].market_key,'spot:@142')
    def test_no_base_no_negative_no_leverage(self):
        for weights in ({'BASE':1},{'BTC':1.01},{'BTC':-.1},{'BTC':float('nan')},{'BTC':float('inf')}):
            with self.subTest(weights=weights),self.assertRaises(ValueError): normalized_weights(weights)
    def test_dust_is_disclosed(self):
        a=Account(100,{'spot:@142':Position('spot:@142',.00001,50000,'BTC','spot')},99.5,99.5)
        r=reconcile({'CASH':1},a,self.cat)
        self.assertEqual(r['status'],'ALIGNED_WITH_EXCHANGE_DUST')
        self.assertTrue(r['actual_positions'])
        self.assertGreater(r['actual_gross_exposure'],0)
    def test_small_perp_exit_not_blocked_by_min_notional(self):
        a=Account(100,{'perp:SOL':Position('perp:SOL',.01,100,'SOL','perp',1)},99,99)
        p=plan({'CASH':1},a,self.cat)
        self.assertEqual(len(p.exits),1);self.assertTrue(p.exits[0].reduce_only)
    def test_prices_meet_spot_and_perp_precision(self):
        self.assertEqual(order_price(50000.123,self.cat.markets['spot:@142'],round_up=False),50000)
        self.assertEqual(order_price(100.00123,self.cat.markets['perp:SOL'],round_up=True),100.01)
    def test_unknown_position_retains_exit_blocker(self):
        a=Account(100,{'perp:OLD':Position('perp:OLD',1,10,'OLD','perp',1)},100,100)
        self.assertIn('EXIT_MARKET_UNAVAILABLE:perp:OLD',plan({'CASH':1},a,self.cat).exit_blockers)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'journal.sqlite3';self.j=Journal(self.path);self.addCleanup(self.j.close)
        self.policy=Policy(maker_wait_seconds=0,poll_seconds=.001)
    def engine(self,b): return Engine(b,self.j,self.policy)
    def test_cash_to_btc_sol_and_repeat_no_orders(self):
        b=FakeBroker();s=signal({'BTC':.5,'SOL':.5})
        r=self.engine(b).execute(s)
        self.assertTrue(r['account_aligned'],r)
        count=b.counter
        again=self.engine(b).execute(s)
        self.assertEqual(b.counter,count);self.assertEqual(again['status'],'ALREADY_COMPLETED')
    def test_rotation_exits_precede_entries(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',.5,100,'SOL','perp',1),'spot:@142':Position('spot:@142',.001,50000,'BTC','spot')})
        r=self.engine(b).execute(signal({'BTC':.5,'ZEC':.5}))
        self.assertTrue(r['account_aligned'],r)
        trades=[a[1] for a in b.actions if a[0]=='place']
        self.assertEqual(trades[0]['market_key'],'perp:SOL');self.assertEqual(trades[0]['side'],'SELL')
        self.assertTrue(all(t['market_key']!='spot:@142' for t in trades))
    def test_to_cash(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',1)})
        r=self.engine(b).execute(signal({'CASH':1}))
        self.assertTrue(r['account_aligned']);self.assertEqual(b.positions['perp:SOL'].quantity,0)
    def test_missing_target_still_exits_and_buys_independent_btc(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',1)})
        r=self.engine(b).execute(signal({'BTC':.5,'TRX':.5}))
        self.assertFalse(r['account_aligned']);self.assertEqual(b.positions['perp:SOL'].quantity,0)
        self.assertGreater(b.positions['spot:@142'].quantity,0)
    def test_partial_maker_then_ioc_only_remainder(self):
        b=FakeBroker(behavior='partial')
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertTrue(r['account_aligned'],r)
        trades=[x[1] for x in b.actions if x[0]=='place']
        self.assertEqual([t['tif'] for t in trades],['Alo','Ioc'])
        self.assertLess(trades[1]['quantity'],trades[0]['quantity'])
    def test_cancel_unconfirmed_never_falls_back(self):
        b=FakeBroker(behavior='uncancelable')
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertFalse(r['account_aligned']);self.assertEqual(b.counter,1)
        self.assertTrue(self.j.pending())
    def test_lost_response_fill_is_reconciled_not_resent(self):
        b=FakeBroker(behavior='lost_fill')
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertTrue(r['account_aligned']);self.assertEqual(b.counter,1)
        self.assertEqual(r['orders_sent_this_invocation'],1)
    def test_unknown_response_is_not_blindly_retried(self):
        b=FakeBroker(behavior='unknown');s=signal({'SOL':1})
        self.assertFalse(self.engine(b).execute(s)['account_aligned'])
        self.assertFalse(self.engine(b).execute(s)['account_aligned'])
        self.assertEqual(b.counter,1)
    def test_prepared_crash_reservation_can_be_abandoned(self):
        s=signal({'SOL':1});self.j.begin(s['decision_closed_day_utc'],target_binding(s),s)
        self.j.reserve(s['decision_closed_day_utc'],target_binding(s),'ENTRY','perp:SOL','Alo',{},0)
        b=FakeBroker();r=self.engine(b).execute(s)
        self.assertTrue(r['account_aligned']);self.assertFalse(self.j.pending())
    def test_nonce_survives_clock_regression_and_restart(self):
        self.assertEqual(self.j.nonce(100),100)
        self.assertEqual(self.j.nonce(99),101)
        other=Journal(self.path)
        try:self.assertEqual(other.nonce(1),102)
        finally:other.close()
    def test_target_revision_is_rejected(self):
        b=FakeBroker();self.engine(b).execute(signal({'CASH':1}))
        with self.assertRaisesRegex(ValueError,'DIFFERENT_TARGET'):self.engine(b).execute(signal({'SOL':1}))
    def test_existing_ten_x_setting_changed_to_one(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',10)})
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertTrue(r['account_aligned']);self.assertEqual(b.positions['perp:SOL'].leverage,1)
    def test_external_order_blocks_entries_not_exits(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',1)})
        b.orders['external']={'state':'OPEN','remaining':1,'oid':12}
        r=self.engine(b).execute(signal({'ZEC':1}))
        self.assertFalse(r['account_aligned']);self.assertEqual(b.positions['perp:SOL'].quantity,0)
        self.assertNotIn('perp:ZEC',b.positions)
    def test_process_death_after_exchange_fill_resumes_without_second_order(self):
        b=FakeBroker();original=b.place
        def interrupted(payload,cloid):
            original(payload,cloid)
            raise KeyboardInterrupt("synthetic process death")
        b.place=interrupted;s=signal({'SOL':1})
        with self.assertRaises(KeyboardInterrupt):self.engine(b).execute(s)
        self.assertEqual(self.j.pending()[0]['state'],'SUBMITTING')
        b.place=original
        self.assertTrue(self.engine(b).execute(s)['account_aligned'])
        self.assertEqual(b.counter,1)

    def test_pre_submit_transport_failure_does_not_create_uncertain_order(self):
        b=FakeBroker()
        def fail_before_request(payload,cloid):raise NoSubmission("synthetic catalog unavailable")
        b.place=fail_before_request
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertFalse(r['account_aligned']);self.assertEqual(r['orders_sent_this_invocation'],0)
        self.assertFalse(self.j.pending())

    def test_explicit_exchange_rejection_is_not_an_unknown_submission(self):
        b=FakeBroker()
        def rejected(payload,cloid):raise ConfirmedRejection("synthetic explicit provider rejection")
        b.place=rejected
        r=self.engine(b).execute(signal({'SOL':1}))
        self.assertFalse(r['account_aligned']);self.assertGreater(r['orders_sent_this_invocation'],0)
        self.assertFalse(self.j.pending())

    def test_prior_day_open_order_is_canceled_before_new_target_entry(self):
        b=FakeBroker(behavior='open')
        old=signal({'SOL':1},'2026-10-16');binding=target_binding(old)
        self.j.begin(old['decision_closed_day_utc'],binding,old)
        row=self.j.reserve(old['decision_closed_day_utc'],binding,'ENTRY','perp:SOL','Alo',{},0)
        self.j.update(row['cloid'],'OPEN')
        b.orders[row['cloid']]={'state':'OPEN','remaining':.5,'oid':1}
        b.behavior='fill'
        r=self.engine(b).execute(signal({'ZEC':1}))
        self.assertTrue(r['account_aligned'],r)
        self.assertEqual(b.actions[0][0],'cancel')
        self.assertEqual(self.j.order(row['cloid'])['state'],'CANCELED')

    def test_uncertain_entry_does_not_prevent_independent_exits(self):
        b=FakeBroker({'perp:SOL':Position('perp:SOL',1,100,'SOL','perp',1)})
        old=signal({'BTC':1},'2026-10-16');binding=target_binding(old)
        self.j.begin(old['decision_closed_day_utc'],binding,old)
        row=self.j.reserve(old['decision_closed_day_utc'],binding,'ENTRY','spot:@142','Alo',{},0)
        self.j.update(row['cloid'],'UNKNOWN')
        r=self.engine(b).execute(signal({'CASH':1}))
        self.assertFalse(r['account_aligned'])
        self.assertEqual(b.positions['perp:SOL'].quantity,0)
        self.assertEqual(b.counter,1)

    def test_stale_signal_cannot_be_executed(self):
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        validate_signal(signal({'CASH':1}),now)
        with self.assertRaisesRegex(ValueError,'STALE'):validate_signal(signal({'CASH':1},'2026-10-16'),now)


class AdapterTests(unittest.TestCase):
    def test_usdc_spot_route_chosen_not_usdh_or_perp(self):
        spot=[{'tokens':[{'index':0,'name':'USDC','szDecimals':8},{'index':1,'name':'USDH','szDecimals':8},{'index':197,'name':'UBTC','szDecimals':5}],
               'universe':[{'index':234,'name':'@234','tokens':[197,1]},{'index':142,'name':'@142','tokens':[197,0]}]},
              [{'coin':'@234','markPx':'50000'},{'coin':'@142','markPx':'50000'}]]
        perps=[('',0,[{'universe':[{'name':'BTC','szDecimals':5},{'name':'SOL','szDecimals':2}]},[{'markPx':'50000'},{'markPx':'100'}]])]
        cat=catalog_from(spot,perps)
        self.assertEqual(cat.target('BTC').asset_id,10142);self.assertEqual(cat.target('SOL').venue,'perp')
        spot[0]['universe']=[]
        self.assertIsNone(catalog_from(spot,perps).target('BTC'))
    def test_unified_equity_is_not_double_counted(self):
        spot={'balances':[{'coin':'USDC','token':0,'total':'50','hold':'10'}, {'coin':'UBTC','token':197,'total':'.001','hold':'0'}]}
        state={'marginSummary':{'accountValue':'999'},'withdrawable':'888','assetPositions':[]}
        a=account_from(spot,[state],'unifiedAccount',markets(),[])
        self.assertEqual(a.equity,100);self.assertEqual(a.spot_cash_free,40);self.assertEqual(a.perp_margin_free,40)
    def test_standard_equity_keeps_separate_balance(self):
        a=account_from({'balances':[{'coin':'USDC','token':0,'total':'50','hold':0}]},
                       [{'marginSummary':{'accountValue':'30'},'withdrawable':'30','assetPositions':[]}],'disabled',markets(),[])
        self.assertEqual(a.equity,80);self.assertEqual(a.perp_margin_free,30)
    def test_status_parser_all_terminal_categories(self):
        for raw,expected in [('filled','FILLED'),('open','OPEN'),('marginCanceled','CANCELED'),('badAloPxRejected','REJECTED')]:
            got=normalize_status({'status':'order','order':{'status':raw,'order':{'sz':'0.1','oid':3}}})
            self.assertEqual(got['state'],expected)
        self.assertEqual(normalize_status({'status':'unknownOid'})['state'],'NOT_FOUND')
    def test_unarmed_broker_cannot_send_exchange_action(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json';path.write_text(json.dumps({'kill_switch':False,'trading_enabled':True}))
            calls=[];b=Broker('0x'+'1'*40,None,path,transport=lambda *args:calls.append(args))
            with self.assertRaisesRegex(ValueError,'NOT_ARMED'):b._action({'type':'order'})
            self.assertEqual(calls,[])
    def test_kill_switch_is_reread_before_every_signed_action(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json';path.write_text(json.dumps({'kill_switch':True,'trading_enabled':True}))
            calls=[];b=Broker('0x'+'1'*40,None,path,transport=lambda *args:calls.append(args))
            b.wallet=object()
            with self.assertRaisesRegex(ValueError,'NOT_ARMED'):b._action({'type':'order'})
            self.assertEqual(calls,[])

    def test_insufficient_cash_never_posts_or_borrows(self):
        with tempfile.TemporaryDirectory() as temp:
            calls=[];b=Broker('0x'+'1'*40,None,Path(temp)/'unused',transport=lambda *args:calls.append(args))
            b.catalog=lambda:markets()
            b.snapshot=lambda:Account(100,{},0,0)
            result=b.place({'market_key':'spot:@142','side':'BUY','quantity':.001,'price':50000,
                            'reduce_only':False,'tif':'Alo'},'0x'+'1'*32)
            self.assertEqual(result['state'],'REJECTED');self.assertFalse(result['request_sent'])
            self.assertFalse(calls)

    def test_official_sdk_wire_contains_correct_asset_and_cloid(self):
        from hyperliquid.utils.signing import order_request_to_order_wire
        from hyperliquid.utils.types import Cloid
        c='0x'+'1'*32
        wire=order_request_to_order_wire({'coin':'@142','is_buy':True,'sz':.001,'limit_px':50000,
             'order_type':{'limit':{'tif':'Alo'}},'reduce_only':False,'cloid':Cloid.from_str(c)},10142)
        self.assertEqual(wire['a'],10142);self.assertEqual(wire['c'],c);self.assertEqual(wire['t'],{'limit':{'tif':'Alo'}})
    def test_shutdown_failed_permission_operation_closes_temporary_handle(self):
        spec=importlib.util.spec_from_file_location('shutdown',ROOT/'scripts/production/disable_phase68g.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'execution/config/execution_mode.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'kill_switch':False,'trading_enabled':True}))
            def ctl(*args):return subprocess.CompletedProcess(args,0, str(root) if args[0]=='show' else '', '')
            with patch.object(module.os,'fchmod',side_effect=OSError('synthetic'),create=True):
                with self.assertRaisesRegex(OSError,'synthetic'):module.disable(root,apply=True,systemctl=ctl)
            self.assertEqual(list(p.parent.glob('.clean-kill-*')),[])
            self.assertTrue(p.with_name('execution_mode.pre_clean_shutdown.json').exists())


if __name__=='__main__':unittest.main()
