from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import json
import hashlib
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.production.canonical_diagnostics import (
    FIELDS, SCALE, canonical_diagnostic_export, diagnostic_units, round_sqrt_ratio,
)
from scripts.execution.numeric_portability_audit import oracle, emulate_welford
from scripts.execution.compare_production_replay import unchanged_history

ROOT = Path(__file__).resolve().parents[1]


def frame(values):
    n = len(values)
    return pd.DataFrame({'date':pd.date_range('2020-01-01',periods=n).strftime('%Y-%m-%d'),
                         'return_net':values,'rolling_vol_30d':[math.nan]*n,
                         'rolling_sharpe_90d':[math.nan]*n,
                         'selected_asset':['AVAX']*n,'execution_target_exposure':[1.0]*n,
                         'trend_permission_active':[True]*n})


class DiagnosticPortabilityTests(unittest.TestCase):
    def assert_oracle(self, values):
        actual = diagnostic_units(values)
        with localcontext() as context:
            context.prec = 120
            for field,window,key in [(FIELDS[0],30,'volatility'),(FIELDS[1],90,'sharpe')]:
                low,high = oracle(values,window),oracle(values,window,precision=120)
                for i,(a,b) in enumerate(zip(low,high)):
                    av = None if a is None else a[key]
                    bv = None if b is None else b[key]
                    units = lambda x: None if x is None else int((x*SCALE).to_integral_value(rounding=ROUND_HALF_EVEN))
                    self.assertEqual(units(av),units(bv))
                    self.assertEqual(actual[field][i],units(bv))

    def test_contract_precision_is_existing_twelve_places(self):
        contract=json.loads((ROOT/'source_of_truth/diagnostic_numeric_contract.json').read_text(encoding='utf-8'))
        self.assertEqual(contract['scale'],SCALE)
        self.assertEqual(contract['decision_consumers'],[])

    def test_rounding_exact_midpoints_half_even(self):
        for floor in range(10):
            midpoint=(2*floor+1)**2
            self.assertEqual(round_sqrt_ratio(midpoint,4),floor+(floor%2))
            self.assertEqual(round_sqrt_ratio(midpoint*100-1,400),floor)
            self.assertEqual(round_sqrt_ratio(midpoint*100+1,400),floor+1)

    def test_full_window_boundaries(self):
        values=[0.01,-0.01]*60
        result=diagnostic_units(values)
        self.assertEqual(result[FIELDS[0]][:29],[None]*29)
        self.assertIsNotNone(result[FIELDS[0]][29])
        self.assertEqual(result[FIELDS[1]][:89],[None]*89)
        self.assertIsNotNone(result[FIELDS[1]][89])
        self.assert_oracle(values)

    def test_nan_is_zero_with_full_window(self):
        a=[0.01,math.nan,-0.01]*40
        self.assertEqual(diagnostic_units(a),diagnostic_units([0.01,0.0,-0.01]*40))
        self.assert_oracle(a)

    def test_zero_volatility_sharpe_null(self):
        for constant in (0.0,0.01,-0.01):
            result=diagnostic_units([constant]*120)
            self.assertEqual(result[FIELDS[0]][29:],[0]*91)
            self.assertEqual(result[FIELDS[1]],[None]*120)

    def test_cancellation_large_offset_small_dispersion(self):
        self.assert_oracle([Decimal('1000000')+Decimal(i%3)*Decimal('0.000000000001') for i in range(180)])

    def test_adversarial_outlier_leaves_window(self):
        self.assert_oracle([1.0,-1.0]+[0.0]*120+[1e-12,-1e-12]*60)

    def test_positive_scaling_preserves_sharpe(self):
        values=[0.012,-0.003,0.004]*60
        a,b=diagnostic_units(values),diagnostic_units([Decimal(str(v))*3 for v in values])
        self.assertEqual(a[FIELDS[1]],b[FIELDS[1]])

    def test_negating_returns_preserves_vol_reverses_sharpe(self):
        values=[0.012,-0.003,0.004]*60
        a,b=diagnostic_units(values),diagnostic_units([-v for v in values])
        self.assertEqual(a[FIELDS[0]],b[FIELDS[0]])
        self.assertEqual(a[FIELDS[1]],[None if v is None else -v for v in b[FIELDS[1]]])

    def test_row_order_fails_closed(self):
        data=frame([0.01]*100)
        with self.assertRaises(ValueError): canonical_diagnostic_export(data.iloc[::-1])
        data.loc[1,'date']=data.loc[0,'date']
        with self.assertRaises(ValueError): canonical_diagnostic_export(data)

    def test_non_lattice_and_infinite_inputs_fail_closed(self):
        for value in (0.0000000000001,math.inf,-math.inf):
            with self.assertRaises(ValueError): diagnostic_units([value]*100)

    def test_canonical_serialization_native_is_untouched(self):
        native=frame([0.01,-0.01]*60);before=native.copy(deep=True)
        native['rolling_vol_30d']=123456.0
        before=native.copy(deep=True)
        exported=canonical_diagnostic_export(native)
        pd.testing.assert_frame_equal(before,native)
        self.assertIn('0.191115148536',exported.to_csv(index=False))
        self.assertEqual(exported.to_csv(index=False),canonical_diagnostic_export(exported).to_csv(index=False))

    def test_every_non_diagnostic_column_unchanged_near_decision_thresholds(self):
        # Export is an identity for decision surfaces even at exact thresholds.
        native=frame([0.01,-0.01]*60)
        thresholds={'flow_3d_sum_usd':500_000_000.0,'btc_close_minus_ema':0.0,
                    'trend_score_minus_buy':0.0,'trend_score_minus_activation':0.0,
                    'effective_market_exposure':1e-9,'leverage_boundary':1.0+1e-9,
                    'cooldown_days':15.0,'positive_flow_count':2.0}
        for column,threshold in thresholds.items():
            native[column]=[math.nextafter(threshold,-math.inf),threshold,math.nextafter(threshold,math.inf)]*40
        exported=canonical_diagnostic_export(native)
        columns=[c for c in native if c not in FIELDS]
        pd.testing.assert_frame_equal(native[columns],exported[columns],check_exact=True)
        self.assertTrue(exported['selected_asset'].eq('AVAX').all())
        self.assertTrue(exported['execution_target_exposure'].eq(1.0).all())

    def test_frozen_history_matches_independent_oracle(self):
        fixture=json.loads((ROOT/'tests/fixtures/production_numeric_returns_20260928.json').read_text())
        self.assert_oracle(fixture['returns'])

    def test_historical_native_diagnostics_do_not_affect_export(self):
        fixture=json.loads((ROOT/'tests/fixtures/production_numeric_returns_20260928.json').read_text())
        data=frame(fixture['returns']);a=canonical_diagnostic_export(data)
        for field in FIELDS: data[field]=[float('inf')]*len(data)
        pd.testing.assert_frame_equal(a,canonical_diagnostic_export(data),check_exact=True)

    def check_cross_architecture(self,window):
        fixture=json.loads((ROOT/'tests/fixtures/production_numeric_returns_20260928.json').read_text())
        def software_fma(a,b,c):
            with localcontext() as context:
                context.prec=100
                return float(Decimal.from_float(a)*Decimal.from_float(b)+Decimal.from_float(c))
        for name,fused in [('pi',True),('vps',False)]:
            # Python 3.12 local runner lacks math.fma; correctly rounded Decimal
            # experiment is only a test fallback. Actual hosts use native 3.13 FMA.
            with patch.object(math,'fma',getattr(math,'fma',software_fma),create=True):
                values=emulate_welford(fixture['returns'],window,fused)
            sha=hashlib.sha256(json.dumps([v.hex() for v in values],separators=(',',':')).encode()).hexdigest()
            self.assertEqual(sha,fixture['native_variance_sha256'][f'{name}_{window}'])

    def test_arm_x86_rolling_volatility_root_cause_fixture(self): self.check_cross_architecture(30)
    def test_arm_x86_rolling_sharpe_root_cause_fixture(self): self.check_cross_architecture(90)

    def test_historical_decision_gate_rejects_any_changed_decision(self):
        before={'snapshot':{'asset':'AVAX','exposure':1},'timeseries':frame([0.01]*100).to_json(orient='split')}
        for column,value in [('selected_asset','BTC'),('execution_target_exposure',0.5),('trend_permission_active',False),('return_net',0.02)]:
            changed=frame([0.01]*100);changed.loc[10,column]=value
            self.assertFalse(unchanged_history(before,{'snapshot':before['snapshot'],'timeseries':changed.to_json(orient='split')}))

    def test_historical_decision_gate_accepts_only_diagnostic_changes(self):
        native=frame([0.01]*100)
        before={'snapshot':{'asset':'AVAX','exposure':1},'timeseries':native.to_json(orient='split')}
        after={'snapshot':{'asset':'AVAX','exposure':1},'timeseries':canonical_diagnostic_export(native).to_json(orient='split')}
        self.assertTrue(unchanged_history(before,after))
        after['snapshot']['asset']='BTC'
        self.assertFalse(unchanged_history(before,after))


if __name__=='__main__': unittest.main()
