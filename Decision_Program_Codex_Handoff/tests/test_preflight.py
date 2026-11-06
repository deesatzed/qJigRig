import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workbench import preflight


class PreflightTests(unittest.TestCase):
    def test_missing_judge_dependencies_fail_before_planner(self):
        from workbench import core
        with tempfile.TemporaryDirectory() as temp:
            old=core.DATA; core.DATA=Path(temp)
            try:
                source=core.snapshot('source','Evidence')
                with patch('workbench.local_judge.inspect_worker_environment',side_effect=ValueError('Local judge dependencies missing: unsloth')), \
                     patch('workbench.core.call_model',side_effect=AssertionError('provider must not be called')):
                    run=core.run('Question?',source['id'],consent=True,judge_backend='local',local_threshold=0.8)
                self.assertEqual(run['result']['status'],'failed')
                self.assertIn('dependencies missing',run['result']['reason'])
                self.assertEqual(run['calls'],[])
            finally: core.DATA=old
    def test_missing_judge_worker_fails_before_planner_call(self):
        from workbench import core, datasets
        old=core.DATA
        with tempfile.TemporaryDirectory() as temp:
            try:
                core.DATA=Path(temp)
                source=core.snapshot('source','Evidence')
                dataset=datasets.freeze('test',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
                config={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/small',
                        'OPENROUTER_TOP_MODEL':'test/top','LOCAL_JUDGE_PYTHON':'/not/a/real/python'}
                with patch('workbench.core.config',return_value=config), \
                     patch('workbench.core.call_model',side_effect=AssertionError('provider must not be called')):
                    run=core.run('Question?',source['id'],consent=True,judge_backend='local',local_threshold=0.8)
                    self.assertIn('judge python',run['result']['reason'].lower())
                    self.assertEqual(run['calls'],[])
                    with self.assertRaisesRegex(ValueError,'judge Python'):
                        datasets.prepare(dataset['id'],True,15,'local',0.8,'shared-corpus')
                    self.assertEqual(core.records('dataset_runs'),[])
            finally: core.DATA=old
    def test_checks_configuration_without_disclosing_values_or_connecting(self):
        with tempfile.TemporaryDirectory() as temp:
            python=Path(temp)/'python'; python.write_text('#!/bin/sh\n'); python.chmod(0o700)
            config={'OPENROUTER_API_KEY':'test-secret-must-not-appear',
                    'OPENROUTER_PLANNER_MODEL':'model/small','OPENROUTER_TOP_MODEL':'model/top',
                    'LOCAL_JUDGE_PYTHON':str(python),'OPENROUTER_WEB_TOOL_BUDGET_USD':'0.01'}
            with patch('workbench.core.config',return_value=config), \
                 patch('socket.socket.connect',side_effect=AssertionError('no network')):
                result=preflight.inspect()
            self.assertTrue(result['api_key_present'])
            self.assertTrue(result['local_judge_python_executable'])
            self.assertFalse(result['local_judge_dependencies_present'])
            self.assertTrue(result['web_tool_budget_configured'])
            self.assertNotIn(config['OPENROUTER_API_KEY'],json.dumps(result))
            self.assertNotIn(str(python),json.dumps(result))
    def test_setup_reports_local_dependency_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            python=Path(temp)/'python'; python.write_text('#!/bin/sh\n'); python.chmod(0o700)
            environment={'python':'3.12','packages':{'unsloth':'1','mlx':'1','transformers':'1','huggingface-hub':'1'}}
            with patch('workbench.core.config',return_value={'LOCAL_JUDGE_PYTHON':str(python)}), \
                 patch('workbench.local_judge.inspect_worker_environment',return_value=environment):
                result=preflight.inspect()
            self.assertTrue(result['local_judge_dependencies_present'])

    def test_rejects_missing_or_invalid_local_configuration(self):
        with patch('workbench.core.config',return_value={'OPENROUTER_TOP_MODEL':'model:online',
                   'OPENROUTER_WEB_TOOL_BUDGET_USD':'nan','BASE_URL':'http://example.com',
                   'LOCAL_JUDGE_PYTHON':'/not/a/real/python'}):
            result=preflight.inspect()
        for field in ('api_key_present','small_model_configured','frontier_model_configured',
                      'provider_endpoint_supported','local_judge_python_executable','web_tool_budget_configured'):
            self.assertFalse(result[field],field)
