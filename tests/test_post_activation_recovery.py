import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from scripts.execution.cutover_pi_to_vps import Cutover, SSHBackend, main
from scripts.execution.migration_diagnostics import MigrationError
from scripts.execution.migration_reconciliation import classify_execution
from scripts.execution.recover_production_publication import recover
from scripts.execution import migration_host_control as host
from tests.test_operator_cutover import Backend


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.manifest={'run_id':'new','target_closed_day':'2026-09-29','signal_id':'signal','no_submit':False,
            'execution_outcome':'NO_ACTION','final_status':'EXECUTION_COMPLETE_PUBLISH_FAILED','real_order_sent':False,
            'failure_stage':'AUTHORITY_PUBLISH','failure_reason':'original_failure',
            'stages':{s:{'status':'PASSED'} for s in ['EXECUTE','POST_TRADE_VERIFY','AUTHORITY_PUBLISH']}}
        self.payload={'target':{'closedDay':'2026-09-29','signalId':'signal'},'journalUnchanged':True,
            'accounts':[{'accountId':'account','plan':{'state':'NO_ACTION'}}],
            'journal':{'tables':{'multi_account_execution_locks':[],'multi_account_agent_nonces':[{'last_nonce':1}],
                'multi_account_execution_actions':[{'verification_state':'VERIFIED'}],
                'multi_account_execution_runs':[{'hyperliquid_account_id':'account','canonical_signal_id':'signal',
                    'canonical_closed_day':'2026-09-29','status':'NO_ACTION','completed_at':'now'}]}}}
        self.activation={'previous_run_id':'old'}

    def classify(self): return classify_execution(self.manifest,self.payload,self.activation)

    def test_publish_failure_is_known_execution_not_unknown_submission(self):
        r=self.classify();self.assertTrue(r['execution_verified']);self.assertFalse(r['verified'])
        self.assertEqual(r['reason_code'],'PUBLICATION_PENDING')

    def test_success_requires_publication(self):
        self.manifest['final_status']='SUCCESS';self.assertFalse(self.classify()['verified'])
        self.manifest['authority_status']='PASSED';self.assertTrue(self.classify()['verified'])

    def test_unknown_cloid_blocks_even_if_wallet_aligned(self):
        self.payload['journal']['tables']['multi_account_execution_actions'][0]['verification_state']='UNKNOWN'
        self.assertFalse(self.classify()['execution_verified'])

    def test_missing_journal_or_unfinished_run_blocks(self):
        self.payload['journal']['tables'].pop('multi_account_execution_runs')
        self.assertFalse(self.classify()['execution_verified'])

    def test_wrong_run_signal_day_or_no_submit_blocks(self):
        original=copy.deepcopy(self.manifest)
        for key,value in [('run_id','old'),('signal_id','other'),('target_closed_day','old'),('no_submit',True)]:
            self.manifest=original|{key:value};self.assertFalse(self.classify()['execution_verified'])

    def test_response_loss_automatically_reconciles_without_second_run(self):
        b=Backend('run');state=self.root/'state.json'
        self.assertTrue(Cutover(b,state).execute()['verified'])
        b.fail=None;Cutover(b,state).execute()
        self.assertEqual(b.calls.count('run'),1);self.assertNotIn('restore',b.calls)

    def test_uncertainty_saved_before_failing_network_probe(self):
        b=Backend('run');state=self.root/'state.json'
        b.reconcile=Mock(side_effect=RuntimeError('connection_lost'))
        b.vps_provably_never_activated=Mock(side_effect=AssertionError('must not probe rollback after run request'))
        with self.assertRaises(RuntimeError):Cutover(b,state).execute()
        self.assertEqual(json.loads(state.read_text())['phase'],'RECONCILE_REQUIRED')
        self.assertNotIn('restore',b.calls)

    def test_cli_unknown_failure_always_includes_host_snapshot(self):
        state=self.root/'state.json';state.write_text('{"phase":"RUN_REQUESTED"}')
        snapshot={'pi':{'available':True,'fenced':True},'vps':{'available':False}}
        with patch('scripts.execution.cutover_pi_to_vps.SSHBackend.verify_pi_fenced',side_effect=MigrationError('REMOTE_FAILURE')),patch('scripts.execution.cutover_pi_to_vps.SSHBackend.snapshot',return_value=snapshot),patch('sys.stdout',new_callable=io.StringIO) as out:
            rc=main(['--reconcile-only','--state',str(state),'--diagnostic-report',str(self.root/'diagnostic')])
        d=json.loads(out.getvalue());self.assertEqual(rc,1);self.assertEqual(d['host_state'],snapshot)
        self.assertTrue(d['pi_fenced']);self.assertTrue(d['live_activation_possible'])

    def test_ssh_timeout_is_classified_without_exposing_stderr(self):
        with patch('subprocess.run',return_value=Mock(returncode=255,stdout='',stderr='secret Connection timed out')):
            with self.assertRaises(MigrationError) as caught:SSHBackend(Path('key')).remote('host','command')
        self.assertEqual(caught.exception.code,'SSH_CONNECTION_TIMEOUT')
        self.assertEqual(caught.exception.remote_exit_code,255);self.assertNotIn('secret',str(caught.exception))

    def store_manifest(self):
        base=self.root/'outputs/execution/production_runs';(base/'new').mkdir(parents=True)
        for p in [base/'latest_production_run.json',base/'new/production_run_manifest.json']:p.write_text(json.dumps(self.manifest))
        return base/'latest_production_run.json'

    def test_publication_recovery_is_dry_run_first_and_idempotent(self):
        latest=self.store_manifest();publish=Mock()
        recover(self.root,'new',self.payload,self.activation,publish)
        self.assertEqual([c.args for c in publish.call_args_list],[(True,),(False,)])
        d=json.loads(latest.read_text());self.assertEqual(d['final_status'],'SUCCESS');self.assertFalse(d['real_order_sent'])
        recover(self.root,'new',self.payload,self.activation,publish);self.assertEqual(publish.call_count,2)

    def test_failed_republication_preserves_original_execution(self):
        latest=self.store_manifest()
        with self.assertRaises(RuntimeError):recover(self.root,'new',self.payload,self.activation,Mock(side_effect=RuntimeError('fail')))
        self.assertEqual(json.loads(latest.read_text()),self.manifest)

    def test_interrupted_publication_can_resume_without_execution(self):
        self.manifest.update(final_status='SUCCESS',authority_status='RECOVERY_PENDING',publication_recovery={'status':'RUNNING'})
        self.store_manifest();publish=Mock()
        result=recover(self.root,'new',self.payload,self.activation,publish)
        self.assertFalse(result['execution_repeated']);self.assertEqual(publish.call_count,2)

    def test_recovery_cannot_republish_another_or_unverified_run(self):
        self.store_manifest();publish=Mock()
        with self.assertRaises(RuntimeError):recover(self.root,'wrong',self.payload,self.activation,publish)
        self.payload['journalUnchanged']=False
        with self.assertRaises(RuntimeError):recover(self.root,'new',self.payload,self.activation,publish)
        publish.assert_not_called()

    def test_root_probe_is_not_enough_for_readability(self):
        with patch.object(host,'property_value',return_value='production'),patch.object(host.subprocess,'run',return_value=Mock(returncode=1)) as runner:
            with self.assertRaises(MigrationError) as caught:host.verify_service_readability()
        self.assertEqual(caught.exception.code,'CAPABILITIES_UNREADABLE')
        self.assertEqual(runner.call_args.args[0][:3],['runuser','-u','production'])

    @unittest.skipUnless(__import__('os').name=='posix','Linux ownership integration')
    def test_atomic_capability_replacement_preserves_service_group_access(self):
        import os,pwd,stat
        path=self.root/'capabilities.json';path.write_text('{}');path.chmod(0o600)
        with patch.object(host,'CAPABILITIES',path),patch.object(host,'property_value',return_value=pwd.getpwuid(os.getuid()).pw_name),patch.object(host.os,'chown') as chown,patch.object(host,'verify_service_readability') as verify:
            host.write_capabilities({'activated':True})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o640);chown.assert_called_once();verify.assert_called_once()
