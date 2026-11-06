import tempfile
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from workbench import core, datasets


class PracticalComparisonTests(unittest.TestCase):
    def setUp(self):
        environment={'python':'test','packages':{'unsloth':'test','mlx':'test','transformers':'test','huggingface-hub':'test'}}
        environment_patch=patch('workbench.local_judge.inspect_worker_environment',return_value=environment)
        environment_patch.start(); self.addCleanup(environment_patch.stop)
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.source=core.snapshot('Public source','Evidence')
        self.cases=[{'case_id':str(i),'question':'Question?', 'snapshot_id':self.source['id']} for i in range(2)]
        self.dataset=datasets.freeze('development',self.cases)
        self.config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/top','OPENROUTER_WEB_TOOL_BUDGET_USD':'0.01','LOCAL_JUDGE_PYTHON':sys.executable}
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()

    def test_requires_explicit_web_and_cost_acknowledgment(self):
        with patch('workbench.core.config',return_value=self.config):
            for web,ack in ((False,False),(True,False),(False,True)):
                with self.subTest(web=web,ack=ack), self.assertRaisesRegex(ValueError,'authorization'):
                    datasets.prepare(self.dataset['id'],True,30,'local',0.8,'practical',web,accept_unenforced_budget=ack)
        self.assertEqual(core.records('dataset_runs'),[])

    def test_practical_rejects_unverifiable_historical_cutoff(self):
        case={**self.cases[0],'as_of':'2026-01-01','historical_as_known':True}
        dataset=datasets.freeze('historical', [case])
        with patch('workbench.core.config',return_value=self.config), self.assertRaisesRegex(ValueError,'historical'):
            datasets.prepare(dataset['id'],True,15,'local',0.8,'practical',True,accept_unenforced_budget=True)

    def test_overrun_stops_before_the_second_case_and_remains_inspectable(self):
        calls=[]
        def bounded(question,snapshot_id,scope,as_of,arm,consent,**kwargs):
            calls.append(arm)
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':arm,'requested_model':kwargs['model'],
              'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
              'evidence_mode':'lexical','extra_search':True,'request':{'question':question,'snapshot_id':snapshot_id,'scope':scope,'as_of':as_of},
              'result':{'status':'deferred'},'calls':[],'trace':[],'elapsed_seconds':0})
        def web(question,scope,as_of,**kwargs):
            calls.append('web'); self.assertEqual(kwargs['model'],'test/top'); self.assertEqual(kwargs['tool_budget_override'],0.01)
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':'frontier-web','requested_model':kwargs['model'],'requested_tool_budget_usd':kwargs['tool_budget_override'],
              'request':{'question':question,'scope':scope,'as_of':as_of},'result':{'status':'failed','search_requests':2},
              'calls':[],'trace':[],'elapsed_seconds':0})
        with patch('workbench.core.config',return_value=self.config), patch('workbench.core.run',side_effect=bounded), patch('workbench.web_research.run',side_effect=web):
            run=datasets.prepare(self.dataset['id'],True,30,'local',0.8,'practical',True,accept_unenforced_budget=True)
            with self.assertRaisesRegex(ValueError,'inspect saved'):
                datasets.resume(run['id'],True)
            self.assertEqual(calls,['fresh','direct','web'])
            self.assertEqual(len(datasets.status(run['id'])['receipts']),1)
            with self.assertRaisesRegex(ValueError,'inspect saved'):
                datasets.resume(run['id'],True)
            self.assertEqual(calls,['fresh','direct','web'])

    def test_practical_case_reaches_blinded_review_and_score(self):
        from workbench import archive, compare
        dataset=datasets.freeze('one case',self.cases[:1])
        def bounded(question,snapshot_id,scope,as_of,arm,consent,**kwargs):
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':arm,'requested_model':kwargs['model'],
                'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
                'evidence_mode':'lexical','extra_search':True,'request':{'question':question,'snapshot_id':snapshot_id,'scope':scope,'as_of':as_of},
                'result':{'status':'deferred'},'calls':[{'usage':{'cost':0.002}}],'trace':[],'elapsed_seconds':0})
        def web(question,scope,as_of,**kwargs):
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':'frontier-web','requested_model':kwargs['model'],'requested_tool_budget_usd':kwargs['tool_budget_override'],
                'request':{'question':question,'scope':scope,'as_of':as_of},'result':{'status':'decided','answer':'Answer','search_requests':1,'citations':[{'url':'https://example.com'}]},
                'calls':[{'usage':{'cost':0.01,'server_tool_use':{'web_search_requests':1,'tool_calls_executed':1}}}],'trace':[],'elapsed_seconds':1})
        with patch('workbench.core.config',return_value=self.config), patch('workbench.core.run',side_effect=bounded), patch('workbench.web_research.run',side_effect=web):
            result=datasets.launch(dataset['id'],True,15,'local',0.8,'practical',True,accept_unenforced_budget=True)
            comparison_id=result['receipts'][0]['comparison_id']; blind=compare.blind(comparison_id)
            self.assertEqual(blind['items'],[])
            compare.assess_case(comparison_id,'Developer','answerable','Synthetic test','Evidence')
            blind=compare.blind(comparison_id)
            self.assertEqual(len(blind['items']),3)
            self.assertTrue(all('arm' not in item for item in blind['items']))
            for item in blind['items']:
                compare.adjudicate(comparison_id,item['review_id'],'Developer','unresolved','unclear','Synthetic test')
            score=datasets.score(result['id'])
            self.assertEqual(score['stage'],'practical')
            self.assertEqual(score['arms']['frontier']['assigned'],1)
            self.assertEqual(score['requested_web_tool_budget_usd'],0.01)
            self.assertEqual(score['arms']['frontier']['web_search_requests'],1)
            self.assertEqual(score['arms']['frontier']['server_tool_calls_executed'],1)
            self.assertIn('Server-tool executions: 1',datasets.render_markdown(score))
            self.assertIsNone(score['arms']['fresh']['web_search_requests'])
            self.assertIsNone(score['arms']['fresh']['observed_web_search_requests'])
            self.assertIn('not a guaranteed',datasets.render_markdown(score))
            bundle=archive.export_dataset(result['id'])
            replay=archive.verify_dataset(bundle)
            self.assertTrue(replay['matches_exported_score'])
            self.assertEqual(replay['score']['cases'][0]['rows'][-1]['web_search_requests'],1)

    def test_real_web_adapter_records_overrun_and_stops_dataset(self):
        import io, json
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,request,timeout):
                self.body=json.loads(request.data)
                return Response(json.dumps({'model':'routed/model','choices':[{'message':{'content':'Answer','annotations':[
                    {'type':'url_citation','url_citation':{'url':'https://example.com'}}]}}],
                    'usage':{'cost':0.02,'server_tool_use':{'web_search_requests':1,'tool_calls_executed':2}}}).encode())
        opener=Opener()
        def bounded(question,snapshot_id,scope,as_of,arm,consent,**kwargs):
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':arm,'requested_model':kwargs['model'],
              'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
              'evidence_mode':'lexical','extra_search':True,'request':{'question':question,'snapshot_id':snapshot_id,'scope':scope,'as_of':as_of},
              'result':{'status':'deferred'},'calls':[],'trace':[],'elapsed_seconds':0})
        config={**self.config,'OPENROUTER_API_KEY':'dummy'}
        with patch('workbench.core.config',return_value=config), patch('workbench.core.run',side_effect=bounded), \
             patch('workbench.web_research.urllib.request.build_opener',return_value=opener):
            run=datasets.prepare(self.dataset['id'],True,30,'local',0.8,'practical',True,accept_unenforced_budget=True)
            with self.assertRaisesRegex(ValueError,'inspect saved'): datasets.resume(run['id'],True)
            receipt=datasets.status(run['id'])['receipts'][0]
            comp=core.load('comparisons',receipt['comparison_id'])
            arm=core.load('runs',next(x['run_id'] for x in comp['items'] if x['arm']=='frontier'))
            self.assertEqual(arm['result']['status'],'failed')
            self.assertEqual(arm['result']['search_requests'],1)
            self.assertEqual(arm['result']['tool_calls_executed'],2)
            self.assertEqual(arm['calls'][0]['usage']['cost'],0.02)
            self.assertEqual(opener.body['model'],'test/top')
            self.assertNotIn(self.source['text'],json.dumps(opener.body))
            with self.assertRaisesRegex(ValueError,'inspect saved'): datasets.resume(run['id'],True)
            self.assertEqual(len(datasets.status(run['id'])['receipts']),1)
