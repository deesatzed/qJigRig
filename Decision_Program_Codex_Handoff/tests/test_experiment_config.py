import unittest
from workbench import experiments, core

class ExperimentConfigTests(unittest.TestCase):
    def test_frozen_config_contains_no_secrets_and_rejects_online_models(self):
        c=experiments.freeze_config({'OPENROUTER_PLANNER_MODEL':'vendor/small','OPENROUTER_TOP_MODEL':'vendor/frontier','OPENROUTER_API_KEY':'secret'})
        self.assertNotIn('secret',str(c)); self.assertEqual(c['small_model'],'vendor/small')
        self.assertIn('planner',c['prompt_hashes'])
        with self.assertRaises(ValueError): experiments.freeze_config({'OPENROUTER_PLANNER_MODEL':'vendor/small:online','OPENROUTER_TOP_MODEL':'vendor/frontier'})
    def test_bounded_request_explicitly_disables_web_plugin(self):
        body=core.chat_body('vendor/small','system',{'question':'q'},100)
        self.assertIn({'id':'web','enabled':False},body['plugins'])
        self.assertNotIn('tools',body)

class SourceBoundaryTests(unittest.TestCase):
    def test_bounded_response_rejects_observed_web_access(self):
        with self.assertRaises(ValueError): core.validate_bounded_response({'choices':[{'message':{}}], 'usage':{'server_tool_use_details':{'web_search_requests':1}}})
        with self.assertRaises(ValueError): core.validate_bounded_response({'choices':[{'message':{}}], 'usage':{'server_tool_use':{'web_search_requests':1}}})
        with self.assertRaises(ValueError): core.validate_bounded_response({'choices':[{'message':{'annotations':[{'type':'url_citation'}]}}]})
        core.validate_bounded_response({'choices':[{'message':{'content':'ok'}}], 'usage':{}})

class DriftTests(unittest.TestCase):
    def test_runtime_drift_or_missing_fingerprint_is_rejected(self):
        frozen=experiments.freeze_config({'OPENROUTER_PLANNER_MODEL':'vendor/small','OPENROUTER_TOP_MODEL':'vendor/frontier'})
        self.assertIn('runtime_hashes',frozen)
        self.assertIn('verify_run.py',frozen['runtime_hashes'])
        frozen['runtime_hashes']['core.py']='changed'
        with self.assertRaisesRegex(ValueError,'runtime'): experiments.validate_config(frozen)
        del frozen['runtime_hashes']
        with self.assertRaisesRegex(ValueError,'runtime'): experiments.validate_config(frozen)
    def test_prompt_drift_is_rejected(self):
        frozen=experiments.freeze_config({'OPENROUTER_PLANNER_MODEL':'vendor/small','OPENROUTER_TOP_MODEL':'vendor/frontier'})
        self.assertEqual(experiments.validate_config(frozen),frozen)
        frozen['prompt_hashes']['planner']='changed'
        with self.assertRaisesRegex(ValueError,'changed'): experiments.validate_config(frozen)
