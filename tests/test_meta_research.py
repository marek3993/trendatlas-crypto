import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import meta_research as meta, meta_resources as resources, research_spaces as spaces
from research.continuous_research import planner, runtime, schema, ledger, broker
from research.continuous_research.common import canonical, digest, atomic, period, utc
from tests.test_continuous_research import setup, gene, evaluator, discovery, TARIFF
from tests.test_research_spaces import tiny, now


HEALTH = dict(cpu_busy_pct=10., load_per_cpu=.1, cpu_pressure=2., memory_available=4*2**30,
              memory_pressure=0., io_pressure=0., disk_free=10*2**30, ledger_bytes=2**20)


def installed():
    stack = ExitStack(); stack.enter_context(meta.installed())
    stack.enter_context(patch.object(resources, 'admit', lambda root: HEALTH))
    return stack


def market_fixture():
    from research.phase2_v2.market import synthetic_market
    from research.anomaly_lab.rules import prepare
    from research.discovery_evolution.runtime import restricted_market
    m = synthetic_market(); f = prepare(m); return restricted_market(m, f), f


def step(db, root, mail, market=None, evaluate=evaluator):
    return meta.tick(db, root, mail, lambda: market or (None, None), evaluate, now(), None if market else discovery)


class MetaPolicyTests(unittest.TestCase):
    def test_beyond_128_and_paid_cap_keeps_same_scientific_history(self):
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); day, _ = period()
            with db:
                db.executemany('INSERT INTO scientific_attempts(candidate,day,utc) VALUES(?,?,?)',
                               ((f'prior-reservation-{i}', day, utc()) for i in range(128)))
            api = broker.connect(mail)
            for i in range(24): self.assertIsNotNone(broker.reserve(api, str(i), 0, TARIFF, 5000)[0])
            before = api.execute('SELECT * FROM reservations ORDER BY id').fetchall()
            self.assertEqual(step(db, root, mail), 'PROGRESSED')
            self.assertEqual(db.execute('SELECT MAX(alpha_index) FROM statistics').fetchone()[0], 1444+129)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests').fetchone()[0], 6)
            self.assertEqual(api.execute('SELECT * FROM reservations ORDER BY id').fetchall(), before)
            self.assertEqual(broker.budget(api)['attempts_remaining_today'], 0)
            self.assertEqual(meta.policy()['candidate_starts_per_day'], None)
            api.close(); db.close()

    def test_entire_current_K_envelope_exhausted_then_real_J_backtest(self):
        # Full production K refinement domain, seeded as exhausted historical fixture.
        # These registry fixtures are NOT claimed to be 824,915 historical backtests.
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); m = market_fixture()
            self.assertEqual(step(db, root, mail, m, runtime.default_evaluator), 'PROGRESSED')
            grid = meta.full_grammar('K'); self.assertEqual(meta.cardinality(grid), 824915)
            with db:
                db.executemany('INSERT OR IGNORE INTO genes VALUES(?,?)',
                               ((digest(meta.at(grid, i)), 'exhausted-envelope-fixture') for i in range(meta.cardinality(grid))))
            self.assertEqual(meta.remaining(db), 0)
            # An outstanding paid request remains WAIT; no manual completion is needed.
            api = broker.connect(mail)
            for i in range(24): broker.reserve(api, str(i), 0, TARIFF, 5000)
            count = api.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]
            self.assertEqual(step(db, root, mail, m, runtime.default_evaluator), 'PROGRESSED')
            sid, space, sha = spaces.active(db)
            self.assertEqual((sid, space['category']), (2, 'J'))
            self.assertEqual(space['origin'], 'LOCAL_META_POLICY')
            candidate = db.execute('SELECT id,body FROM candidates WHERE batch=2 ORDER BY utc LIMIT 1').fetchone()
            self.assertEqual(json.loads(candidate[1])['genes']['family'], 'J')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests WHERE candidate=?', (candidate[0],)).fetchone()[0], 5)
            for body, in db.execute('SELECT body FROM backtests WHERE candidate=?', (candidate[0],)):
                r = json.loads(body); self.assertTrue(r['valid']); self.assertTrue(runtime.book(root, r)['audit']['pnl_reconciled'])
            self.assertEqual(api.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], count)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 2)
            self.assertEqual(space['lifetime_alpha_before'], 1445)
            print(canonical({'proof': 'full_K_envelope_fixture_then_real_J', 'K_registered': 824915,
                             'candidate': candidate[0], 'space_hash': sha, 'new_candidate_backtests': 5,
                             'unique_completed': 2, 'API_attempts_retained': count, 'all_books_valid': True,
                             'frozen_utc': space['frozen_utc']}))
            ledger.verify(db); api.close(); db.close()

    def test_resource_pressure_and_unknown_metrics_pause_without_reservations(self):
        cases = [('cpu_busy_pct', 90), ('load_per_cpu', 2), ('cpu_pressure', 90), ('memory_available', 1),
                 ('memory_pressure', 3), ('io_pressure', 20), ('disk_free', 0), ('ledger_bytes', 4*2**30)]
        with tempfile.TemporaryDirectory() as root:
            for key, value in cases:
                sample = {**HEALTH, key: value}
                self.assertTrue(resources.decision(sample).startswith('WAIT_RESOURCE_'))
                with self.assertRaises(resources.ResourcePause): resources.admit(root, lambda _: sample)
            self.assertIsNone(resources.decision(HEALTH))
            with self.assertRaisesRegex(resources.ResourcePause, 'OBSERVATION'):
                resources.admit(root, lambda _: {})
        with tempfile.TemporaryDirectory() as root, meta.installed(), patch.object(resources, 'admit', side_effect=resources.ResourcePause('WAIT_RESOURCE_CPU')):
            db, mail = setup(root); tiny(db)
            self.assertEqual(step(db, root, mail), 'WAIT_RESOURCE_CPU')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0], 0); db.close()

    def test_mid_candidate_resource_pause_resumes_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); calls = []
            def admit(root):
                calls.append(1)
                if len(calls) == 3: raise resources.ResourcePause('WAIT_RESOURCE_MEMORY')
                return HEALTH
            with patch.object(resources, 'admit', admit):
                self.assertEqual(step(db, root, mail), 'WAIT_RESOURCE_MEMORY')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests').fetchone()[0], 1)
            reserved = db.execute('SELECT * FROM scientific_attempts').fetchall()
            completed = db.execute('SELECT * FROM backtests').fetchall(); db.close()
            db = ledger.connect(root); spaces.initialize_spaces(db)
            self.assertEqual(step(db, root, mail), 'PROGRESSED')
            self.assertEqual(db.execute('SELECT * FROM scientific_attempts').fetchall(), reserved)
            self.assertEqual(db.execute('SELECT * FROM backtests WHERE key=?', (completed[0][0],)).fetchall(), completed)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 6); ledger.verify(db); db.close()

    def test_blend_is_one_real_book_with_independent_signal_memory_and_causal_prefix(self):
        import numpy as np
        with installed():
            m, f = market_fixture()
            left = meta.at(meta.full_grammar('J'), 10); right = gene(2)
            g = meta.genes({'family': 'BLEND', 'left': left, 'right': right, 'left_weight': .25})
            state = {}; a = {}; b = {}
            for i in range(400, 440):
                av = meta.OLD_TARGETS(m, left, i, a); bv = meta.OLD_TARGETS(m, right, i, b)
                a['previous'] = av.copy(); b['previous'] = bv.copy()
                np.testing.assert_allclose(meta.targets(m, g, i, state), .25*av+.75*bv)
            interval = ['2020-01-01', '2021-12-17']
            result = runtime.default_evaluator(m, f, g, interval, 'nominal')
            self.assertTrue(result['audit']['pnl_reconciled']); self.assertTrue(result['audit']['continuous_book'])
            self.assertGreater(result['metrics']['costs_usd'], 0)
            # Prefix evaluation is unchanged when later observations exist.
            prefix = runtime.default_evaluator(m, f, g, ['2020-01-01', '2020-12-17'], 'nominal')
            self.assertEqual(result['equity'][:len(prefix['equity'])], prefix['equity'])
            # Checkpoint serialization preserves both component histories.
            checkpoint = json.loads(canonical(prefix['checkpoint']))
            continuation = meta.engine.evaluate(m, g, [['2020-12-18', '2021-12-17']], initial_state=checkpoint)
            self.assertAlmostEqual(continuation['equity'][-1]['equity'], result['equity'][-1]['equity'], places=10)

    def test_blend_canonical_dedup_and_rejection_of_unsupported_execution(self):
        a = meta.at(meta.full_grammar('J'), 0); b = gene()
        x = meta.genes({'family': 'BLEND', 'left': a, 'right': b, 'left_weight': .25})
        y = meta.genes({'family': 'BLEND', 'left': b, 'right': a, 'left_weight': .75})
        self.assertEqual(digest(x), digest(y))
        for bad in ({**x, 'right': a}, {**x, 'left_weight': 0}, {**x, 'left': x},
                    {**x, 'left': meta.at(meta.full_grammar('N'), 0)}):
            with self.assertRaises(ValueError): meta.genes(bad)

    def test_AI_wire_and_admission_in_frozen_blend_space(self):
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); step(db, root, mail)
            views = spaces.evidence(db)
            grammar = meta.neighborhood('J+K', views, 1)
            meta.freeze_space(db, 'J+K', grammar, views)
            payload = {'scope': 'prior_train_validation_only', 'cutoff': schema.load()['feedback_cutoff'],
                       'parents': views, 'coverage': {'completed': 1}, 'meta_space': {'id': 2, 'hash': spaces.active(db)[2], 'grammar': grammar}}
            payload['parents'][0]['diagnostic_only'] = {'canary': 'SEALED_CANARY'}
            body = planner.wire_body(payload)
            self.assertNotIn('SEALED_CANARY', canonical(body)); self.assertLessEqual(len(canonical(body).encode())+256, 6500)
            g = meta.novel(db, grammar)[0]
            p = {'parent': views[0]['id'], 'rule': views[0]['rule'], 'genes': g,
                 'mechanism': 'Fixture AI combines supported signals within the frozen grammar.', 'falsification': 'Validation drawdown refutes this configuration.'}
            accepted = planner.register(db, p, 'AI_AUTHORED', 'fixture-response', 0)
            self.assertIsNotNone(accepted)
            self.assertIsNone(planner.register(db, {**p, 'mechanism': 'Rewording never changes the global identity.'}, 'AI_AUTHORED', 'fixture-duplicate', 0))
            self.assertEqual(step(db, root, mail), 'PROGRESSED')
            self.assertTrue(db.execute('SELECT 1 FROM feedback WHERE candidate=?', (digest(g),)).fetchone()); db.close()

    def test_bounded_scan_checkpoint_and_honest_terminal_state(self):
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); step(db, root, mail); meta.initialize_meta(db)
            c = copy.deepcopy(meta.policy()); c['categories'] = ['J']; c['scan_positions_per_activation'] = 2
            grammar = meta.full_grammar('J'); count = meta.cardinality(grammar)
            with db:
                db.executemany('INSERT OR IGNORE INTO genes VALUES(?,?)', ((digest(meta.at(grammar, i)), 'fixture') for i in range(count)))
            with patch.object(meta, 'policy', lambda: c):
                self.assertEqual(meta.advance(db), 'WAIT_META_SCAN')
                self.assertEqual(db.execute('SELECT MAX(ordinal) FROM meta_scans').fetchone()[0], 2)
                self.assertEqual(meta.advance(db), 'WAIT_META_SCAN')
                self.assertEqual(db.execute('SELECT MAX(ordinal) FROM meta_scans').fetchone()[0], 4)
                with db: db.execute('INSERT INTO meta_scans(category,ordinal,body) VALUES(?,?,?)', ('J', count, '{}'))
                self.assertEqual(meta.advance(db), 'IDLE_META_GRAMMAR_EXHAUSTED')
            self.assertEqual(spaces.active(db)[0], 1); db.close()

    def test_late_old_AI_request_does_not_block_space_and_wire_is_preserved(self):
        with tempfile.TemporaryDirectory() as root, installed():
            db, mail = setup(root); tiny(db); step(db, root, mail)
            row = db.execute('SELECT id,body FROM requests').fetchone(); payload = json.loads(row[1])['payload']
            before = digest(spaces.protocol.wire_body(payload))
            self.assertTrue(db.execute('SELECT 1 FROM requests WHERE id NOT IN (SELECT id FROM ingested)').fetchone())
            self.assertEqual(step(db, root, mail), 'PROGRESSED')
            self.assertEqual(spaces.active(db)[1]['category'], 'J')
            self.assertEqual(digest(planner.wire_body(payload)), before); db.close()

    def test_automatic_category_rotation_reaches_real_blend_backtest(self):
        small = {fam: {k: [v[0]] for k, v in params.items()} for fam, params in meta.domains().items()}
        small['K']['rebalance_days'] = [3, 5]
        with tempfile.TemporaryDirectory() as root, installed(), patch.object(meta, 'domains', lambda: small):
            db, mail = setup(root); tiny(db); m, f = market_fixture()
            actual = []
            def evaluate(m, f, g, interval, stress):
                if isinstance(g, dict) and g['family'] == 'BLEND':
                    actual.append(digest(g)); return runtime.default_evaluator(m, f, g, interval, stress)
                return evaluator(m, f, g, interval, stress)
            for _ in range(20):
                step(db, root, mail, (m, f), evaluate)
                if actual: break
            self.assertEqual(len(actual), 5)
            sid, space, sha = spaces.active(db); self.assertEqual(space['category'], 'J+K')
            self.assertTrue(db.execute('SELECT 1 FROM feedback WHERE candidate=?', (actual[0],)).fetchone())
            for body, in db.execute('SELECT body FROM backtests WHERE candidate=?', (actual[0],)):
                self.assertTrue(json.loads(body)['valid'])
            print(canonical({'proof': 'automatic_supported_category_rotation_to_real_blend', 'space': sid,
                             'category': space['category'], 'candidate': actual[0], 'real_books': len(actual),
                             'space_hash': sha, 'frozen_utc': space['frozen_utc']}))
            db.close()

    def test_deployment_resource_priority_and_all_old_boundaries(self):
        from scripts.deploy_meta_research import resource_unit, unit_revision
        from research.continuous_research.deploy import units, WORKER, BROKER
        old = units('/old')[WORKER+'.service'].replace('research/continuous_research/entry.py', 'research/research_spaces.py')
        new = resource_unit(unit_revision(old, '/old', '/new'))
        for required in ('Nice=19', 'CPUWeight=1', 'IOWeight=1', 'IOSchedulingClass=idle', 'MemoryHigh=2147483648',
                         'MemoryMax=3221225472', 'CPUQuota=60%', 'PrivateNetwork=true', 'ProtectSystem=strict'):
            self.assertIn(required, new)
        self.assertNotIn('LoadCredential=', new)
        self.assertEqual(next(x for x in old.splitlines() if x.startswith('InaccessiblePaths=')),
                         next(x for x in new.splitlines() if x.startswith('InaccessiblePaths=')))
        broker_unit = units('/old')[BROKER+'.service'].replace('research/continuous_research/entry.py', 'research/research_spaces.py')
        self.assertEqual(unit_revision(broker_unit, '/old', '/new').replace('/new', '/old').replace('research/meta_research.py', 'research/research_spaces.py'), broker_unit)


if __name__ == '__main__': unittest.main()
