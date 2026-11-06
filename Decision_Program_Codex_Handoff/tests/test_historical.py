import tempfile
import unittest
from pathlib import Path
from workbench import core, collections

class HistoricalTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_future_or_unknown_observation_defers_before_model_call(self):
        for observed in ('','2025-01-01'):
            source=core.snapshot('source','The rule applies.',observed_at=observed)
            run=core.run('Does the rule apply?',source['id'],as_of='2024-01-01',historical_as_known=True,consent=True)
            self.assertEqual(run['result']['status'],'deferred'); self.assertEqual(run['calls'],[])
            self.assertIn('observation',run['result']['reason'].lower())
    def test_collection_requires_each_observation_to_be_known_in_time(self):
        a=core.snapshot('a','Rule.',observed_at='2023-01-01')
        b=core.snapshot('b','Exception.',observed_at='2025-01-01')
        source=collections.create('collection',[a['id'],b['id']])
        run=core.run('Is there an exception?',source['id'],as_of='2024-01-01',historical_as_known=True,consent=True)
        self.assertEqual(run['result']['status'],'deferred'); self.assertEqual(run['calls'],[])
    def test_as_known_requires_valid_date(self):
        source=core.snapshot('source','Text.',observed_at='2023-01-01')
        run=core.run('Question?',source['id'],historical_as_known=True,consent=True)
        self.assertEqual(run['result']['status'],'failed'); self.assertEqual(run['calls'],[])

class HistoricalDatasetTests(unittest.TestCase):
    def test_dataset_freezes_historical_mode(self):
        from workbench import datasets
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); source=core.snapshot('source','Text.',observed_at='2023-01-01')
                case={'case_id':'one','question':'Question?','snapshot_id':source['id'],'as_of':'2024-01-01','historical_as_known':True}
                data=datasets.freeze('historical',[case])
                self.assertIs(data['cases'][0]['historical_as_known'],True)
                with self.assertRaises(ValueError): datasets.freeze('missing date',[{**case,'as_of':''}])
            finally: core.DATA=old

class HistoricalDatasetRunTests(unittest.TestCase):
    def test_historical_dataset_defers_all_arms_without_provider_calls(self):
        import os
        from unittest.mock import patch
        from workbench import datasets
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); source=core.snapshot('source','Text.',observed_at='2025-01-01')
                dataset=datasets.freeze('historical',[{'case_id':'one','question':'Question?','snapshot_id':source['id'],'as_of':'2024-01-01','historical_as_known':True}])
                with patch.dict(os.environ,{'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/frontier'}):
                    run=datasets.launch(dataset['id'],True,15)
                self.assertEqual(run['status'],'awaiting adjudication')
                records=core.records('runs'); self.assertEqual(len(records),3)
                self.assertTrue(all(r['result']['status']=='deferred' and not r['calls'] for r in records))
            finally: core.DATA=old
