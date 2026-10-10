import copy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from research import research_spaces as spaces
from research.continuous_research import ledger, planner, runtime, broker, schema
from research.continuous_research.common import canonical, digest, instant, utc, atomic
from tests.test_continuous_research import setup, gene, evaluator, discovery, TARIFF


def tiny(db):
    spaces.initialize_spaces(db, {k: [v] for k, v in gene(1).items() if k != 'family'})


def no_proposals(body):
    return {'id': 'synthetic-provider-fixture', 'model': 'deepseek-flash',
            'usage': {'prompt_tokens': 1000, 'completion_tokens': 50},
            'choices': [{'finish_reason': 'stop', 'message': {'content': canonical({
                'evaluation': 'No additional proposal in this fixture.', 'proposals': []})}}]}


def now():
    return (instant(utc())+timedelta(seconds=60)).isoformat()


def activation(db, root, mail, get_market=lambda: (None, None), evaluate=evaluator, discover=discovery):
    broker.once(mail, no_proposals, lambda: TARIFF)
    return runtime.tick(db, root, mail, get_market, evaluate, now(), discovery_fn=discover)


class ResearchSpaceTests(unittest.TestCase):
    def test_exhaustion_successor_and_real_engine_backtest_without_operator(self):
        from research.phase2_v2.market import synthetic_market
        from research.anomaly_lab.rules import prepare
        from research.discovery_evolution.runtime import restricted_market
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db)
            market = synthetic_market(); features = prepare(market)
            market = restricted_market(market, features)
            get_market = lambda: (market, features)
            counts = []
            for _ in range(3):
                self.assertEqual(activation(db, root, mail, get_market, runtime.default_evaluator, None), 'PROGRESSED')
                counts.append(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0])
            self.assertEqual(counts, [1, 2, 3])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM research_spaces').fetchone()[0], 2)
            sid, successor, sha = spaces.active(db)
            self.assertEqual(successor['lifetime_alpha_before'], 1445)
            self.assertEqual(successor['eligible_feedback_count'], 1)
            self.assertTrue(successor['parent_space_hash'])
            self.assertEqual(successor['origin'], 'LOCAL_RESULT_REFINEMENT')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests').fetchone()[0], 16)
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT candidate) FROM feedback').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT MAX(alpha_index) FROM statistics').fetchone()[0], 1447)
            events = [json.loads(r[0]) for r in db.execute('SELECT body FROM events ORDER BY id')]
            freeze = next(i for i, e in enumerate(events) if e['kind'] == 'research_space_frozen' and e['space'] == 2)
            new_candidate = db.execute('SELECT id FROM candidates WHERE batch=2 ORDER BY utc LIMIT 1').fetchone()[0]
            reserved = next(i for i, e in enumerate(events) if e['kind'] == 'backtest_reserved' and e['candidate'] == new_candidate)
            self.assertLess(freeze, reserved)
            self.assertEqual(db.execute('SELECT space,space_hash FROM space_batches WHERE batch=2').fetchone(), (sid, sha))
            for body, in db.execute('SELECT body FROM backtests'):
                receipt = json.loads(body); self.assertTrue(receipt['valid'])
                self.assertTrue(runtime.book(root, receipt)['audit']['pnl_reconciled'])
            for body, in db.execute('SELECT body FROM feedback'):
                self.assertFalse(json.loads(body)['confirmed_trading_candidate'])
            request = json.loads(db.execute('SELECT body FROM requests WHERE trigger_batch=1').fetchone()[0])
            self.assertEqual(request['payload']['research_space']['hash'], sha)
            self.assertLessEqual(len(canonical(planner.wire_body(request['payload'])).encode())+256, 6500)
            ledger.verify(db); db.close()

    def test_crash_after_successor_freeze_resumes_same_space_gene_and_alpha(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db); activation(db, root, mail)
            def crash(*args):
                raise KeyboardInterrupt('power loss inside new candidate engine')
            with self.assertRaises(KeyboardInterrupt):
                activation(db, root, mail, evaluate=crash)
            before = spaces.active(db)
            attempt = db.execute('SELECT id,key FROM attempts ORDER BY id DESC LIMIT 1').fetchone()
            count = db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0]
            api = broker.connect(mail); reservations = api.execute('SELECT COUNT(*),SUM(nanousd) FROM reservations').fetchone(); api.close()
            db.close(); db = ledger.connect(root); spaces.initialize_spaces(db)
            self.assertEqual(runtime.tick(db, root, mail, lambda: (None, None), evaluator, now(), discovery), 'PROGRESSED')
            self.assertEqual(spaces.active(db), before)
            self.assertEqual(db.execute('SELECT id FROM attempts WHERE key=?', (attempt[1],)).fetchone()[0], attempt[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0], count)
            api = broker.connect(mail); self.assertEqual(api.execute('SELECT COUNT(*),SUM(nanousd) FROM reservations').fetchone(), reservations); api.close()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE research_spaces SET body='{}'")
            ledger.verify(db); db.close()

    def test_wait_for_pending_response_and_no_transition_with_open_work(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db)
            runtime.tick(db, root, mail, lambda: (None, None), evaluator, now(), discovery)
            self.assertEqual(spaces.remaining(db), 0)
            self.assertEqual(spaces.advance(db), 'WAIT_PENDING_SPACE_REQUEST')
            self.assertEqual(spaces.active(db)[0], 1)
            activation(db, root, mail)
            self.assertEqual(spaces.active(db)[0], 2)
            self.assertIsNone(spaces.advance(db))
            self.assertEqual(spaces.active(db)[0], 2); db.close()

    def test_global_dedup_and_frozen_grid_admission(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db)
            activation(db, root, mail); activation(db, root, mail)
            p = spaces.active(db)[1]['parent_evidence']
            proposal = {'parent': p['id'], 'genes': p['genes'], 'rule': p['rule'],
                        'mechanism': 'Different words and space do not make a new gene.', 'falsification': 'Validation failure invalidates the idea.'}
            self.assertIsNone(planner.register(db, proposal, 'AI_AUTHORED', 'duplicate-fixture', 0))
            proposal['genes'] = {**p['genes'], 'vol_target': .24}
            with self.assertRaisesRegex(ValueError, 'outside_frozen'):
                planner.register(db, proposal, 'AI_AUTHORED', 'invalid-fixture', 0)
            with self.assertRaises(ValueError):
                spaces.genes({**p['genes'], 'vol_target': .06501})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM genes').fetchone()[0], db.execute('SELECT COUNT(DISTINCT id) FROM genes').fetchone()[0]); db.close()

    def test_diagnostics_cannot_change_parent_selection_or_space(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db); activation(db, root, mail)
            view = spaces.evidence(db)[0]
            contaminated = copy.deepcopy(view)
            contaminated['diagnostic_only'] = {'winner': 'SEALED_TEST_CANARY'}
            contaminated['training']['metrics']['test_score'] = 'SEALED_TEST_CANARY'
            self.assertEqual(spaces.safe_view(contaminated), view)
            self.assertNotIn('SEALED_TEST_CANARY', canonical(spaces.safe_view(contaminated)))
            for phase in ('training', 'validation'):
                bad = copy.deepcopy(view); bad[phase]['interval'][1] = '2026-09-27'
                with self.assertRaises(ValueError): spaces.safe_view(bad)
                bad = copy.deepcopy(view); bad[phase]['valid'] = False
                with self.assertRaises(ValueError): spaces.safe_view(bad)
            activation(db, root, mail)
            self.assertNotIn('diagnostic_only', canonical(spaces.active(db)[1]['parent_evidence']))
            db.close()

    def test_empty_valid_frontier_is_honest_idle_no_scientific_reset(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root)
            spaces.initialize_spaces(db, {k: [v] for k, v in gene().items() if k != 'family'})
            self.assertEqual(spaces.advance(db), 'IDLE_NO_VALID_TRAIN_VALIDATION_FEEDBACK')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0], 0)
            self.assertEqual(ledger.meta(db, 'bootstrap')['inherited']['alpha_index'], 1444)
            self.assertEqual(spaces.active(db)[0], 1); db.close()

    def test_legacy_wire_bytes_and_base_contract_remain_identical(self):
        with tempfile.TemporaryDirectory() as root:
            db, mail = setup(root); planner.ensure_request(db, mail)
            payload = json.loads(db.execute('SELECT body FROM requests').fetchone()[0])['payload']
            expected = spaces.protocol.wire_body(payload)
            legacy = spaces.protocol.wire_body(payload, [digest(payload)])
            with spaces.installed(): self.assertEqual(planner.wire_body(payload), expected)
            with spaces.installed([digest(payload)]): self.assertEqual(planner.wire_body(payload), legacy)
            self.assertEqual(schema.spaces()[0]['vol_target'], [.06, .08, .1, .12, .15, .18, .2, .24]); db.close()

    def test_successor_AI_schema_admission_backtest_and_same_shared_budget(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db)
            activation(db, root, mail); activation(db, root, mail)
            request = json.loads(db.execute('SELECT body FROM requests WHERE trigger_batch=1').fetchone()[0])
            parent = request['payload']['parents'][0]
            g = spaces.unseen(db, spaces.active(db)[1]['K_schema'])[0]
            p = {'parent': parent['id'], 'genes': g, 'rule': parent['rule'],
                 'mechanism': 'Fixture provider proposes a new configuration inside the frozen refined grid.',
                 'falsification': 'Negative validation growth would refute this configuration.'}
            def send(body):
                self.assertEqual(json.loads(body['messages'][1]['content'])['K_schema'], spaces.active(db)[1]['K_schema'])
                r = no_proposals(body)
                r['choices'][0]['message']['content'] = canonical({'evaluation': 'Fixture critique of eligible prior validation.', 'proposals': [p]})
                return r
            self.assertEqual(broker.once(mail, send, lambda: TARIFF), 'COMPLETE')
            for _ in range(4):
                runtime.tick(db, root, mail, lambda: (None, None), evaluator, now(), discovery)
            feedback = json.loads(db.execute('SELECT body FROM feedback WHERE candidate=?', (digest(g),)).fetchone()[0])
            self.assertEqual(feedback['origin'], 'AI_AUTHORED'); self.assertEqual(feedback['request'], request['id'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests WHERE candidate=?', (digest(g),)).fetchone()[0], 5)
            api = broker.connect(mail); budget = broker.budget(api)
            self.assertEqual(budget['lifetime_new_attempts'], 2)
            self.assertEqual(budget['attempts_remaining_today'], 22)
            self.assertAlmostEqual(budget['reserved_usd_month'], .0075)
            api.close(); db.close()

    def test_frontier_exhaustion_never_relabels_seen_genes_as_new_space(self):
        with tempfile.TemporaryDirectory() as root, spaces.installed():
            db, mail = setup(root); tiny(db); activation(db, root, mail)
            broker.once(mail, no_proposals, lambda: TARIFF); planner.ingest(db, mail)
            domain = spaces.envelope()
            for parent in spaces.evidence(db):
                grid = {k: [v] for k, v in parent['genes'].items() if k != 'family'}
                for k in spaces.contract()['refinement']:
                    i = domain[k].index(parent['genes'][k]); grid[k] = domain[k][max(0, i-1):i+2]
                with db:
                    db.executemany('INSERT OR IGNORE INTO genes VALUES(?,?)', ((digest(g), 'exhausted-frontier-fixture') for g in spaces.configurations(grid)))
            before = db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0]
            self.assertEqual(spaces.advance(db), 'IDLE_NO_ELIGIBLE_NOVEL_FRONTIER')
            self.assertEqual(spaces.advance(db), 'IDLE_NO_ELIGIBLE_NOVEL_FRONTIER')
            self.assertEqual(spaces.active(db)[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0], before); db.close()

    def test_deployment_changes_only_isolated_research_entrypoint(self):
        from scripts.deploy_research_spaces import unit_revision
        from research.continuous_research.deploy import units, WORKER, BROKER
        for name in (WORKER, BROKER):
            old = units('/old')[name+'.service'].replace('research/continuous_research/entry.py', 'research/continuous_research_protocol.py')
            new = unit_revision(old, '/old', '/new')
            self.assertEqual(new.replace('/new', '/old').replace('research/research_spaces.py', 'research/continuous_research_protocol.py'), old)
            self.assertIn('InaccessiblePaths=', new)
            if name == WORKER:
                self.assertIn('PrivateNetwork=true', new); self.assertNotIn('LoadCredential=', new)
        with self.assertRaises(ValueError): unit_revision('unrelated production service', '/old', '/new')


if __name__ == '__main__':
    unittest.main()
