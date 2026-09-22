import tempfile
import sqlite3
import subprocess
import sys
import hashlib
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from research_os.dev_only.evolution_worker.resource_guard import memory_guard as g


class MemoryGuardTests(unittest.TestCase):
    def test_success_requires_real_limit_and_memory_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            status = Path(temp) / 'status'
            status.write_text('VmLck: 40000 kB\nVmSwap: 0 kB\n')
            resource = Mock()
            resource.getrlimit.return_value = (g.CAP, g.CAP)
            libc = Mock(); libc.mlockall.return_value = 0
            self.assertEqual(g.lock_memory(resource, libc, status)['swap_kib'], 0)
            libc.mlockall.assert_called_with(3)
            resource.getrlimit.return_value = (-1, -1)
            with self.assertRaises(RuntimeError): g.lock_memory(resource, libc, status)
            resource.getrlimit.return_value = (g.CAP, g.CAP)
            libc.mlockall.return_value = -1
            with self.assertRaises(RuntimeError): g.lock_memory(resource, libc, status)
            libc.mlockall.return_value = 0
            status.write_text('VmLck: 0 kB\nVmSwap: 1 kB\n')
            with self.assertRaises(RuntimeError): g.lock_memory(resource, libc, status)

    def test_failed_guard_never_reaches_pinned_engine(self):
        with patch.object(g.sys, 'argv', ['guard']), patch.object(g, 'lock_memory', side_effect=RuntimeError('no lock')), patch.object(g.runpy, 'run_path') as run:
            with self.assertRaises(RuntimeError): g.main()
            run.assert_not_called()

    def test_killed_sqlite_writer_recovery_preserves_committed_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            paths = [state / 'queue.sqlite3', state / 'jobs/job/research.sqlite3']
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(path)
                db.execute('CREATE TABLE checkpoint(id INTEGER PRIMARY KEY, value TEXT)')
                db.executemany('INSERT INTO checkpoint VALUES(?,?)', [(i, 'committed' * 200) for i in range(200)])
                db.commit(); db.close()
                code = "import os,sqlite3,sys;d=sqlite3.connect(sys.argv[1]);d.execute('PRAGMA cache_size=1');d.execute('BEGIN IMMEDIATE');d.execute(\"UPDATE checkpoint SET value='uncommitted'\");os._exit(137)"
                result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True)
                self.assertEqual(result.returncode, 137)
            self.assertEqual(len(g.recover_interrupted_sqlite(state)), 2)
            for path in paths:
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM checkpoint WHERE value=?', ('committed' * 200,)).fetchone()[0], 200)
                db.close()

    def test_sealed_database_is_never_opened_for_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp); root = state / 'jobs/sealed';root.mkdir(parents=True)
            (root / 'SEALED.json').write_text('{}')
            (root / 'research.sqlite3').write_bytes(b'immutable-not-a-database')
            (root / 'research.sqlite3-journal').write_bytes(b'x' * 1024)
            before = hashlib.sha256((root / 'research.sqlite3').read_bytes()).hexdigest()
            self.assertEqual(g.recover_interrupted_sqlite(state), [])
            self.assertEqual(before, hashlib.sha256((root / 'research.sqlite3').read_bytes()).hexdigest())


if __name__ == '__main__': unittest.main()
