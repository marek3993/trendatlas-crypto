import tempfile
import unittest
from pathlib import Path
from scripts.execution.cutover_pi_to_vps import Cutover


class Backend:
    def __init__(self,fail=None):
        self.calls=[]; self.fail=fail; self.pi=True; self.vps=False; self.orders=0; self.nonce=123
    def call(self,name):
        self.calls.append(name)
        if name==self.fail: raise RuntimeError('injected failure')
    def preflight(self): self.call('preflight'); return {'signer':'same','account':'same'}
    def wait_pi_idle(self): self.call('wait')
    def fence_pi(self): self.call('fence'); self.pi=False
    def verify_pi_fenced(self): self.call('verify_pi'); assert not self.pi
    def final_checkpoint(self): self.call('checkpoint'); return {'nonce':self.nonce,'actions':['confirmed-cloid']}
    def verify_handoff(self,c): self.call('handoff'); assert c['nonce']==self.nonce
    def vps_provably_never_activated(self): return not self.vps
    def restore_pi(self): self.call('restore'); assert not self.vps; self.pi=True
    def activate_vps(self): self.call('activate'); assert not self.pi; self.vps=True
    def run_once(self,state): self.call('run'); self.orders+=1; self.nonce+=1
    def readback(self): self.call('readback'); return {'verified':True,'nonce':self.nonce}
    def verify_sole_vps(self): self.call('sole'); assert self.vps and not self.pi
    def reconcile(self,state): self.call('reconcile'); return {'verified':True,'nonce':self.nonce}


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.path=Path(self.temp.name)/'state.json'
    def test_single_execution_host_and_sequence_handoff(self):
        b=Backend(); Cutover(b,self.path).execute()
        self.assertLess(b.calls.index('verify_pi'),b.calls.index('activate'))
        self.assertLess(b.calls.index('handoff'),b.calls.index('run'))
        self.assertEqual(b.nonce,124)
    def test_idempotent_repeat_never_second_order(self):
        b=Backend(); Cutover(b,self.path).execute(); Cutover(b,self.path).execute(); self.assertEqual(b.orders,1)
    def test_failure_before_activation_restores_pi(self):
        b=Backend('handoff')
        with self.assertRaises(RuntimeError): Cutover(b,self.path).execute()
        self.assertTrue(b.pi); self.assertFalse(b.vps); self.assertEqual(b.orders,0)
    def test_failure_after_possible_submission_reconciles_no_replay(self):
        b=Backend('readback')
        with self.assertRaises(RuntimeError): Cutover(b,self.path).execute()
        self.assertFalse(b.pi); self.assertEqual(b.orders,1)
        b.fail=None; Cutover(b,self.path).execute()
        self.assertEqual(b.orders,1); self.assertIn('reconcile',b.calls); self.assertNotIn('restore',b.calls)
    def test_activation_rejected_before_side_effect_restores_pi(self):
        b=Backend('activate')
        with self.assertRaises(RuntimeError): Cutover(b,self.path).execute()
        self.assertTrue(b.pi); self.assertFalse(b.vps)
    def test_interruption_before_acknowledgement_is_uncertain(self):
        b=Backend('run')
        with self.assertRaises(RuntimeError): Cutover(b,self.path).execute()
        b.fail=None; Cutover(b,self.path).execute(); self.assertEqual(b.calls.count('run'),1)
    def test_failed_preflight_does_not_fence_pi(self):
        b=Backend('preflight')
        with self.assertRaises(RuntimeError): Cutover(b,self.path).execute()
        self.assertNotIn('fence',b.calls); self.assertTrue(b.pi)
    def test_persistent_timer_uses_only_canonical_service(self):
        root=Path(__file__).resolve().parents[1]
        timer=(root/'scripts/systemd/vps/mrv1-production.timer').read_text()
        self.assertIn('Persistent=true',timer); self.assertIn('Unit=mrv1-production.service',timer)

if __name__=='__main__': unittest.main()
