import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from workbench import core, datasets

class BackgroundDatasetTests(unittest.TestCase):
    def test_worker_error_is_visible_without_retry(self):
        from workbench import jobs
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA; core.DATA=Path(tmp)
            try:
                source=core.snapshot('test','Evidence')
                dataset=datasets.freeze('test',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
                with patch('workbench.datasets.resume',side_effect=ValueError('uncertain in-flight case')) as resume, patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}):
                    run=jobs.start_dataset(dataset['id'],True,15)
                    jobs.wait(run['id'],3)
                self.assertEqual(jobs.status(run['id'])['state'],'error')
                self.assertIn('uncertain',jobs.status(run['id'])['error'])
                self.assertEqual(resume.call_count,1)
            finally: core.DATA=old
    def test_start_returns_saved_id_while_work_is_running(self):
        from workbench import jobs
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA; core.DATA=Path(tmp)
            entered=threading.Event(); release=threading.Event()
            try:
                source=core.snapshot('test','public test evidence')
                dataset=datasets.freeze('test',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
                def slow_resume(run_id,consent=False):
                    entered.set(); release.wait(3)
                with patch('workbench.datasets.resume',side_effect=slow_resume), patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}):
                    run=jobs.start_dataset(dataset['id'],True,15)
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(core.load('dataset_runs',run['id'])['dataset_id'],dataset['id'])
                    self.assertEqual(jobs.status(run['id'])['state'],'running')
                    release.set()
                    jobs.wait(run['id'],3)
                self.assertEqual(jobs.status(run['id'])['state'],'finished')
            finally:
                release.set(); core.DATA=old
