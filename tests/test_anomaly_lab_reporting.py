import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab_reporting', ROOT/'scripts/anomaly_lab_report_consumer.py')
reporting = importlib.util.module_from_spec(spec); spec.loader.exec_module(reporting)


class ReportingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT/'source_of_truth/anomaly_lab_reporting_contract.json').read_text())
        self.source = {'samples': [{'frequency': {'independent_events': 0, 'frequency_annual_rate_ci95': [0., 0.]}}],
                       'counts': {'origins': 1}, 'status': {'processed_origins': 1}, 'unknown_billing': False,
                       'usd_upper_estimate': .01}

    def test_zero_events_does_not_claim_zero_frequency_uncertainty(self):
        result = reporting.normalize(self.source, self.c)
        self.assertIsNone(result['samples'][0]['frequency']['frequency_annual_rate_ci95'])
        self.assertEqual(result['samples'][0]['frequency']['uncertainty_status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.source['samples'][0]['frequency']['frequency_annual_rate_ci95'], [0., 0.])

    def test_unknown_billing_and_stale_summary_are_not_invented(self):
        self.source['unknown_billing'] = True; self.source['status']['processed_origins'] = 0
        result = reporting.normalize(self.source, self.c)
        self.assertIsNone(result['usd_upper_estimate']); self.assertEqual(result['status']['state'], 'SUMMARY_PENDING')

    def test_reporting_cannot_change_experiment_or_grant_authority(self):
        for key in ('orders_allowed', 'experiment_or_evaluator_changes_allowed'):
            bad = dict(self.c); bad[key] = True
            with self.assertRaises(ValueError): reporting.validate(bad)


if __name__ == '__main__': unittest.main()
