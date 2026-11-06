import unittest
from workbench import core

class StoppingTests(unittest.TestCase):
    def test_relevance_keeps_material_unknowns_and_rejects_invariants(self):
        expr={'op':'or','args':[{'ref':'a'},{'ref':'b'}]}
        self.assertTrue(core.predicate_relevant(expr,['a','b'],{'a':False},'b'))
        self.assertFalse(core.predicate_relevant(expr,['a','b'],{'a':True},'b'))
        tautology={'op':'or','args':[{'ref':'b'},{'op':'not','args':[{'ref':'b'}]}]}
        self.assertFalse(core.predicate_relevant(tautology,['b'],{},'b'))

    def test_followup_selection_has_exhaustive_control(self):
        from workbench.local_retrieval import followup_selection
        expr={'op':'or','args':[{'ref':'a'},{'ref':'b'}]}
        state=[{'predicate':{'id':'a'},'outcome':'true'},{'predicate':{'id':'b'},'outcome':'unknown'}]
        self.assertEqual(followup_selection(expr,state,True),[])
        self.assertEqual(followup_selection(expr,state,False),[1])

    def test_no_extra_search_retains_unknown_without_second_round(self):
        from unittest.mock import patch
        from workbench.local_retrieval import evaluate
        predicate={'id':'p','question':'park event permit','evidence_requirement':'park permit',
                   'positive_claim':'A permit is required.','negative_claim':'A permit is not required.'}
        uncertain={'choice':'false','probabilities':{'true':0.1,'false':0.9}}
        with patch('workbench.local_retrieval.probe_pairs', return_value={'results':[uncertain,uncertain]}):
            trace,_=evaluate('Park event permit information.',[predicate],0.8,{'ref':'p'},extra_search=False)
        self.assertEqual(trace[0]['outcome'],'unknown')
        self.assertEqual(len(trace[0]['retrieval_rounds']),1)
        self.assertEqual(trace[0]['followup_status'],'disabled')
    def test_exception_remains_material_after_ordinary_false(self):
        expr={'op':'or','args':[{'ref':'ordinary'},{'ref':'exception'}]}
        self.assertIsNone(core.stable_outcome(expr,['ordinary','exception'],{'ordinary':False}))
        self.assertTrue(core.stable_outcome(expr,['ordinary','exception'],{'ordinary':False,'exception':True}))
    def test_decisive_false_allows_skip_under_and(self):
        expr={'op':'and','args':[{'ref':'first'},{'ref':'second'}]}
        self.assertIs(core.stable_outcome(expr,['first','second'],{'first':False}),False)
    def test_unknown_and_conflict_never_assume_a_value(self):
        expr={'op':'and','args':[{'ref':'first'},{'ref':'second'}]}
        self.assertIsNone(core.stable_outcome(expr,['first','second'],{'first':True,'second':None}))
    def test_repeated_reference_completions_preserve_identity(self):
        expr={'op':'or','args':[{'ref':'p'},{'op':'not','args':[{'ref':'p'}]}]}
        self.assertIs(core.stable_outcome(expr,['p'],{}),True)

class WorkAccountingTests(unittest.TestCase):
    def test_missing_local_evidence_is_not_counted_as_model_evaluation(self):
        from workbench import compare
        run={'answer_check_backend':'local','trace':[{'outcome':'unknown','positive_support':None},{'outcome':'true','positive_support':{'choice':'true'}}]}
        self.assertEqual(compare.predicate_work(run),{'evaluated':1,'skipped':0,'unresolved_without_evaluation':1})
