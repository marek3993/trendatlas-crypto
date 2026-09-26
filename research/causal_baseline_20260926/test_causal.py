"""Regression checks for timing, economic identity, costs and chart separation."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd
from collect_inputs import extract_verified, safe_path, sha, ADDRESS
from run import HERE, REPO, causal, prices_from_raw

ZERO=causal.Costs(0,0,0,0)

def signal(day,coin,weight=1):
    return {'signal_data_day':day,'signal_available_at':(pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1,hours=12)).isoformat(),
            'selected_asset':coin,'target_exposure':0 if coin=='CASH' else weight,'source_file':'fixture_signals.csv','source_row':2}

def prices():
    days=pd.date_range('2024-01-01',periods=9,tz='UTC')
    values={'BTC':[100,100,100,80,80,100,120,130,130],
            'AVAX':[10,10,10,20,20,22,22,22,22],
            'DOGE':[1,1,1,1.1,1.1,1.1,1.1,1.1,1.1],
            'TRX':[1,1,1,2,2,2,2,2,2]}
    return pd.DataFrame([{'asset':a,'timestamp':t,'price':v,'source_file':a+'.csv','source_row':i+2}
                         for a,vs in values.items() for i,(t,v) in enumerate(zip(days,vs))])

def ledger(items,costs=ZERO):
    return causal.build_ledger(pd.DataFrame(items),prices(),start='2024-01-01',end='2024-01-09',costs=costs)

class AccountingTests(unittest.TestCase):
    def test_cash_at_close_d_cannot_erase_held_loss(self):
        out=ledger([signal('2024-01-01','BTC'),signal('2024-01-03','CASH')]).set_index('date')
        self.assertAlmostEqual(out.loc['2024-01-03','net_strategy_return'],-.2)
        self.assertEqual(out.loc['2024-01-03','executed_held_asset'],'BTC')
        self.assertEqual(out.loc['2024-01-05','executed_held_asset'],'CASH')

    def test_new_avax_cannot_receive_pre_entry_move(self):
        out=ledger([signal('2024-01-01','BTC'),signal('2024-01-03','AVAX')]).set_index('date')
        self.assertEqual(out.loc['2024-01-03','executed_held_asset'],'BTC')
        self.assertAlmostEqual(out.loc['2024-01-03','gross_strategy_return'],-.2)
        self.assertAlmostEqual(out.loc['2024-01-05','gross_strategy_return'],.1)

    def test_doge_and_trx_use_symbol_keyed_prices(self):
        for coin,want in [('DOGE',.1),('TRX',1.)]:
            out=ledger([signal('2024-01-01',coin)]).set_index('date')
            self.assertAlmostEqual(out.loc['2024-01-03','raw_asset_return'],want)
            self.assertEqual(out.loc['2024-01-03','price_source_file_start'],coin+'.csv')

    def test_base_and_missing_asset_rejected(self):
        for name in ['BASE','BASEUSDT',None,float('nan'),'']:
            with self.assertRaises(ValueError):
                ledger([signal('2024-01-01',name)])

    def test_all_asset_joins_are_order_independent_and_candidate_is_not_holding(self):
        coins=['BTC','ETH','BNB','XRP','SOL','ADA','DOGE','LINK','AVAX','LTC','TRX','DOT']
        days=pd.date_range('2024-01-01',periods=len(coins))
        gov=pd.DataFrame({'date':days,'executed_regime':'BASE','executed_position':'BASE','chosen_asset':'DOGE'})
        base=pd.DataFrame({'date':days,'base_asset':coins})
        self.assertEqual(causal.economic_assets(gov[gov.columns[::-1]],base.sample(frac=1,random_state=17)).tolist(),coins)
        with self.assertRaises(ValueError):
            causal.economic_assets(gov,pd.concat([base,base.iloc[:1]]))
        with self.assertRaises(ValueError):
            causal.economic_assets(gov,base.iloc[1:])

    def test_costs_exactly_explain_gross_to_net(self):
        out=ledger([signal('2024-01-01','BTC',1.25),signal('2024-01-04','AVAX'),signal('2024-01-06','CASH')],causal.Costs())
        np.testing.assert_allclose(out.gross_strategy_return-out[['fees','slippage','borrow','funding']].sum(axis=1),out.net_strategy_return,atol=1e-15)
        self.assertTrue((out.loc[~out.transition_flag,['fees','slippage']]==0).all().all())
        self.assertGreater(out.borrow.sum(),0);self.assertGreater(out.funding.sum(),0)

    def test_gross_uses_actual_drifting_exposure_and_fixed_units(self):
        out=ledger([signal('2024-01-01','BTC',1.25)],causal.Costs()).set_index('date')
        prev=out.loc['2024-01-03'];nxt=out.loc['2024-01-04']
        self.assertAlmostEqual(nxt.exposure,prev.exposure*(1+prev.raw_asset_return)/(1+prev.net_strategy_return))
        self.assertFalse(nxt.transition_flag);self.assertEqual(nxt.fees,0)
        active=out.exposure.gt(0)
        np.testing.assert_allclose(out.loc[active,'gross_strategy_return'],out.loc[active,'exposure']*(out.loc[active,'source_price_end']/out.loc[active,'source_price_start']-1),atol=1e-15)

    def test_late_signal_is_not_backfilled(self):
        s=signal('2024-01-01','AVAX');s['signal_available_at']='2024-01-06T01:00:00Z'
        out=ledger([s]).set_index('date')
        self.assertTrue(out.loc[:'2024-01-06','executed_held_asset'].eq('CASH').all())
        self.assertEqual(out.loc['2024-01-07','executed_held_asset'],'AVAX')

    def test_old_same_day_return_columns_cannot_enter_new_ledger(self):
        items=[signal('2024-01-01','BTC')]
        before=ledger(items)
        items[0].update(return_net=999,probe_strategy_return_gross=999,model_equity=999,real_account_pnl=999)
        pd.testing.assert_frame_equal(before,ledger(items))

    def test_chart_rejects_active_rows_without_availability_or_prices(self):
        out=ledger([signal('2024-01-01','BTC')])
        for column,value in [('signal_available_at',''),('source_price_start',np.nan)]:
            broken=out.copy();broken.loc[broken.exposure.gt(0),column]=value
            with self.assertRaises(ValueError): causal.model_chart(broken,prices())

    def test_missing_price_and_duplicate_keys_fail_closed(self):
        for p in [prices().iloc[1:],pd.concat([prices(),prices().iloc[:1]])]:
            # A BTC signal is already available at the first interval here.
            with self.assertRaises(ValueError):
                causal.build_ledger(pd.DataFrame([signal('2023-12-30','BTC')]),p,start='2024-01-01',end='2024-01-09')

    def test_chart_contract_matches_ledger_and_separates_account(self):
        out=ledger([signal('2024-01-01','BTC')],causal.Costs())
        chart=causal.model_chart(out,prices().query("asset == 'BTC'"))
        np.testing.assert_allclose(chart.model_index,(1+out.net_strategy_return).cumprod(),atol=0,rtol=0)
        poisoned=out.assign(real_account_pnl=1e12,real_account_index=1e20,model_equity=-999)
        pd.testing.assert_frame_equal(chart,causal.model_chart(poisoned,prices().query("asset == 'BTC'")))
        account={'ledger_type':'exchange_native_real_account','rows':[{'date':'2024-01-01','cash_flow_adjusted_return':.02,'model_equity':1e20}]}
        self.assertAlmostEqual(causal.account_chart(account).real_account_index.iloc[0],1.02)
        with self.assertRaises(ValueError): causal.account_chart({'rows':out.to_dict('records')})
        with self.assertRaises(ValueError): causal.account_chart({'ledger_type':'exchange_native_real_account','rows':[{'date':'2024-01-01','model_equity':12}]})
        with self.assertRaises((ValueError,AttributeError,KeyError)): causal.model_chart(pd.DataFrame(account['rows']),prices())

class FrozenEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((HERE/'input_bundle.manifest.json').read_text())
        cls.root=Path(tempfile.mkdtemp(prefix='test-inputs-',dir=HERE/'scratch'))
        extract_verified(HERE/'input_bundle.zip',cls.manifest,cls.root)
        sys.path.insert(0,str(cls.root/'scripts'))

    def test_actual_close_filter_changes_next_decision_not_earned_day(self):
        # Exercise the actual captured production helper, including its known
        # same-day return defect. Only its target output enters the new ledger.
        import dev_only_phase68g_etf_flow_impulse_probe as probe
        import dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity as cooldown
        daily=pd.DataFrame({'date':pd.date_range('2023-12-20',periods=19).strftime('%Y-%m-%d'),'close':np.arange(100.,119.)})
        changed=daily.copy();changed.loc[changed.date.eq('2024-01-03'),'close']=50.
        outputs=[]
        for i,raw in enumerate([daily,changed]):
            path=self.root/f'close_mutation_{i}.csv';raw.to_csv(path,index=False)
            frame=probe.load_btc_frame(path).loc['2024-01-01':'2024-01-07'].copy()
            frame['baseline_cash']=True;frame['hard_invalidation_on']=False
            frame['flow_2_of_last_3_positive_flag']=True;frame['permission_on']=frame.btc_price_filter_pass
            frame['portfolio_held_asset']='CASH';frame['effective_leverage']=0.;frame['realistic_ret_gross']=0.
            state,_=cooldown.build_cooldown_state_machine(frame,15)
            signals=[signal(d.strftime('%Y-%m-%d'),r.probe_held_asset,r.probe_effective_leverage) for d,r in state.iterrows()]
            outputs.append((state,ledger(signals).set_index('date')))
        self.assertNotEqual(outputs[0][0].loc['2024-01-03','probe_held_asset'],outputs[1][0].loc['2024-01-03','probe_held_asset'])
        # Keep the execution-price tape fixed: changing a decision input cannot
        # rewrite PnL. Changing a held asset's actual price would legitimately do so.
        pd.testing.assert_series_equal(outputs[0][1].loc[:'2024-01-04','net_strategy_return'],outputs[1][1].loc[:'2024-01-04','net_strategy_return'])
        self.assertNotEqual(outputs[0][1].loc['2024-01-05','executed_held_asset'],outputs[1][1].loc['2024-01-05','executed_held_asset'])

    def test_input_archive_integrity_privacy_and_path_safety(self):
        with zipfile.ZipFile(HERE/'input_bundle.zip') as z:
            self.assertEqual(len(z.namelist()),len(set(z.namelist())))
            for name in z.namelist():
                safe_path(name);data=z.read(name)
                self.assertEqual(sha(data),self.manifest['files'][name]['sha256'])
                self.assertIsNone(ADDRESS.search(data.decode('utf-8',errors='replace')),name)
                self.assertNotIn(b'-----BEGIN PRIVATE KEY-----',data,name)
                if name.endswith(('production_run_manifest.json','latest_production_run.json')):
                    obj=json.loads(data);self.assertNotIn('multi_account_execution',obj);self.assertNotIn('account_equity_before',obj)
        for bad in ['../escape','/absolute','C:\\private','.env']:
            with self.assertRaises(ValueError): safe_path(bad)

    def test_every_price_identifies_exact_raw_row_and_column(self):
        tape=prices_from_raw(self.root)
        for source,group in tape.groupby('source_file'):
            raw=pd.read_csv(self.root/source)
            for row in group.itertuples():
                col='close' if row.source_column.startswith('close_terminal') else 'open'
                self.assertEqual(row.price,raw.iloc[row.source_row-2][col])

class ArtifactTests(unittest.TestCase):
    def test_published_input_hashes_and_raw_reproduction(self):
        root=HERE/'results'
        self.assertTrue(json.loads((root/'original_reproduction.json').read_text())['passed'])
        self.assertEqual(json.loads((root/'raw_rebuild_check.json').read_text())['phase60_differences'],{})
        self.assertTrue(all(r['match'] for r in json.loads((root/'input_verification.json').read_text())['declared_direct_inputs']))

    def test_full_ledger_and_dashboard_contract(self):
        root=HERE/'results';l=pd.read_csv(root/'causal_ledger.csv').fillna({'signal_available_at':''})
        causal.validate_ledger(l)
        chart=pd.read_csv(root/'dashboard_model_chart.csv')
        np.testing.assert_allclose(chart.model_index,(1+l.net_strategy_return).cumprod(),rtol=1e-12,atol=1e-12)
        self.assertFalse(l.executed_held_asset.eq('BASE').any())
        self.assertTrue((pd.to_datetime(l.signal_available_at,utc=True,errors='coerce')[l.exposure.gt(0)]<=pd.to_datetime(l.return_interval_start,utc=True)[l.exposure.gt(0)]).all())

    def test_signed_daily_attribution_reconciles_and_does_not_erase_trx_gain(self):
        comparison=pd.read_csv(HERE/'results/daily_comparison.csv').set_index('date')
        np.testing.assert_allclose(comparison[['identity_and_gross_definition_delta_pp','timing_and_executed_exposure_delta_pp','explicit_cost_delta_pp']].sum(axis=1),comparison.removed_net_percentage_points,rtol=1e-10,atol=1e-10)
        self.assertEqual(comparison.loc['2024-12-03','executed_held_asset'],'TRX')
        self.assertGreater(comparison.loc['2024-12-03','net_strategy_return'],.95)
        self.assertLess(comparison.loc['2025-01-07','net_strategy_return'],-.02)
        self.assertLess(comparison.loc['2026-09-24','net_strategy_return'],0)

    def test_two_clean_full_replays_are_bitwise_identical(self):
        first=HERE/'results';second=HERE/'scratch/determinism'
        names=json.loads((first/'reproduction_manifest.json').read_text())['result_sha256']
        for name,digest in names.items():
            self.assertEqual(sha((first/name).read_bytes()),digest,name)
            self.assertEqual(sha((second/name).read_bytes()),digest,name)

if __name__=='__main__':
    unittest.main(verbosity=2)
