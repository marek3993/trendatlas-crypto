"""Installer sequencing tests with a fake VPS; no system service or network is used."""
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
import base64
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
    def test_bundle_path_escape_rejected(self):
        m=module(ROOT/'deploy/clean_5050/bootstrap_multi_account.py','clean_installer')
        buf=io.BytesIO();body=b'bad'
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('../escape',body)
            z.writestr('BUNDLE_MANIFEST.json',json.dumps({'../escape':hashlib.sha256(body).hexdigest()}))
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(ValueError,'UNSAFE'):
            m.unpack(buf.getvalue(),Path(temp))
    def simulate(self, fail=None, *, activate=True):
        builder=module(ROOT/'scripts/production/build_clean_installer.py','builder2')
        body,_=builder.bundle()
        m=module(ROOT/'deploy/clean_5050/bootstrap_multi_account.py','installer2')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);base=Path(tmp.name)
        m.ROOT=base/'opt/clean';m.STATE=base/'state';m.INSTALL=base/'install';m.CONFIG=base/'etc/policy.json';m.SYSTEMD=base/'systemd'
        m.SYSTEMD.mkdir();m.BUNDLE_B64=base64.b64encode(body).decode();m.BUNDLE_SHA256=hashlib.sha256(body).hexdigest()
        commands=[]
        def fake_run(args,**kwargs):
            args=[str(x) for x in args];commands.append(args)
            if fail=='unit' and 'unittest' in args:raise RuntimeError('UNIT_TEST_FAILED')
            if any('fetch_clean_5050_data.py' in x for x in args):
                (m.STATE/'validation-data').mkdir(parents=True,exist_ok=True)
            if any('validate_clean_5050.py' in x for x in args):
                p=m.STATE/'validation-results';p.mkdir(exist_ok=True)
                (p/'validation.json').write_text(json.dumps({'passed':fail!='reference','checkpoint_matches':18 if fail!='reference' else 17}))
            if any('run_clean_5050.py' in x for x in args):
                p=m.STATE/'state';p.mkdir(exist_ok=True);(p/'signal.json').write_text('{}')
            if any('run-clean-multi-account.ts' in x for x in args):
                if fail=='signer':raise RuntimeError('SIGNER_FAILED')
                (m.STATE/'state/multi_account_preflight.json').write_text(json.dumps({'preflight_passed':True,'account_count':2}))
            if args==['systemctl','start',m.UNIT+'.service']:
                if fail=='live':raise RuntimeError('LIVE_RESPONSE_LOST')
                (m.STATE/'state/multi_account_receipt.json').write_text(json.dumps({'all_accounts_aligned':True}))
            return subprocess.CompletedProcess(args,0,'','')
        def fake_subprocess(args,**kwargs):
            return subprocess.CompletedProcess(args,0,'inactive','')
        args=SimpleNamespace(source_commit='a'*40,python=None,activate_live=activate)
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
        self.assertTrue(json.loads((m.INSTALL/'status.json').read_text())['live_activation_possible'])
        self.assertNotIn(['systemctl','start','mrv1-production.service'],commands)
    def test_default_install_does_not_activate(self):
        m,commands,error=self.simulate(activate=False)
        self.assertIsNone(error)
        self.assertTrue(json.loads(m.CONFIG.read_text())['kill_switch'])
        self.assertEqual(json.loads((m.INSTALL/'status.json').read_text())['status'],'TESTED_MULTI_ACCOUNT_NOT_ACTIVATED')
    def test_daily_timer_has_no_extra_signal_shift(self):
        timer=(ROOT/'deploy/systemd/trendatlas-clean-production.timer').read_text()
        self.assertIn('OnCalendar=*-*-* 00:10:00 UTC',timer)
        unit=(ROOT/'deploy/systemd/trendatlas-clean-production.service').read_text()
        self.assertIn('run_clean_multi_account.py',unit)
        self.assertNotIn('execute_clean_5050.py',unit)
        self.assertIn('EnvironmentFile=/etc/trendatlas-production/multi-account.env',unit)
        self.assertNotIn('LoadCredentialEncrypted',unit)


if __name__=='__main__':unittest.main()
