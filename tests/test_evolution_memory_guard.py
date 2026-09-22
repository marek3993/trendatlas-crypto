import tempfile
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


if __name__ == '__main__': unittest.main()
