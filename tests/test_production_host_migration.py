import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from scripts.execution.production_host import validate_evidence, HostAdmissionError
from scripts.execution.rehearsal_workspace import create_rehearsal, assert_isolated_rehearsal, runtime_fingerprints
from scripts.execution.compare_production_replay import compare

ROOT = Path(__file__).resolve().parents[1]


class HostContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'live'; self.root.mkdir()
        (self.root / 'source_of_truth').mkdir()
        contract = json.loads((ROOT / 'source_of_truth/production_host_contract.json').read_text())
        (self.root / 'source_of_truth/production_host_contract.json').write_text(json.dumps(contract))
        (self.root / 'code.py').write_text('immutable')
        files = {'code.py': hashlib.sha256(b'immutable').hexdigest()}
        self.evidence = dict(machine_id='host', runtime_root=str(self.root.resolve()), files=files,node_version=contract['node_version'],
            cross_arch_golden_replay=dict(status='PASS', comparison='exact', platforms=['linux/aarch64','linux/x86_64'],
                manifest_sha256=hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), result_sha256='a'*64),
            systemd_verified=True, single_execution_host='host', activated_by_operator=True)
        self.args = dict(system='Linux', machine='x86_64', python_version=contract['python_version'],
            packages=contract['critical_python_packages'], machine_id='host', root=self.root)

    def test_x86_publication(self): validate_evidence(self.evidence, **self.args)
    def test_arm_publication(self): validate_evidence(self.evidence, **(self.args | {'machine':'aarch64'}))
    def test_unsupported_platform(self):
        for machine in ('armv7l', 'amd64', 'riscv64'):
            with self.subTest(machine=machine), self.assertRaises(HostAdmissionError):
                validate_evidence(self.evidence, **(self.args | {'machine':machine}))
    def test_dependency_drift(self):
        with self.assertRaises(HostAdmissionError): validate_evidence(self.evidence, **(self.args | {'python_version':'3.14.4'}))
    def test_manifest_drift(self):
        (self.root / 'code.py').write_text('changed')
        with self.assertRaises(HostAdmissionError): validate_evidence(self.evidence, **self.args)
    def test_replay_cannot_claim_new_tolerance(self):
        self.evidence['cross_arch_golden_replay']['comparison']='approximately'
        with self.assertRaises(HostAdmissionError): validate_evidence(self.evidence, **self.args)
    def test_single_host_and_operator_activation_required(self):
        for patch in ({'single_execution_host':'other'}, {'activated_by_operator':False}):
            with self.subTest(patch=patch), self.assertRaises(HostAdmissionError): validate_evidence(self.evidence | patch, **self.args)
    def test_no_submit_account_and_journal_isolation_on_failure(self):
        for rel in ('outputs/execution/read_only/account.json','outputs/execution/execution_journal/journal.json','data/bars.csv'):
            p=self.root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('original')
        before=runtime_fingerprints(self.root)
        stage=Path(self.temp.name)/'stage'; create_rehearsal(self.root, stage); assert_isolated_rehearsal(stage)
        (stage/'outputs/execution/read_only/account.json').write_text('failed preflight')
        self.assertEqual(before,runtime_fingerprints(self.root))
        self.assertEqual((stage/'outputs/execution/execution_journal/journal.json').read_text(),'original')
    def test_live_root_rejected(self):
        with self.assertRaises(RuntimeError): assert_isolated_rehearsal(self.root)
    def test_shared_hardlink_rejected(self):
        p=self.root/'outputs/account'; p.parent.mkdir(); p.write_text('account')
        stage=Path(self.temp.name)/'stage'; create_rehearsal(self.root,stage)
        (stage/'outputs/account').unlink(); (stage/'outputs/account').hardlink_to(p)
        with self.assertRaises(RuntimeError): assert_isolated_rehearsal(stage)
    def test_exact_cross_arch_replay_does_not_invent_tolerance(self):
        a={'snapshot':{'selected_asset':'AVAX','target_exposure':1},'timeseries':json.dumps({'columns':['return'],'index':[0],'data':[[1.0]]})}
        self.assertEqual(compare(a,a,{'state':'NO_ACTION'},{'state':'NO_ACTION'})['status'],'PASS')
        b=a | {'timeseries':json.dumps({'columns':['return'],'index':[0],'data':[[1.0+1e-14]]})}
        self.assertEqual(compare(a,b,{'state':'NO_ACTION'},{'state':'NO_ACTION'})['status'],'BLOCKED')
        self.assertEqual(compare(a,a,{'state':'NO_ACTION'},{'state':'RESIZE'})['status'],'BLOCKED')
    def test_legacy_identity_cannot_spoof_arm_on_vps(self):
        from scripts.execution.authority_contract import ensure_pi_only_publish_allowed
        env={'MRV1_ENABLE_AUTHORITY_PUBLISH':'1','MRV1_AUTHORITY_MODE':'authoritative',
             'MRV1_AUTOMATIC_PRODUCER_ID':'raspberry_pi','MRV1_RUNTIME_PLATFORM_SYSTEM':'linux','MRV1_RUNTIME_PLATFORM_MACHINE':'aarch64'}
        with patch('platform.system',return_value='Linux'),patch('platform.machine',return_value='x86_64'),self.assertRaises(PermissionError):
            ensure_pi_only_publish_allowed(env)

if __name__ == '__main__': unittest.main()
