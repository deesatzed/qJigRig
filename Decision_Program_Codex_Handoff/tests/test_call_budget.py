import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from workbench import core, datasets


class CallBudgetTests(unittest.TestCase):
    def test_shared_evidence_worst_case_fits_reserved_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = core.DATA
            try:
                core.DATA = Path(tmp)
                source = core.snapshot('Synthetic', 'Every item is ready.')
                dataset = datasets.freeze('Budget', [{'case_id':'case','question':'Are all items ready?','snapshot_id':source['id']}])
                predicates = [{'id':f'p{i}','question':f'Is item {i} ready?', 'evidence_requirement':'Readiness'} for i in range(6)]
                plan = {'predicates':predicates,'expression':{'op':'and','args':[{'ref':p['id']} for p in predicates]},
                        'true_answer':'Yes','false_answer':'No','false_status':'decided','ambiguity':''}
                seen = Counter()
                def responder(model, prompt, payload, max_tokens=1200):
                    seen[prompt] += 1
                    if prompt == core.PLAN_PROMPT: result = 'invalid json'
                    elif prompt == core.PLAN_PROMPT + core.REPAIR_SUFFIX: result = json.dumps(plan)
                    elif prompt == core.JUDGE_PROMPT:
                        result = json.dumps({'outcome':'true','quote':'fabricated' if seen[prompt] == 1 else 'Every item is ready.'})
                    elif prompt == core.JUDGE_REPAIR_PROMPT: result = json.dumps({'outcome':'true','quote':'Every item is ready.'})
                    elif prompt == core.ANSWER_CHECK_PROMPT: result = json.dumps({'verdict':'supported','quotes':['fabricated']})
                    elif prompt == core.ANSWER_CHECK_REPAIR_PROMPT: result = json.dumps({'verdict':'supported','quotes':['Every item is ready.']})
                    elif prompt == core.DIRECT_PROMPT: result = json.dumps({'status':'decided','answer':'Yes','quotes':['fabricated']})
                    elif prompt == core.DIRECT_REPAIR_PROMPT: result = json.dumps({'status':'decided','answer':'Yes','quotes':['Every item is ready.']})
                    else: raise AssertionError('Unexpected provider call')
                    return result, {'usage':{}}
                config = {'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/frontier'}
                with patch('workbench.core.config',return_value=config), patch('workbench.core.call_model',side_effect=responder):
                    run = datasets.launch(dataset['id'],True,15,targeted=False)
                self.assertEqual(run['status'],'awaiting adjudication')
                self.assertEqual(sum(seen.values()),15)
                self.assertEqual(datasets.MAX_CALLS_PER_CASE,15)
                comparison=core.load('comparisons',run['receipts'][0]['comparison_id'])
                self.assertEqual([core.load('runs',item['run_id'])['result']['status'] for item in comparison['items']],['decided']*3)
            finally:
                core.DATA = old

    def test_shared_corpus_search_and_repairs_fit_reserved_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = core.DATA
            try:
                core.DATA = Path(tmp)
                source = core.snapshot('Synthetic', 'Every item is ready.')
                dataset = datasets.freeze('Budget', [{'case_id':'case','question':'Are all items ready?','snapshot_id':source['id']}])
                predicate={'id':'p','question':'Are items ready?','evidence_requirement':'Readiness',
                           'positive_claim':'All items are ready.','negative_claim':'Not all items are ready.'}
                plan={'predicates':[predicate], 'expression':{'ref':'p'},'true_answer':'Yes','false_answer':'No','false_status':'decided','ambiguity':''}
                seen=Counter()
                def responder(model,prompt,payload,max_tokens=1200):
                    seen[prompt]+=1
                    if prompt==core.PLAN_PROMPT: result='invalid json'
                    elif prompt==core.PLAN_PROMPT+core.REPAIR_SUFFIX: result=json.dumps(plan)
                    elif prompt==core.SEARCH_PROMPT: result=json.dumps({'query':'','reason':'No follow-up'})
                    elif prompt==core.DIRECT_PROMPT: result=json.dumps({'status':'decided','answer':'Yes','quotes':['fabricated']})
                    elif prompt==core.DIRECT_REPAIR_PROMPT: result=json.dumps({'status':'decided','answer':'Yes','quotes':['Every item is ready.']})
                    else: raise AssertionError('Unexpected provider call')
                    return result,{'usage':{}}
                trace=[{'predicate':predicate,'outcome':'true','evidence_spans':[],'retrieval_rounds':[]}]
                environment={'python':'test','packages':{}}
                judge={'choice':'true','probabilities':{'true':1.0,'false':0.0},'worker_environment':environment}
                import sys
                config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/frontier','LOCAL_JUDGE_PYTHON':sys.executable}
                with patch('workbench.core.config',return_value=config), patch('workbench.core.call_model',side_effect=responder), \
                     patch('workbench.local_judge.inspect_worker_environment',return_value=environment), \
                     patch('workbench.local_retrieval.evaluate',return_value=(trace,[{'worker_environment':environment}])), patch('workbench.local_judge.probe',return_value=judge):
                    run=datasets.launch(dataset['id'],True,15,judge_backend='local',local_threshold=0.8,stage='shared-corpus')
                self.assertEqual(run['status'],'awaiting adjudication')
                self.assertEqual(sum(seen.values()),8)
                self.assertLessEqual(sum(seen.values()),datasets.MAX_CALLS_PER_CASE)
                comparison=core.load('comparisons',run['receipts'][0]['comparison_id'])
                self.assertEqual([core.load('runs',item['run_id'])['result']['status'] for item in comparison['items']],['decided']*3)
            finally:
                core.DATA=old
