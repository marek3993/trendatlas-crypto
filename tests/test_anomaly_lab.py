import copy
import io
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from research.phase2_v2.market import synthetic_market, digest, canonical
from research.phase2_v2.inputs import guarded_rows
from research.phase2_v2.contract import load as phase2_contract
from research.phase2_v2 import broker as phase2_broker
from research.anomaly_lab import runtime, broker
from research.anomaly_lab.contract import load
from research.anomaly_lab.rules import catalogue, validate, prepare, condition, clusters, target_map, neighbors
from research.anomaly_lab.discovery import describe
from research.anomaly_lab.statistics import alpha_for, block_test, block_interval
from research.anomaly_lab.accounting import check
from research.anomaly_lab.handoff import export, ingest, phase2_genes
from research.anomaly_lab.condition import ready
from research.anomaly_lab.audit import audit
from research.anomaly_lab.deploy import units


class AnomalyRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = synthetic_market()
        cls.production = {d.strftime('%Y-%m-%d'): ('BTC', .25) for d in cls.market.dates}

    def setUp(self):
        self.m = copy.deepcopy(self.market); self.f = prepare(self.m, self.production)
        self.rule = {'family': 'breakout', 'threshold': 40, 'horizon': 7, 'action': 'long'}

    def test_contract_and_finite_validated_schema(self):
        c = load(); self.assertFalse(c['orders_allowed']); self.assertEqual(len(catalogue()), 66)
        self.assertEqual(len({digest(r) for r in catalogue()}), 66)
        self.assertEqual(len(neighbors(self.rule)), 3)
        for rule in catalogue(): phase2_genes(rule)
        for bad in ({**self.rule, 'code': 'print(1)'}, {**self.rule, 'horizon': 1}, {**self.rule, 'action': 'BUY'}, {**self.rule, 'threshold': True}):
            with self.assertRaises(ValueError): validate(bad)

    def test_transitive_and_cross_asset_cluster_not_100_or_10_events(self):
        mask = np.zeros((120, 10), bool); mask[:100] = True; eligible = np.ones_like(mask)
        ranks = np.tile(np.arange(10), (120, 1)); assets = [str(k) for k in range(10)]
        events = clusters(mask, eligible, ranks, assets, 7, 0, 119)
        self.assertEqual(len(events), 1); self.assertEqual(events[0]['duration_days'], 100)
        self.assertEqual(len(events[0]['assets']), 10)
        eligible[50] = False
        self.assertEqual(len(clusters(mask, eligible, ranks, assets, 7, 0, 119)), 2)

    def test_data_anomaly_is_quarantined_and_missing_not_zero(self):
        i = self.m.dates.get_indexer(['2020-01-01'])[0]
        self.m.high[i, 1] = self.m.low[i, 1]/2
        self.m.quote[i+2, 2] = np.nan
        f = prepare(self.m, self.production)
        self.assertFalse(f['eligible'][i:i+60, 1].any())
        self.assertFalse(f['eligible'][i+2, 2]); self.assertEqual(f['health']['derivatives'], 'UNAVAILABLE')
        self.assertEqual(f['health']['volume_kind'], 'SPOT_MIXED_EXACT_AND_DECLARED_PROXY')
        self.m.assets[1] = 'LUNAUSDT@original'
        self.assertFalse(prepare(self.m, self.production)['eligible'][:, 1].any())

    def test_prefix_future_perturbation_changes_neither_conditions_nor_targets(self):
        lo, hi = self.m.dates.get_indexer(['2020-01-01', '2020-02-01'])
        before = {digest(r): target_map(self.m, self.f, r, lo, hi) for r in catalogue()}
        self.m.close[hi+1:] *= 500; self.m.high[hi+1:] *= 700; self.m.quote[hi+1:] *= 1000
        future = prepare(self.m, self.production)
        for r in catalogue(): self.assertEqual(before[digest(r)], target_map(self.m, future, r, lo, hi))

    def test_signal_publication_buffer_and_no_cluster_end_lookahead(self):
        lo, hi = self.m.dates.get_indexer(['2020-01-01', '2020-02-01'])
        mask = np.zeros_like(self.m.eligible); mask[lo, 0] = True
        with patch('research.anomaly_lab.rules.condition', return_value=mask):
            targets = target_map(self.m, self.f, self.rule, lo, hi)
            self.assertEqual(targets[self.m.dates[lo].strftime('%Y-%m-%d')], ('CASH', 0.))
            self.assertEqual(targets[self.m.dates[lo+1].strftime('%Y-%m-%d')], ('BTC', .25))
            mask[lo+1:hi, 0] = True
            continuing = target_map(self.m, self.f, self.rule, lo, hi)
        self.assertEqual(targets[self.m.dates[lo+1].strftime('%Y-%m-%d')], continuing[self.m.dates[lo+1].strftime('%Y-%m-%d')])

    def test_frequency_uses_eligible_data_and_separates_favorable_probability(self):
        lo, hi = self.m.dates.get_indexer(['2020-01-01', '2020-06-30'])
        mask = np.zeros_like(self.m.eligible); mask[lo:lo+100] = True
        self.f['eligible'][lo+100:hi+1] = False
        with patch('research.anomaly_lab.discovery.condition', return_value=mask): value = describe(self.m, self.f, self.rule, lo, hi, 1)
        self.assertEqual(value['frequency']['raw_asset_day_triggers'], 300)
        self.assertEqual(value['frequency']['independent_events'], 1)
        self.assertEqual(value['frequency']['eligible_calendar_observations'], 100)
        self.assertEqual(value['frequency']['eligible_asset_observations'], 300)
        self.assertAlmostEqual(value['frequency']['events_per_year'], 365.25/100)
        self.assertEqual(value['verdict'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('favorable_fraction', value['aftermath']); self.assertFalse(value['confirmed_trading_candidate'])

    def test_timestamp_guard_never_parses_prospective_columns(self):
        stream = io.BytesIO(b'date,close\n2026-09-25,100\n2026-09-26,SEALED\n2026-09-27,SEALED\n')
        self.assertEqual(list(guarded_rows(stream, phase2_contract())), [{'date': '2026-09-25', 'close': '100'}])
        self.assertTrue(stream.read().startswith(b'SEALED'))
        for origin in range(14): self.assertLess(runtime.training(origin)[-1][1], phase2_contract()['walk_forward']['validation_folds'][origin][0])
        self.assertEqual(runtime.training(0)[-1][1], '2019-12-17')

    def test_existing_engine_independent_accounting_and_cost_stress(self):
        folds = [['2020-01-01', '2020-03-31']]; lo, hi = runtime.index(self.m, folds)
        nominal = runtime.execute(self.m, self.f, self.rule, folds)
        evidence = check(self.m, target_map(self.m, self.f, self.rule, lo, hi), folds, nominal)
        self.assertTrue(evidence['passed']); self.assertLess(evidence['max_nav_error'], 1e-8)
        double = runtime.execute(self.m, self.f, self.rule, folds, 'double_cost')
        self.assertLessEqual(double['metrics']['net_return'], nominal['metrics']['net_return']+1e-10)
        self.assertEqual(evidence['days_checked'], 91)

    def test_continuous_equity_checkpoint_does_not_reset_at_fold_boundary(self):
        a = runtime.execute(self.m, self.f, self.rule, [['2020-01-01', '2020-03-31']])
        b = runtime.execute(self.m, self.f, self.rule, [['2020-04-01', '2020-06-30']], checkpoint=copy.deepcopy(a['checkpoint']))
        all_ = runtime.execute(self.m, self.f, self.rule, [['2020-01-01', '2020-06-30']])
        self.assertAlmostEqual(b['equity'][-1]['equity'], all_['equity'][-1]['equity'])
        self.assertEqual([r['equity'] for r in a['equity']+b['equity']], [r['equity'] for r in all_['equity']])

    def test_missing_held_price_invalidates_entire_book(self):
        # A constant historical target exercises an unpriced holding without silent liquidation.
        i = self.m.dates.get_indexer(['2020-02-01'])[0]; self.m.opening[i, 0] = np.nan
        with self.assertRaisesRegex(ValueError, 'missing_held_asset_price|invalid_execution_candle'):
            runtime.control(self.m, self.f, self.rule, [['2020-01-01', '2020-03-31']])

    def test_bad_positive_candle_cannot_create_pnl_edge(self):
        i = self.m.dates.get_indexer(['2020-02-01'])[0]
        self.m.close[i, 0] *= 2
        f = prepare(self.m, self.production)
        with self.assertRaisesRegex(ValueError, 'invalid_execution_candle'):
            runtime.control(self.m, f, self.rule, [['2020-01-01', '2020-03-31']])

    def test_lifetime_alpha_and_serial_blocks(self):
        self.assertLess(sum(alpha_for(t) for t in range(1, 10001)), .05)
        self.assertAlmostEqual(alpha_for(1), .025)
        insufficient = block_test([1.]*100, [1]*100, 1)
        self.assertIsNone(insufficient['p']); self.assertFalse(insufficient['rejected'])
        strong = block_test([.1]*12, np.arange(12)*30, 1, repeats=255)
        self.assertTrue(strong['rejected']); self.assertLess(strong['p'], .001)
        self.assertEqual(strong['blocks'], 12)

    def test_no_edge_synthetic_multiple_testing_with_cross_asset_dependence(self):
        # Independent common block signs, arbitrary intra-block serial dependence;
        # 20 adaptive hypothesis choices per run, spending continues across cycles.
        rng = np.random.default_rng(42); false_runs = 0; runs = 120
        for run in range(runs):
            magnitudes = rng.uniform(.001, .04, 10); common = rng.choice([-1., 1.], 10)
            rejected = False
            for trial in range(1, 21):
                # Past-only adaptive scale does not reveal this test block's signs.
                values = magnitudes*common*rng.uniform(.7, 1.3, 10)
                stat = block_test(np.repeat(values, 3), np.repeat(np.arange(10)*30, 3), trial, repeats=127, seed=run+trial)
                rejected |= stat['rejected']
            false_runs += rejected
        self.assertLessEqual(false_runs/runs, .075)
        self.assertLess(alpha_for(21), alpha_for(1))

    def test_moving_blocks_jointly_resample_missing_exposure(self):
        counts = np.zeros(180); counts[::10] = 1; covered = np.ones(180); covered[60:90] = 0; counts[60:90] = 0
        ci = block_interval(counts, covered, repeats=255, seed=10, scale=365.25)
        self.assertEqual(len(ci), 2); self.assertGreater(ci[1], ci[0]); self.assertGreater(ci[0], 0)

    def test_immutable_trials_resume_and_binding_change_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db = runtime.connect(directory); runtime.initialize(db, {'test': 1})
            hid = runtime.register(db, self.rule, 0, 'deterministic')
            trial = runtime.reserve(db, 0, hid, 'test', runtime.training(0))
            db.close(); db = runtime.connect(directory); runtime.initialize(db, {'test': 1})
            self.assertEqual(trial, runtime.reserve(db, 0, hid, 'test', runtime.training(0)))
            self.assertGreater(runtime.reserve(db, 1, hid, 'new_cycle', runtime.training(1)), trial)
            with self.assertRaises(ValueError): runtime.initialize(db, {'test': 2})
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM trials')
            with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE hypotheses SET source='other'")
            db.close()

    def test_broker_is_bounded_reuses_existing_transport_and_restores_globals(self):
        payload = {'cycle_id': load()['api_budget_id'], 'scope': 'anomaly_prior_training_only', 'training_cutoff': '2019-12-17',
                   'schema': load()['families'], 'horizons': [7, 14], 'aggregates': [{'id': str(k), 'values': 'v'*600} for k in range(50)],
                   'derivatives': 'UNAVAILABLE', 'historical_independence': 'NONE_PREVIOUSLY_SEEN'}
        self.assertLessEqual(len(canonical(broker.body(payload)).encode()), 6500)
        old = phase2_broker.wire_body
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); key = digest(payload)
            runtime.atomic(root/'requests'/f'{key}.json', {'hash': key, 'payload': payload})
            def transport(p, secret):
                self.assertNotIn('cycle_id', p); self.assertNotIn('seen_hashes', p)
                return json.dumps({'hypotheses': []}), {'total_tokens': 100, 'usd_upper_estimate': .0001, 'billing_known': True}, 'mock'
            with patch.object(phase2_broker, 'api_key', return_value='TEST_ONLY'):
                self.assertTrue(broker.once(root, transport)); self.assertFalse(broker.once(root, transport))
            self.assertEqual(json.loads((root/'responses'/f'{key}.json').read_text())['usage']['total_tokens'], 100)
        self.assertIs(phase2_broker.wire_body, old)

    def test_uncertain_ai_request_never_retried(self):
        payload = {'cycle_id': load()['api_budget_id'], 'scope': 'anomaly_prior_training_only', 'training_cutoff': '2019-12-17',
                   'schema': {}, 'horizons': [7], 'aggregates': [], 'derivatives': 'UNAVAILABLE', 'historical_independence': 'NONE'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); key = digest(payload)
            runtime.atomic(root/'requests'/f'{key}.json', {'hash': key, 'payload': payload})
            runtime.atomic(root/'inflight'/f'{key}.json', {'reserved_call': 1})
            def forbidden(*args): raise AssertionError('uncertain_retry')
            broker.once(root, forbidden)
            receipt = json.loads((root/'responses'/f'{key}.json').read_text())
            self.assertTrue(receipt['usage']['uncertain']); self.assertFalse(receipt['usage']['billing_known'])

    def test_handoff_prior_origin_immutable_and_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); db = runtime.connect(root); runtime.initialize(db, {'test': 1})
            hid = runtime.register(db, self.rule, 0, 'deterministic')
            evidence = {'rule': self.rule, 'training_cutoff': '2019-12-17', 'neighbor_stable': False}
            export(db, root, 0, hid, evidence); export(db, root, 0, hid, evidence)
            self.assertEqual(len(ingest(root/'handoff', '2020-01-01')), 1)
            self.assertEqual(ingest(root/'handoff', '2019-01-01'), [])
            with self.assertRaises(ValueError): ingest(root/'handoff', '2026-09-27')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM handoffs').fetchone()[0], 1)
            path = next((root/'handoff').glob('*.json')); row = json.loads(path.read_text()); row['orders_allowed'] = True; path.write_text(json.dumps(row))
            with self.assertRaises(ValueError): ingest(root/'handoff', '2020-01-01')
            db.close()

    def test_systemd_independence_no_production_no_sealed_mount(self):
        value = units(Path('/opt/lab-test'))
        worker = value['trendatlas-anomaly-lab.service'].replace('\\', '/'); broker_unit = value['trendatlas-anomaly-broker.service'].replace('\\', '/')
        self.assertIn('PrivateNetwork=true', worker); self.assertIn('User=trendatlas-anomaly', worker)
        self.assertNotIn('LoadCredential=', worker); self.assertIn('LoadCredential=deepseek-key:', broker_unit)
        self.assertIn('/var/lib/trendatlas-phase2', worker); self.assertIn('/var/lib/trendatlas-research-v2-inputs', broker_unit)
        self.assertNotIn('ExecStart=/opt/trendatlas-production', worker)

    def test_lightweight_idle_dispatch_and_read_only_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.assertTrue(ready(root))
            db = runtime.connect(root); runtime.initialize(db, {'test': 1})
            for k in range(14): db.execute('INSERT INTO origins VALUES(?,?)', (k, 'test'))
            db.commit(); self.assertFalse(ready(root)); db.close()
            result = audit(root); self.assertEqual(result['hash_chain'], 'PASS'); self.assertEqual(result['counts']['origins'], 14)
            self.assertFalse(ready(mailbox=root/'mailbox'))


if __name__ == '__main__': unittest.main()
