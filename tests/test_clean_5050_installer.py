"""Installer sequencing tests with a fake VPS; no system service or network is used."""
from contextlib import ExitStack
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
import base64
import fcntl
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def module(path,name):
    spec=spec_from_file_location(name,path);m=module_from_spec(spec);spec.loader.exec_module(m);return m


class InstallerTests(unittest.TestCase):
    def test_bundle_reproducible_no_runtime_data_or_keys(self):
        b=module(ROOT/'scripts/production/build_clean_installer.py','clean_builder')
        a,manifest=b.bundle();other,_=b.bundle()
        self.assertEqual(a,other)
        self.assertIn('src/trendatlas_clean/execution.py',manifest)
        self.assertFalse(any(n.startswith(('data/','outputs/')) or 'private-key' in n or n.endswith('.sqlite3') for n in manifest))
    def test_unpack_preserves_bundle_manifest_at_release_root(self):
        builder=module(ROOT/'scripts/production/build_clean_installer.py','manifest_builder')
        installer=module(ROOT/'deploy/clean_5050/bootstrap_multi_account.py','manifest_installer')
        body,expected=builder.bundle()
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            original=archive.read('BUNDLE_MANIFEST.json')
        with tempfile.TemporaryDirectory() as temp:
            release=Path(temp)
            self.assertEqual(installer.unpack(body,release),expected)
            manifest=release/'BUNDLE_MANIFEST.json'
            self.assertTrue(manifest.is_file(), 'Release root must identify the source bundle without Git')
            self.assertEqual(manifest.read_bytes(),original)
            self.assertEqual(json.loads(manifest.read_bytes()),expected)
    def test_bundle_path_escape_rejected(self):
        m=module(ROOT/'deploy/clean_5050/bootstrap_multi_account.py','clean_installer')
        buf=io.BytesIO();body=b'bad'
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('../escape',body)
            z.writestr('BUNDLE_MANIFEST.json',json.dumps({'../escape':hashlib.sha256(body).hexdigest()}))
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(ValueError,'UNSAFE'):
            m.unpack(buf.getvalue(),Path(temp))
    def simulate(self, fail=None, *, activate=True, active=False, upgrade=False, busy=False, lock_busy=False):
        builder=module(ROOT/'scripts/production/build_clean_installer.py','builder2')
        body,_=builder.bundle()
        m=module(ROOT/'deploy/clean_5050/bootstrap_multi_account.py','installer2')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);base=Path(tmp.name)
        m.ROOT=base/'opt/clean';m.STATE=base/'state';m.INSTALL=base/'install';m.CONFIG=base/'etc/policy.json';m.SYSTEMD=base/'systemd';m.TIMER_STAMPS=base/'timers'
        m.SYSTEMD.mkdir();m.BUNDLE_B64=base64.b64encode(body).decode();m.BUNDLE_SHA256=hashlib.sha256(body).hexdigest()
        commands=[]
        timer_active=active
        if active:
            m.CONFIG.parent.mkdir(parents=True)
            policy=json.loads((ROOT/'execution/config/clean_5050_policy.json').read_text())
            policy.update(kill_switch=False,trading_enabled=True,operator_setting='preserved')
            m.CONFIG.write_text(json.dumps(policy))
        preflight={'preflight_passed':True,'account_count':2,'signal_id':'signal','closed_day':'2026-10-18'}
        def fake_run(args,**kwargs):
            nonlocal timer_active
            args=[str(x) for x in args];commands.append(args)
            if args==['systemctl','disable','--now',m.UNIT+'.timer']:timer_active=False
            if args==['systemctl','enable','--now',m.UNIT+'.timer']:
                stamp=m.TIMER_STAMPS/('stamp-'+m.UNIT+'.timer')
                self.assertTrue(stamp.is_file())
                receipt=json.loads((m.STATE/'state/multi_account_receipt.json').read_text())
                self.assertGreaterEqual(stamp.stat().st_mtime,datetime.fromisoformat(receipt['generated_at_utc']).timestamp())
            if fail=='unit' and 'unittest' in args:raise RuntimeError('UNIT_TEST_FAILED')
            if any('fetch_clean_5050_data.py' in x for x in args):
                (m.STATE/'validation-data').mkdir(parents=True,exist_ok=True)
            if any('validate_clean_5050.py' in x for x in args):
                p=m.STATE/'validation-results';p.mkdir(exist_ok=True)
                (p/'validation.json').write_text(json.dumps({'passed':fail!='reference','checkpoint_matches':18 if fail!='reference' else 17}))
            if any('run_clean_5050.py' in x for x in args):
                p=m.STATE/'state';p.mkdir(exist_ok=True);(p/'signal.json').write_text('{}')
            if any('run-clean-multi-account.ts' in x for x in args):
                with (m.STATE/'state/production.lock').open('a') as probe:
                    with self.assertRaises(BlockingIOError):fcntl.flock(probe.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                if fail=='signer':raise RuntimeError('SIGNER_FAILED')
                (m.STATE/'state/multi_account_preflight.json').write_text(json.dumps(preflight))
            if args==['systemctl','start',m.UNIT+'.service']:
                with (m.STATE/'state/production.lock').open('a') as probe:
                    fcntl.flock(probe.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                receipt={'mode':'CLEAN_MULTI_ACCOUNT','signal_id':'signal','closed_day':'2026-10-18',
                         'account_count':2,'all_accounts_aligned':fail!='receipt',
                         'results':[{'status':'FILLED_AND_ALIGNED','orderRequested':True} for _ in range(2)],
                         'generated_at_utc':datetime.now(timezone.utc).isoformat()}
                if fail=='stale':receipt['generated_at_utc']='2020-01-01T00:00:00Z'
                if fail=='live':
                    receipt['all_accounts_aligned']=False
                    receipt['results'][0]={'status':'FAILED','orderRequested':False,'reason':'setLeverageOne: Error: rejected'}
                (m.STATE/'state/multi_account_receipt.json').write_text(json.dumps(receipt))
                if fail=='live':raise RuntimeError('LIVE_RESPONSE_LOST')
            return subprocess.CompletedProcess(args,0,'','')
        def fake_subprocess(args,**kwargs):
            state='activating' if busy and args[-1]==m.UNIT+'.service' else ('active' if timer_active and args[-1]==m.UNIT+'.timer' else 'inactive')
            return subprocess.CompletedProcess(args,0,state,'')
        args=SimpleNamespace(source_commit='a'*40,python=None,activate_live=activate,upgrade_active=upgrade)
        with ExitStack() as stack:
            stack.enter_context(patch.object(m,'run',side_effect=fake_run))
            stack.enter_context(patch.object(m,'capture',return_value='enabled'))
            stack.enter_context(patch.object(m,'python_runtime',return_value='/validated/python'))
            stack.enter_context(patch.object(m,'environment_source',return_value=Path('/existing/multi-account.env')))
            stack.enter_context(patch.object(m,'node_runtime',return_value='/usr/bin/node'))
            stack.enter_context(patch.object(m.shutil,'which',return_value='/usr/bin/npm'))
            stack.enter_context(patch.object(m,'old_disabled'))
            stack.enter_context(patch.object(m.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=0)))
            stack.enter_context(patch.object(m.os,'chown'))
            stack.enter_context(patch.object(m.subprocess,'run',side_effect=fake_subprocess))
            if lock_busy:stack.enter_context(patch.object(m.fcntl,'flock',side_effect=BlockingIOError))
            try:m.install(args);error=None
            except (ValueError,RuntimeError) as exc:error=str(exc)
        return m,commands,error
    def test_unit_failure_never_clears_kill_or_starts_live(self):
        m,commands,error=self.simulate('unit')
        self.assertEqual(error,'UNIT_TEST_FAILED')
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
        self.assertNotIn(['systemctl','start',m.UNIT+'.service'],commands)
    def test_reference_failure_never_clears_kill(self):
        m,commands,error=self.simulate('reference')
        self.assertEqual(error,'HISTORICAL_REFERENCE_VALIDATION_FAILED')
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
    def test_signer_failure_never_clears_kill(self):
        m,commands,error=self.simulate('signer')
        self.assertEqual(error,'SIGNER_FAILED')
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
    def test_activation_only_after_tests_reference_and_signer(self):
        m,commands,error=self.simulate()
        self.assertIsNone(error)
        unit=next(i for i,c in enumerate(commands) if 'unittest' in c)
        reference=next(i for i,c in enumerate(commands) if any('validate_clean_5050.py' in x for x in c))
        signer=next(i for i,c in enumerate(commands) if any('run-clean-multi-account.ts' in x for x in c))
        start=commands.index(['systemctl','start',m.UNIT+'.service'])
        self.assertLess(unit,reference);self.assertLess(reference,signer);self.assertLess(signer,start)
        self.assertFalse(json.loads(m.CONFIG.read_text())['kill_switch'])
        self.assertEqual(json.loads((m.INSTALL/'status.json').read_text())['status'],'CLEAN_MULTI_ACCOUNT_LIVE_AND_ALIGNED')
    def test_live_failure_is_recorded_as_possible_activation(self):
        m,commands,error=self.simulate('live')
        self.assertEqual(error,'LIVE_RESPONSE_LOST')
        report=json.loads((m.INSTALL/'status.json').read_text())
        self.assertTrue(report['live_activation_possible'])
        self.assertEqual(report['account_results'][0]['reason'],'setLeverageOne: Error: rejected')
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
        self.assertNotIn(['systemctl','enable','--now',m.UNIT+'.timer'],commands)
        self.assertNotIn(['systemctl','start','mrv1-production.service'],commands)
    def test_default_install_does_not_activate(self):
        m,commands,error=self.simulate(activate=False)
        self.assertIsNone(error)
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
        self.assertEqual(json.loads((m.INSTALL/'status.json').read_text())['status'],'TESTED_MULTI_ACCOUNT_NOT_ACTIVATED')
    def test_active_install_requires_explicit_upgrade(self):
        m,commands,error=self.simulate(active=True)
        self.assertIsNone(error)
        self.assertEqual(commands,[])
        self.assertFalse(json.loads(m.CONFIG.read_text())['kill_switch'])
    def test_upgrade_pauses_before_tests_preserves_policy_and_starts_exactly_once(self):
        m,commands,error=self.simulate(active=True,upgrade=True)
        self.assertIsNone(error)
        pause=commands.index(['systemctl','disable','--now',m.UNIT+'.timer'])
        tests=next(i for i,c in enumerate(commands) if 'unittest' in c)
        group=commands.index(['usermod','-aG','trendatlas-production','trendatlas-clean'])
        preflight=next(i for i,c in enumerate(commands) if any('run-clean-multi-account.ts' in x for x in c))
        start=commands.index(['systemctl','start',m.UNIT+'.service'])
        reset=commands.index(['systemctl','clean','--what=state',m.UNIT+'.timer'])
        resume=commands.index(['systemctl','enable','--now',m.UNIT+'.timer'])
        self.assertLess(pause,tests);self.assertLess(group,preflight);self.assertLess(preflight,start)
        self.assertLess(start,reset);self.assertLess(reset,resume)
        self.assertEqual(commands.count(['systemctl','start',m.UNIT+'.service']),1)
        self.assertIn('--property=SupplementaryGroups=trendatlas-production',commands[preflight])
        self.assertEqual(json.loads(m.CONFIG.read_text())['operator_setting'],'preserved')
    def test_upgrade_never_interrupts_inflight_worker(self):
        m,commands,error=self.simulate(active=True,upgrade=True,busy=True)
        self.assertEqual(error,'CLEAN_WORKER_BUSY_WAIT_FOR_COMPLETION')
        self.assertEqual(commands,[])
        self.assertFalse(json.loads(m.CONFIG.read_text())['kill_switch'])
    def test_upgrade_does_not_modify_a_manually_running_locked_worker(self):
        m,commands,error=self.simulate(active=True,upgrade=True,lock_busy=True)
        self.assertEqual(error,'CLEAN_PRODUCTION_LOCK_BUSY_TIMER_PAUSED')
        self.assertEqual(commands,[['systemctl','disable','--now',m.UNIT+'.timer']])
        self.assertFalse(json.loads(m.CONFIG.read_text())['kill_switch'])
    def test_failed_upgrade_stays_disarmed_without_resuming_timer(self):
        for failure in ('unit','signer','reference','live','receipt','stale'):
            with self.subTest(failure=failure):
                m,commands,error=self.simulate(failure,active=True,upgrade=True)
                self.assertIsNotNone(error)
                self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
                self.assertNotIn(['systemctl','enable','--now',m.UNIT+'.timer'],commands)
                self.assertNotIn(['systemctl','start','mrv1-production.service'],commands)
    def test_daily_timer_has_no_extra_signal_shift(self):
        timer=(ROOT/'deploy/systemd/trendatlas-clean-production.timer').read_text()
        self.assertIn('OnCalendar=*-*-* 00:10:00 UTC',timer)
        unit=(ROOT/'deploy/systemd/trendatlas-clean-production.service').read_text()
        self.assertIn('run_clean_multi_account.py',unit)
        self.assertNotIn('execute_clean_5050.py',unit)
        self.assertIn('EnvironmentFile=/etc/trendatlas-production/multi-account.env',unit)
        self.assertNotIn('LoadCredentialEncrypted',unit)
        self.assertIn('SupplementaryGroups=trendatlas-production',unit)


if __name__=='__main__':unittest.main()
