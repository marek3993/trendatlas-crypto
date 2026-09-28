"""Retention must keep newest checkpoint and independent daily/weekly history."""
import datetime as dt
from pathlib import Path
import unittest
from maintenance import retained


class RetentionTests(unittest.TestCase):
    def test_seven_daily_four_weekly_and_newest(self):
        today = dt.datetime(2026, 9, 28)
        paths = [Path((today - dt.timedelta(days=i)).strftime('%Y%m%dT120000Z')) for i in range(45)]
        keep = retained(paths)
        self.assertTrue(set(paths[:7]).issubset(keep))
        self.assertIn(paths[0], keep)
        self.assertEqual(len({dt.datetime.strptime(p.name[:8], '%Y%m%d').date().isocalendar()[:2] for p in keep}), 4)
        self.assertNotIn(paths[-1], keep)

    def test_same_day_duplicate_keeps_latest(self):
        older, newest = Path('20260928T120000Z'), Path('20260928T130000Z')
        self.assertEqual(retained([older, newest]), {newest})


if __name__ == '__main__': unittest.main()
