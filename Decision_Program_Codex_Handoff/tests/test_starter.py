import tempfile
import unittest
from pathlib import Path
from workbench import core, datasets

class StarterTests(unittest.TestCase):
    def test_development_references_are_exact_spans_and_match_question_ids(self):
        import json
        folder=core.ROOT/'starter_corpus'
        questions=json.loads((folder/'development_questions.json').read_text())
        refs=json.loads((folder/'development_references.json').read_text())['cases']
        self.assertEqual({x['case_id'] for x in questions},{x['case_id'] for x in refs})
        for case in refs:
            for item in case['evidence']:
                self.assertIn(item['quote'],(folder/item['source']).read_text())
    def test_source_hash_failure_does_not_create_records(self):
        import shutil
        from unittest.mock import patch
        from workbench import starter
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); shutil.copytree(core.ROOT/'starter_corpus',root/'starter_corpus')
            (root/'starter_corpus'/'python-3.12.10-token.rst').write_text('tampered')
            old=core.DATA
            try:
                core.DATA=root/'data'
                with patch.object(core,'ROOT',root):
                    with self.assertRaisesRegex(ValueError,'hash mismatch'): starter.initialize_development()
                self.assertEqual(core.records('snapshots'),[])
            finally: core.DATA=old
    def test_initialization_freezes_sources_and_questions_without_reference_labels(self):
        from workbench import starter
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                result=starter.initialize_development()
                dataset=datasets.load_frozen(result['dataset_id'])
                self.assertGreaterEqual(len(dataset['cases']),4)
                self.assertTrue(all(set(c)<= {'case_id','question','snapshot_id','scope','as_of','snapshot_sha256','snapshot_metadata_sha256'} for c in dataset['cases']))
                self.assertNotIn('expected_answer',str(dataset))
                self.assertEqual(core.load('snapshots',result['collection_id'])['scope'],'Python 3.12.10')
                for case in dataset['cases']: datasets.verify_case_source(case)
            finally: core.DATA=old
