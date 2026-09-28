"""Regression coverage for the predeclared cross-architecture comparison."""
import copy
import unittest
import replay


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.left = dict(spec=dict(candidate_id='fixed', search_seed=1701, rtol=1e-10,
                                  atol=1e-10, request=dict(period=dict(scope='inner_validation'))),
                         payload=dict(signals=[1.0], fills=[dict(price=100.)], daily=[None, 100.]),
                         environment=dict(architecture='aarch64'))
        self.right = copy.deepcopy(self.left)
        self.right['environment']['architecture'] = 'x86_64'

    def test_exact_replay(self):
        self.assertTrue(replay.compare(self.left, self.right)['exact_numeric_equality'])

    def test_existing_numeric_tolerance(self):
        self.right['payload']['fills'][0]['price'] += 1e-9
        self.assertTrue(replay.compare(self.left, self.right)['pass_replay'])

    def test_signal_decisions_require_exact_equality(self):
        self.right['payload']['signals'][0] += 1e-12
        with self.assertRaises(RuntimeError): replay.compare(self.left, self.right)

    def test_nonfinite_mask_must_match(self):
        self.right['payload']['daily'][0] = 0.
        with self.assertRaises(RuntimeError): replay.compare(self.left, self.right)

    def test_price_outside_tolerance_rejected(self):
        self.right['payload']['fills'][0]['price'] += 1e-5
        with self.assertRaises(RuntimeError): replay.compare(self.left, self.right)


if __name__ == '__main__': unittest.main()
