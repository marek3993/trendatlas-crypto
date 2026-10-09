"""Native separate-user regression for a read-only observer's WAL side effects."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from scripts.audit_continuous_research import prepare_observer


@unittest.skipUnless(os.name=='posix' and hasattr(os,'geteuid') and os.geteuid()==0,'native root/isolated research users required')
class ObserverRegressionTests(unittest.TestCase):
    def test_readonly_observer_does_not_deny_separate_broker_writer(self):
        import grp
        gid=grp.getgrnam('trendatlas-research').gr_gid
        initial_group=os.getegid();initial_mask=os.umask(0o007)
        try:
            with tempfile.TemporaryDirectory(prefix='research-observer-regression-') as tmp:
                root=Path(tmp);os.chown(root,0,gid);root.chmod(0o770)
                dbpath=root/'research.sqlite'
                def writer(code):
                    return subprocess.run(['sudo','-u','trendatlas-continuous-broker',sys.executable,'-B','-c',
                        'import os,sqlite3;os.umask(7);d=sqlite3.connect('+repr(str(dbpath))+');'+code],capture_output=True,text=True)
                result=writer("d.execute('PRAGMA journal_mode=WAL');d.execute('CREATE TABLE t(n)');d.commit();d.close()")
                self.assertEqual(result.returncode,0,result.stderr)
                (root/'api.sqlite').touch();os.chown(root/'api.sqlite',0,gid)
                def reader():
                    child=subprocess.Popen(['sudo','-u','trendatlas-continuous',sys.executable,'-u','-B','-c',
                        'import os,sqlite3;os.umask(7);d=sqlite3.connect('+repr('file:'+str(dbpath)+'?mode=ro')+',uri=True);'
                        "d.execute('BEGIN');d.execute('SELECT * FROM t').fetchall();print('READY');input();d.close()"],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    self.assertEqual(child.stdout.readline().strip(),'READY');return child
                # A different UID reading the broker's default 0640 database creates
                # sidecars whose mode prevents the broker from opening them writable.
                child=reader()
                try:
                    failed=writer("d.execute('INSERT INTO t VALUES(1)');d.commit()")
                    self.assertNotEqual(failed.returncode,0);self.assertIn('readonly database',failed.stderr)
                finally:child.communicate('\n',timeout=10)
                for path in root.glob('research.sqlite*'):path.chmod(0o660)
                self.assertEqual(prepare_observer(root,root),gid)
                child=reader()
                try:
                    passed=writer("d.execute('INSERT INTO t VALUES(2)');d.commit()")
                    self.assertEqual(passed.returncode,0,passed.stderr)
                finally:child.communicate('\n',timeout=10)
                db=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
                with self.assertRaises(sqlite3.OperationalError):db.execute('INSERT INTO t VALUES(3)')
                db.close()
                db=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
                self.assertEqual(db.execute('SELECT n FROM t').fetchall(),[(2,)]);db.close()
        finally:os.setegid(initial_group);os.umask(initial_mask)


if __name__=='__main__':unittest.main()
