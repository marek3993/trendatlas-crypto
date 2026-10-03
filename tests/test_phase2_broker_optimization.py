import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from research.phase2_continuous import broker, compact, runtime
from research.phase2_continuous.engine import digest


class BrokerOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.genes = {'family': 'J', 'trend_days': 120, 'vol_days': 20,
                      'vol_target': 0.10, 'exit_confirm_days': 1}
        self.payload = {'cycle_id': 'cycle1', 'generation': 1, 'family': 'J',
                        'parents': [{'id': digest(self.genes), 'genes': self.genes, 'metrics': {},
                                     'folds': [], 'reasons': []}],
                        'schema': runtime.SPACE['J'], 'scope': compact.POLICY['scope']}

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self, payload):
        key = digest(payload)
        runtime.atomic(self.root / 'requests' / (key + '.json'), {'hash': key, 'payload': payload})
        return key

    def response(self, key):
        return json.loads((self.root / 'responses' / (key + '.json')).read_text())

    def test_large_historical_ledger_never_enters_wire_and_cache_crosses_cycles(self):
        huge = dict(self.payload, seen=['a' * 64] * 20000)
        self.assertEqual(broker.wire_body(huge), broker.wire_body(self.payload))
        self.assertLess(len(json.dumps(broker.wire_body(huge)).encode()), compact.POLICY['input_token_ceiling'])
        one = self.enqueue(huge)
        calls = []
        def transport(payload, _key):
            self.assertNotIn('seen', payload)
            calls.append(payload)
            return '{"candidates":[]}', {'total_tokens': 200, 'usd_upper_estimate': .0001}, 'test'
        with patch.object(broker, 'api_key', return_value='test'):
            broker.broker_once(self.root, transport)
            two = self.enqueue(dict(huge, cycle_id='cycle2'))
            broker.broker_once(self.root, transport)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.response(two)['usage']['api_call'], 0)
        self.assertEqual(self.response(two)['cache_source'], one)

    def test_only_explicit_rate_limit_retries_and_attempts_are_audited(self):
        key = self.enqueue(self.payload)
        attempts = []
        def transport(payload, secret):
            attempts.append(1)
            if len(attempts) == 1:
                raise urllib.error.HTTPError('test', 429, 'rate limited', {}, None)
            return '{"candidates":[]}', {'total_tokens': 100, 'usd_upper_estimate': .0001}, 'test'
        with patch.object(broker, 'api_key', return_value='test'), patch.object(broker.time, 'sleep'):
            broker.broker_once(self.root, transport)
        self.assertEqual(len(attempts), 2)
        result = self.response(key)
        self.assertEqual(result['usage']['api_call'], 1)
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual(result['attempts'][0]['billed_tokens'], 0)
        broker.broker_once(self.root, transport)
        self.assertEqual(len(attempts), 2)

    def test_timeout_is_unknown_billing_and_never_retried(self):
        key = self.enqueue(self.payload)
        calls = []
        def transport(*args):
            calls.append(1)
            raise TimeoutError('uncertain remote completion')
        with patch.object(broker, 'api_key', return_value='test'):
            broker.broker_once(self.root, transport)
            broker.broker_once(self.root, transport)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.response(key)['usage']['total_tokens'])
        self.assertFalse(self.response(key)['usage']['billing_known'])

    def test_crash_reservation_forbids_duplicate_transport(self):
        key = self.enqueue(self.payload)
        runtime.atomic(self.root / 'inflight' / (key + '.json'), {'reserved_call': 1})
        with patch.object(broker, 'api_key', return_value='test'):
            broker.broker_once(self.root, lambda *args: self.fail('must not call network'))
        self.assertEqual(self.response(key)['error'], 'uncertain_prior_call_no_retry')

    def test_input_ceiling_and_raw_provider_usage(self):
        p = dict(self.payload)
        p['parents'] = [dict(self.payload['parents'][0], reasons=['x' * 10000])]
        key = self.enqueue(p)
        with patch.object(broker, 'api_key', return_value='test'):
            broker.broker_once(self.root, lambda *args: self.fail('oversized input'))
        self.assertEqual(self.response(key)['error'], 'input_token_ceiling')
        raw = {'prompt_tokens': 100, 'prompt_cache_hit_tokens': 60, 'completion_tokens': 20,
               'total_tokens': 120, 'completion_tokens_details': {'reasoning_tokens': 3}}
        bill = broker.billing(raw)
        self.assertEqual(bill['input_cache_miss_tokens'], 40)
        self.assertEqual(bill['provider_usage'], raw)
        self.assertTrue(bill['billing_known'])

    def test_resume_keeps_legacy_request_and_partial_generation_budget(self):
        db = runtime.connect(self.root)
        try:
            cycle = runtime.ensure_cycle(db, 'code', 'contract', 'input')
            parent = self.payload['parents'][0]
            runtime.add_candidate(db, cycle, 0, self.genes, None, 'initial_predeclared_space', 1)
            legacy = dict(self.payload, cycle_id=cycle, seen=['legacy' * 10] * 1000)
            key = digest(legacy)
            mailbox = self.root / 'mailbox'
            runtime.atomic(mailbox / 'requests' / (key + '.json'), {'hash': key, 'payload': legacy})
            children = [{'parent': parent['id'], 'genes': dict(self.genes, trend_days=v),
                         'hypothesis': 'Reduce timing fragility.'} for v in [100, 110, 130, 140]]
            runtime.atomic(mailbox / 'responses' / (key + '.json'),
                           {'hash': key, 'state': 'COMPLETE', 'content': json.dumps({'candidates': children})})
            with db:
                db.execute("INSERT INTO family_stage VALUES(?,?,0,'AWAITING_BROKER',?)", (cycle, 'J', key))
            runtime.add_candidate(db, cycle, 1, children[0]['genes'], parent['id'], 'deepseek:prior crash', 2)
            with patch.object(runtime, 'parents_for_family', return_value=[parent]):
                self.assertTrue(runtime.advance_family(db, self.root, cycle, 'J'))
                self.assertFalse(runtime.advance_family(db, self.root, cycle, 'J'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates WHERE generation=1').fetchone()[0], 4)
            self.assertEqual(len(list((mailbox / 'requests').glob('*.json'))), 1)
            runtime.verify_chain(db)
        finally:
            db.close()

    def test_completed_seed_stage_does_not_repeat_exhaustion_events(self):
        db = runtime.connect(self.root)
        try:
            cycle = runtime.ensure_cycle(db, 'code', 'contract', 'input')
            runtime.seed_population(db, cycle)
            before = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            runtime.seed_population(db, cycle)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], before)
        finally:
            db.close()

    def test_random_sampling_failure_cannot_claim_space_exhausted(self):
        from unittest.mock import Mock
        tiny = {'J': {'trend_days': [100, 110], 'vol_days': [20],
                      'vol_target': [0.10], 'exit_confirm_days': [1]}}
        db = runtime.connect(self.root)
        try:
            cycle = runtime.ensure_cycle(db, 'code', 'contract', 'input')
            runtime.add_candidate(db, cycle, 1, dict(self.genes, trend_days=100), None, 'prior', 1)
            rng = Mock(); rng.choice.side_effect = lambda values: values[0]
            with patch.object(runtime, 'SPACE', tiny), patch.object(runtime.random, 'Random', return_value=rng):
                runtime.seed_population(db, cycle)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0], 2)
            self.assertIn('110', db.execute('SELECT genes FROM candidates WHERE generation=0').fetchone()[0])
            with db:
                db.execute("UPDATE cycles SET status='SEALED_DEVELOPMENT'")
            successor = runtime.ensure_cycle(db, 'code', 'contract', 'input')
            with patch.object(runtime, 'SPACE', tiny), patch.object(runtime.random, 'Random') as factory:
                runtime.seed_population(db, successor)
                factory.return_value.choice.assert_not_called()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates WHERE cycle_id=?', (successor,)).fetchone()[0], 0)
        finally:
            db.close()

    def test_exhausted_neighborhood_offers_bounded_globally_novel_mutations(self):
        db = runtime.connect(self.root)
        try:
            cycle = runtime.ensure_cycle(db, 'code', 'contract', 'input')
            runtime.add_candidate(db, cycle, 0, self.genes, None, 'initial', 1)
            parent = dict(self.payload['parents'][0], eligible=False)
            with (patch.object(compact, 'mutate', return_value=(None, 'local_neighborhood_exhausted')),
                  patch.object(runtime, 'candidate_summary', return_value=parent)):
                payload = compact.proposal(db, cycle, 'J', [parent], runtime.SPACE['J'])
            options = payload['unseen_options']
            self.assertEqual(len(options), compact.POLICY['unseen_options_max'])
            hashes = {digest(o['genes']) for o in options}
            self.assertEqual(len(hashes), len(options))
            self.assertNotIn(digest(self.genes), hashes)
            self.assertLessEqual(len(json.dumps(broker.wire_body(payload)).encode()), compact.POLICY['input_token_ceiling'])
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
