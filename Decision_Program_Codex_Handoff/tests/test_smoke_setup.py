import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class LocalSmokeSetupTests(unittest.TestCase):
    def test_existing_output_is_rejected_before_optional_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'; path.write_text('preserve')
            script=Path(__file__).resolve().parent.parent/'scripts'/'local_judge_smoke.py'
            result=subprocess.run([sys.executable,'-S',str(script),'--output',str(path)],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('already exists',result.stderr)
            self.assertEqual(path.read_text(),'preserve')
