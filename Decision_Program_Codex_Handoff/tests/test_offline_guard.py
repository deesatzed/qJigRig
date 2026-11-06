import subprocess
import sys
import unittest
from pathlib import Path


class OfflineGuardTests(unittest.TestCase):
    def test_runner_blocks_external_connections_before_dns(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([sys.executable, str(root / 'scripts' / 'offline_tests.py'), '--probe'],
                                cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('external access blocked', result.stdout)
