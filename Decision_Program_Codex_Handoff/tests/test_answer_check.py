import unittest
from workbench import core

class AnswerCheckTests(unittest.TestCase):
    def test_multiple_individual_passages_can_support_multi_source_answer(self):
        from workbench import collections
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                a=core.snapshot('a','Alpha supports the first claim.')
                b=core.snapshot('b','Beta supports the second claim.')
                source=collections.create('collection',[a['id'],b['id']])
                check=core.validate_answer_check({'verdict':'supported','quotes':['Alpha supports the first claim.','Beta supports the second claim.']},source)
                self.assertEqual([ref['source_id'] for ref in check['source_refs']],[a['id'],b['id']])
                self.assertEqual(core.apply_answer_check({'status':'decided','answer':'Both'},check,source['text'])['status'],'decided')
                with self.assertRaises(ValueError):
                    core.validate_answer_check({'verdict':'supported','quotes':['Alpha supports the first claim.','fabricated']},source)
                with self.assertRaises(ValueError):
                    core.validate_answer_check({'verdict':'supported','quotes':[source['text']]},source)
            finally: core.DATA=old
    def test_disagreement_or_uncertainty_defers_the_candidate(self):
        candidate={'status':'decided','answer':'A permit is required.'}
        for verdict in ('contradicted','uncertain'):
            result=core.apply_answer_check(candidate,{'verdict':verdict,'quote':'','reason':'Not supported'},'source')
            self.assertEqual(result['status'],'deferred')
            self.assertIsNone(result['answer'])
    def test_agreement_needs_an_exact_quote(self):
        candidate={'status':'decided','answer':'No permit is required.'}
        for quote in ('','fabricated'):
            result=core.apply_answer_check(candidate,{'verdict':'supported','quote':quote,'reason':'yes'},'The event is exempt.')
            self.assertEqual(result['status'],'deferred')
        result=core.apply_answer_check(candidate,{'verdict':'supported','quote':'The event is exempt.','reason':'yes'},'The event is exempt.')
        self.assertEqual(result,candidate)
    def test_invalid_check_is_not_a_positive_result(self):
        result=core.apply_answer_check({'status':'decided','answer':'Yes'}, {'verdict':'other'}, 'source')
        self.assertEqual(result['status'],'deferred')
