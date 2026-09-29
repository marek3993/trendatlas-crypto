import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from scripts.execution.production_research_priority import control
from scripts.execution.pi_migration_host_control import verify_retirement_proof


class PriorityTests(unittest.TestCase):
    def test_checkpoint_stop_precedes_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'paused'; calls=[]
            def run(args,**kw):
                calls.append(args); return subprocess.CompletedProcess(args,0,stdout='success\n')
            control('pause',run,marker); self.assertTrue(marker.exists())
            self.assertIn(['systemctl','stop','trendatlas-research-worker.service'],calls)
            control('resume',run,marker); self.assertFalse(marker.exists())
            self.assertEqual(calls[-1],['systemctl','start','--no-block','trendatlas-research-worker.service'])
    def test_checkpoint_failure_keeps_admission_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'paused'
            def run(args,**kw): return subprocess.CompletedProcess(args,0,stdout='failed\n')
            with self.assertRaises(RuntimeError): control('pause',run,marker)
            self.assertTrue(marker.exists())
    def test_sealed_inactive_worker_not_started(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'paused'; calls=[]
            def run(args,**kw): calls.append(args); return subprocess.CompletedProcess(args,3)
            control('pause',run,marker); control('resume',run,marker)
            self.assertEqual(len(calls),1)
    def test_retirement_requires_success_and_actual_reboot(self):
        record={'old_boot_id':'before','plan':{'units':['production.timer']}}
        states={'production.timer':('masked','inactive')}
        self.assertTrue(verify_retirement_proof(record,'after',states,False)['reboot_verified'])
        for boot,units,secret in [('before',states,False),('after',{'production.timer':('enabled','active')},False),('after',states,True)]:
            with self.subTest(boot=boot,units=units,secret=secret), self.assertRaises(RuntimeError):
                verify_retirement_proof(record,boot,units,secret)
    def test_cleanup_archives_before_removing_credential_and_reboots_last(self):
        from scripts.execution import pi_migration_host_control as host
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); state=root/'state'; state.mkdir()
            def mapped(value): return root/str(value).lstrip('/')
            for name,value in [('/proc/sys/kernel/random/boot_id','before'),('/etc/default/trendatlas-multi-account','synthetic'),('/etc/systemd/system/mrv1-production.service','unit')]:
                p=mapped(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            plan={'units':['mrv1-production.service'],'cron_users':{},'cron_files':[],'user_units':[]}; calls=[]
            def archive(plan):
                self.assertTrue(mapped('/etc/default/trendatlas-multi-account').exists())
                calls.append('encrypted_archive_verified'); return 'a'*64
            def run(*args,**kw): calls.append(args); return 'inactive' if args[:2]==('systemctl','show') else ''
            with patch.object(host,'STATE',state),patch.object(host,'Path',side_effect=mapped),patch.object(host,'verify_fenced'),patch.object(host,'inventory',return_value=plan),patch.object(host,'encrypted_archive',side_effect=archive),patch.object(host,'run',side_effect=run):
                host.retire({'verified':True})
            self.assertEqual(calls[0],'encrypted_archive_verified')
            self.assertEqual(calls[-1],('systemctl','reboot'))
            self.assertFalse(mapped('/etc/default/trendatlas-multi-account').exists())
            self.assertTrue((state/'retired-units/mrv1-production.service').exists())
            self.assertIn(('systemctl','mask','mrv1-production.service'),calls)

if __name__=='__main__': unittest.main()
