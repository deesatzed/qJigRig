import os
import subprocess
import sys
import tempfile
import unittest
import json
import hashlib
from pathlib import Path


class CliErrorTests(unittest.TestCase):
    def test_import_and_derive_preserve_utf8_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={**os.environ,'WORKBENCH_DATA':str(Path(tmp)/'data')}
            source=Path(tmp)/'source.txt'; original='café\r\nsecond line\r\n'; source.write_bytes(original.encode('utf-8'))
            def run(*args):
                return subprocess.run([sys.executable,'-m','workbench',*args],env=env,capture_output=True,text=True,check=True)
            imported=json.loads(run('import',str(source)).stdout)
            self.assertEqual(imported['text'],original)
            self.assertEqual(imported['sha256'],hashlib.sha256(original.encode('utf-8')).hexdigest())
            changed='café\r\nchanged line\r\n'; source.write_bytes(changed.encode('utf-8'))
            derived=json.loads(run('derive','--parent',imported['id'],'--file',str(source),'--title','changed','--reason','test').stdout)
            self.assertEqual(derived['text'],changed)
            self.assertEqual(derived['sha256'],hashlib.sha256(changed.encode('utf-8')).hexdigest())
    def test_missing_run_reports_expected_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([sys.executable,'-m','workbench','dataset-score','0'*32],
                                  env={**os.environ,'WORKBENCH_DATA':tmp},capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('error:',result.stderr.lower())
        self.assertNotIn('Traceback',result.stderr)
        self.assertEqual(result.stdout,'')
