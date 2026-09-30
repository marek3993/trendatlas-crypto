import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.execution.migration_readiness import bindings, validate_receipt
from scripts.execution.migration_diagnostics import MigrationError, remote_error, failure_report
from scripts.execution.cutover_pi_to_vps import main, Cutover
from tests.test_operator_cutover import Backend


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)
        self.payload = {'target': {'closedDay': '2026-09-29', 'asset': 'AVAX', 'exposure': 1, 'signalId': 'day29'},
                        'journal': {'sha256': 'journal'}, 'accounts': [{'accountId': 'owner', 'masterAddress': '0x123',
                        'signerFingerprint': 'signer', 'account': {'positions': [{'asset': 'AVAX', 'size': 7.65, 'markPrice': 11}],
                        'equityUsd': 85, 'openOrders': [], 'openOrderCount': 0}, 'recentFills': [],
                        'plan': {'state': 'NO_ACTION', 'actions': []}}]}
        self.ready = {'receipt_version': 2, 'observed_at': self.now.isoformat(), **bindings(self.payload)}
        self.ready['current_replay'] = {**bindings(self.payload), 'status': 'PASS', 'report_sha256': 'report', 'inputs_sha256': 'inputs'}

    def assert_blocked(self, code):
        with self.assertRaises(MigrationError) as caught:
            validate_receipt(self.ready, self.payload, self.now)
        self.assertEqual(caught.exception.code, code)

    def test_current_exact_binding_passes(self):
        validate_receipt(self.ready, self.payload, self.now)

    def test_historical_unbound_receipt_fails(self):
        self.ready.pop('receipt_version'); self.assert_blocked('RECEIPT_UNBOUND')

    def test_midnight_rollover_fails(self):
        self.ready['closed_day'] = '2026-09-28'; self.assert_blocked('RECEIPT_DAY_CHANGED')

    def test_old_and_future_receipt_fail(self):
        for timestamp in ['2026-09-30T13:00:00+00:00', '2026-09-30T14:00:01+00:00', 'invalid']:
            self.ready['observed_at'] = timestamp; self.assert_blocked('RECEIPT_EXPIRED')

    def test_signal_change_fails(self):
        self.payload['target']['signalId'] = 'changed'; self.assert_blocked('RECEIPT_TARGET_CHANGED')

    def test_position_orders_fills_identity_change_fail(self):
        original = copy.deepcopy(self.payload)
        for mutate in [lambda a: a['account']['positions'][0].update(size=8),
                       lambda a: a['account'].update(openOrders=[{'oid': 1}], openOrderCount=1),
                       lambda a: a.update(recentFills=[{'time': 123}]),
                       lambda a: a.update(signerFingerprint='different')]:
            self.payload = copy.deepcopy(original)
            mutate(self.payload['accounts'][0]); self.assert_blocked('RECEIPT_ACCOUNT_CHANGED')

    def test_market_valuation_alone_is_not_a_trade(self):
        self.payload['accounts'][0]['account']['positions'][0]['markPrice'] = 12
        self.payload['accounts'][0]['account']['equityUsd'] = 90
        validate_receipt(self.ready, self.payload, self.now)

    def test_journal_and_planner_changes_fail(self):
        self.payload['journal']['sha256'] = 'new'; self.assert_blocked('RECEIPT_JOURNAL_CHANGED')
        self.payload['journal']['sha256'] = 'journal'
        self.payload['accounts'][0]['plan']['state'] = 'READY'; self.assert_blocked('RECEIPT_PLANNER_CHANGED')

    def test_old_replay_fails(self):
        self.ready['current_replay']['closed_day'] = '2026-09-28'; self.assert_blocked('REPLAY_UNBOUND')

    def test_runtime_inputs_drift_fails_even_when_target_unchanged(self):
        self.ready['runtime_inputs_sha256'] = 'original'
        with self.assertRaises(MigrationError) as caught:
            validate_receipt(self.ready, self.payload, self.now, runtime_inputs_sha256='changed')
        self.assertEqual(caught.exception.code, 'RECEIPT_INPUTS_CHANGED')

    def test_untrusted_remote_output_cannot_leak(self):
        for raw in ['secret=abc', json.dumps({'reason_code': 'secret=abc'}), '{"reason_code":[]}', '[]', 'null']:
            self.assertEqual(str(remote_error(raw)), 'REMOTE_FAILURE')
        self.assertEqual(str(remote_error('{"reason_code":"CURRENT_CLOSED_DAY_REQUIRED","secret":"abc"}')), 'CURRENT_CLOSED_DAY_REQUIRED')

    def test_fail_before_fence_for_every_binding_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            for code in ['CURRENT_CLOSED_DAY_REQUIRED', 'RECEIPT_EXPIRED', 'RECEIPT_ACCOUNT_CHANGED', 'RECEIPT_JOURNAL_CHANGED']:
                backend = Backend()
                with patch.object(backend, 'preflight', side_effect=MigrationError(code)):
                    with self.assertRaises(MigrationError): Cutover(backend, Path(tmp)/'state').execute()
                self.assertEqual(backend.calls, []); self.assertEqual(backend.orders, 0)

    def test_failure_flags_are_conservative(self):
        error = RuntimeError('secret')
        self.assertIsNone(failure_report(error, {'phase': 'UNKNOWN'})['live_activation_possible'])
        self.assertIsNone(failure_report(error, {'phase': 'FENCING_PI'})['pi_fenced'])
        self.assertTrue(failure_report(error, {'phase': 'ACTIVATING'})['live_activation_possible'])

    def test_cli_writes_safe_diagnostic_without_traceback(self):
        import io
        with tempfile.TemporaryDirectory() as tmp, patch('sys.stdout', new_callable=io.StringIO) as output:
            report = Path(tmp)/'report.json'
            with patch('scripts.execution.cutover_pi_to_vps.SSHBackend.preflight', side_effect=MigrationError('CURRENT_CLOSED_DAY_REQUIRED')):
                rc = main(['--state', str(Path(tmp)/'state'), '--diagnostic-report', str(report)])
            self.assertEqual(rc, 1)
            data = json.loads(report.read_text())
            self.assertFalse(data['pi_fenced']); self.assertFalse(data['live_activation_possible'])
            self.assertEqual(data['reason_code'], 'CURRENT_CLOSED_DAY_REQUIRED')
            self.assertNotIn('Traceback', output.getvalue())


if __name__ == '__main__': unittest.main()
