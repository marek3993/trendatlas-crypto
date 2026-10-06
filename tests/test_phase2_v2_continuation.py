import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from research.phase2_v2 import runtime as r, continuation as c


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = r.connect(self.root)
        r.initialize(self.db, {'engine': 'frozen', 'inputs': 'frozen', 'contract': 'frozen'})
        c.initialize(self.db)
        with self.db:
            self.db.execute("INSERT INTO test_books VALUES(0,?,?)", (json.dumps({'checkpoint': {'held': 'LUNA', 'cash': -25}}), 'original'))
            for origin in range(1, 14):
                self.db.execute('INSERT INTO selections VALUES(?,?,?,?,?)', (origin, 'frozen-candidate', '"CASH"', '{}', 'before-test'))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_terminal_price_failure_preserves_checkpoint_and_never_retries(self):
        before = list(self.db.execute('SELECT * FROM test_books'))
        selections = list(self.db.execute('SELECT * FROM selections'))
        with patch.object(r, 'test_selected', side_effect=ValueError('missing_held_asset_price:2022-05-13:LUNAUSDT@original')) as run:
            c.test_selected(self.db, 1, None)
            c.test_selected(self.db, 1, None)
            c.test_selected(self.db, 2, None)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(before, list(self.db.execute('SELECT * FROM test_books')))
        self.assertEqual(selections, list(self.db.execute('SELECT * FROM selections')))
        failures = [json.loads(x[0]) for x in self.db.execute('SELECT receipt FROM terminal_test_failures ORDER BY origin')]
        self.assertEqual(failures[0]['state'], 'UNDEFINED_INVALID')
        self.assertEqual(failures[1]['state'], 'NOT_EVALUABLE_CONTINUITY_LOST')
        self.assertIsNone(failures[1]['full_horizon_cagr'])
        self.assertFalse(failures[1]['liquidation_or_cash_reset'])
        self.assertEqual(c.processed(self.db), 3)
        self.assertEqual(json.loads(self.db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])['engine'], 'frozen')
        with self.assertRaises(Exception):
            self.db.execute("DELETE FROM terminal_test_failures")

    def test_unrecognized_programming_error_is_not_hidden(self):
        with patch.object(r, 'test_selected', side_effect=ValueError('programming_error')):
            with self.assertRaisesRegex(ValueError, 'programming_error'):
                c.test_selected(self.db, 1, None)
        self.assertEqual(c.processed(self.db), 1)

    def test_next_origin_uses_unchanged_past_only_training(self):
        with patch.object(r, 'test_selected', side_effect=ValueError('missing_held_asset_price:2022-05-13:LUNA')):
            c.test_selected(self.db, 1, None)
        origin = c.processed(self.db)
        r.seed(self.db, 0)  # Available prior population for unchanged inheritance.
        r.seed(self.db, origin)
        tasks = r.pending(self.db, origin, 0, {'engine': 'frozen'})
        self.assertTrue(tasks)
        self.assertTrue(all(t[2] == 2 for t in tasks))
        self.assertLess(r.training_folds(origin)[-1][1], r.C['walk_forward']['validation_folds'][origin][0])

    def test_completion_counts_invalid_separately_and_stops_without_new_cycle(self):
        cycle = self.db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0]
        with patch.object(r, 'test_selected', side_effect=ValueError('missing_entry_price')):
            for origin in range(1, 14):
                c.test_selected(self.db, origin, None)
        s = c.status(self.db)
        self.assertFalse(s['active_evolution'])
        self.assertEqual(s['processed_origins'], 14)
        self.assertEqual(s['test_folds_completed'], 1)
        self.assertEqual(s['invalid_test_folds'], 13)
        self.assertFalse(c.executable(self.root))
        self.assertEqual(cycle, self.db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0])


if __name__ == '__main__':
    unittest.main()
