import unittest
from workbench.local_judge import validate_prediction

class LocalJudgeTests(unittest.TestCase):
    def test_worker_environment_is_recorded_for_single_and_batch_probes(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from workbench import local_judge
        prediction={'decision':{'type':'choice','choice':'true','probabilities':{'true':0.9,'false':0.1}}}
        environment={'python':'3.12.16','packages':{'unsloth':'2026.11.2','mlx':'0.30.0'}}
        response={'prediction':prediction,'input_tokens':12,'elapsed_seconds':0.1,'environment':environment}
        with patch.object(local_judge,'worker_python',return_value='/example/python'), patch.object(local_judge.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(response)+'\n')):
            self.assertEqual(local_judge.probe('source','claim')['worker_environment'],environment)
            self.assertEqual(local_judge.probe_many('source',['claim'])['worker_environment'],environment)
    def test_environment_inspection_rejects_missing_dependencies(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from workbench import local_judge
        environment={'python':'3.12.16','packages':{'unsloth':None,'mlx':None,'transformers':None,'huggingface-hub':None}}
        with patch.object(local_judge,'worker_python',return_value='/example/python'), \
             patch.object(local_judge.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(environment))):
            with self.assertRaisesRegex(ValueError,'missing.*unsloth'):
                local_judge.inspect_worker_environment()
    def test_valid_typed_probabilities_are_retained_without_thresholding(self):
        raw={'decision':{'type':'choice','choice':'true','probabilities':{'true':0.9,'false':0.1}}}
        result=validate_prediction(raw)
        self.assertEqual(result['probabilities']['true'],0.9)
        self.assertNotIn('supported',result)
    def test_malformed_scores_are_rejected(self):
        for probabilities in ({'true':1.1,'false':-0.1},{'true':float('nan'),'false':0.2},{'true':0.5},{'true':0.9,'false':0.9}):
            with self.assertRaises(ValueError): validate_prediction({'decision':{'type':'choice','choice':'true','probabilities':probabilities}})

class LocalPolicyTests(unittest.TestCase):
    def test_support_threshold_is_explicit_and_false_is_unknown(self):
        from workbench.local_judge import support_decision
        with self.assertRaises(ValueError): support_decision({'choice':'true','probabilities':{'true':0.95,'false':0.05}},None)
        with self.assertRaises(ValueError): support_decision({'choice':'true','probabilities':{'true':0.95,'false':0.05}},1.1)
        self.assertEqual(support_decision({'choice':'true','probabilities':{'true':0.95,'false':0.05}},0.9),'supported')
        self.assertEqual(support_decision({'choice':'false','probabilities':{'true':0.01,'false':0.99}},0.9),'unknown')
        self.assertEqual(support_decision({'choice':'true','probabilities':{'true':0.8,'false':0.2}},0.9),'unknown')

class LocalPredicateTests(unittest.TestCase):
    def test_two_sided_support_maps_without_conflating_unknown_and_false(self):
        from workbench.local_judge import combine_support
        self.assertEqual(combine_support('supported','unknown'),'true')
        self.assertEqual(combine_support('unknown','supported'),'false')
        self.assertEqual(combine_support('unknown','unknown'),'unknown')
        self.assertEqual(combine_support('supported','supported'),'conflict')
        with self.assertRaises(ValueError): combine_support('false','unknown')
