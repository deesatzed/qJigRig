import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workbench import core


class RunJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.source=core.snapshot('source','Public synthetic fact.')
        self.config={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/model'}
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()

    def test_interruption_leaves_call_intent_without_receipt_or_run(self):
        with patch('workbench.core.config',return_value=self.config), \
             patch('workbench.core.call_model',side_effect=SystemExit('interrupted')):
            with self.assertRaises(SystemExit):
                core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
        intents=core.records('run_intents'); calls=core.records('run_call_intents')
        self.assertEqual(len(intents),1); self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['run_id'],intents[0]['id'])
        self.assertEqual(core.records('run_call_receipts'),[])
        self.assertEqual(core.records('runs'),[])

    def test_provider_failure_receipt_preserves_observed_cost(self):
        error=core.ProviderError('provider failed',{'model':'test/model','status':'failed','usage':{'cost':0.01}})
        with patch('workbench.core.config',return_value=self.config), \
             patch('workbench.core.call_model',side_effect=error):
            run=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
        receipt=core.records('run_call_receipts')[0]
        self.assertEqual(receipt['run_id'],run['id'])
        self.assertEqual(receipt['metadata']['usage']['cost'],0.01)
        self.assertEqual(run['result']['status'],'failed')
    def test_http_error_usage_is_preserved_in_bounded_and_web_receipts(self):
        import io, json, urllib.error
        from workbench import web_research
        class Opener:
            def open(self,*args,**kwargs):
                body=json.dumps({'error':{'message':'request failed'},'usage':{'cost':0.02}}).encode()
                raise urllib.error.HTTPError('https://openrouter.ai/',429,'error',{},io.BytesIO(body))
        cfg={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/model','OPENROUTER_TOP_MODEL':'test/model'}
        with patch('workbench.core.config',return_value=cfg), patch('urllib.request.build_opener',return_value=Opener()):
            bounded=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
            web=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
        for run in (bounded,web):
            self.assertEqual(run['result']['status'],'failed')
            self.assertEqual(run['calls'][0]['usage']['cost'],0.02)
            self.assertEqual(run['calls'][0]['cost_status'],'provider reported')
            receipt=next(x for x in core.records('run_call_receipts') if x['run_id']==run['id'])
            self.assertEqual(receipt['metadata']['usage']['cost'],0.02)
    def test_http_error_missing_or_malformed_usage_remains_unobserved(self):
        import io, urllib.error
        from workbench import web_research
        cfg={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/model','OPENROUTER_TOP_MODEL':'test/model'}
        for body in (b'not json',b'{"error":{"message":"failed"}}',b'{"usage":"invalid"}',b'{"usage":{"cost":NaN}}',b'{"usage":{"details":{"cost":1e999}}}'):
            class Opener:
                def open(self,*args,**kwargs):
                    raise urllib.error.HTTPError('https://openrouter.ai/',429,'error',{},io.BytesIO(body))
            with self.subTest(body=body), patch('workbench.core.config',return_value=cfg), patch('urllib.request.build_opener',return_value=Opener()):
                bounded=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
                web=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
            for run in (bounded,web):
                self.assertEqual(run['result']['status'],'failed')
                self.assertIsNone(run['calls'][0]['usage'])
                self.assertEqual(run['calls'][0]['cost_status'],'unobserved')
    def test_invalid_http_error_cost_is_not_marked_reported(self):
        import io, json, urllib.error
        from workbench import web_research
        cfg={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/model','OPENROUTER_TOP_MODEL':'test/model'}
        for value in ('0.02',True,-1):
            class Opener:
                def open(self,*args,**kwargs):
                    raise urllib.error.HTTPError('https://openrouter.ai/',429,'error',{},io.BytesIO(json.dumps({'usage':{'cost':value}}).encode()))
            with self.subTest(value=value), patch('workbench.core.config',return_value=cfg), patch('urllib.request.build_opener',return_value=Opener()):
                bounded=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
                web=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
            for run in (bounded,web):
                self.assertEqual(run['calls'][0]['cost_status'],'unobserved')
                self.assertEqual(run['calls'][0]['usage']['cost'],value)
    def test_nonfinite_usage_in_success_response_is_rejected_and_recorded(self):
        import io
        from workbench import web_research
        class Reply(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,*args,**kwargs):
                return Reply(b'{"choices":[{"finish_reason":"stop","message":{"content":"answer"}}],"usage":{"cost":1e999}}')
        cfg={'OPENROUTER_API_KEY':'dummy','OPENROUTER_PLANNER_MODEL':'test/model','OPENROUTER_TOP_MODEL':'test/model'}
        with patch('workbench.core.config',return_value=cfg), patch('urllib.request.build_opener',return_value=Opener()):
            bounded=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
            web=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
        for run in (bounded,web):
            self.assertEqual(run['result']['status'],'failed')
            self.assertIsNone(run['calls'][0]['usage'])
            self.assertEqual(run['calls'][0]['cost_status'],'unobserved')
            self.assertEqual(core.load('runs',run['id'])['result']['status'],'failed')
    def test_web_interruption_leaves_intent_before_transport(self):
        from workbench import web_research
        class Opener:
            def open(self,*args,**kwargs): raise SystemExit('interrupted')
        config={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'test/model'}
        with patch('workbench.core.config',return_value=config), \
             patch('workbench.web_research.urllib.request.build_opener',return_value=Opener()):
            with self.assertRaises(SystemExit):
                web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
        intents=core.records('run_intents'); calls=core.records('run_call_intents')
        self.assertEqual(len(intents),1); self.assertEqual(intents[0]['mode'],'frontier-web')
        self.assertEqual(calls[0]['run_id'],intents[0]['id'])
        self.assertEqual(core.records('run_call_receipts'),[])
        self.assertEqual(core.records('runs'),[])
    def test_receipt_write_failure_retains_reported_call_and_response(self):
        import json
        original_save=core.save
        def fail_receipt(kind,obj):
            if kind=='run_call_receipts': raise OSError('Receipt storage unavailable')
            return original_save(kind,obj)
        answer=json.dumps({'status':'decided','answer':'Yes','quotes':['Public synthetic fact.']})
        metadata={'model':'test/model','usage':{'cost':0.01}}
        with patch('workbench.core.config',return_value=self.config), \
             patch('workbench.core.call_model',return_value=(answer,metadata)), \
             patch('workbench.core.save',side_effect=fail_receipt):
            run=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'failed')
        self.assertEqual(run['calls'][0]['usage']['cost'],0.01)
        self.assertEqual(run['model_responses'][0]['text'],answer)
        self.assertEqual(len(core.records('run_call_intents')),1)
        self.assertEqual(core.records('run_call_receipts'),[])
    def test_receipt_write_failure_also_retains_provider_error_cost(self):
        original_save=core.save
        def fail_receipt(kind,obj):
            if kind=='run_call_receipts': raise OSError('Receipt storage unavailable')
            return original_save(kind,obj)
        error=core.ProviderError('provider failed',{'model':'test/model','status':'failed','usage':{'cost':0.02}})
        with patch('workbench.core.config',return_value=self.config), \
             patch('workbench.core.call_model',side_effect=error), patch('workbench.core.save',side_effect=fail_receipt):
            run=core.run('Is the fact present?',self.source['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'failed')
        self.assertEqual(run['calls'][0]['usage']['cost'],0.02)
    def test_web_receipt_write_failure_retains_returned_cost(self):
        import io
        from workbench import web_research
        class Reply(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,*args,**kwargs):
                return Reply(b'{"choices":[{"finish_reason":"stop","message":{"content":"Answer","annotations":[{"type":"url_citation","url_citation":{"url":"https://example.com"}}]}}],"usage":{"cost":0.03,"server_tool_use":{"web_search_requests":1}}}')
        original_save=core.save
        def fail_receipt(kind,obj):
            if kind=='run_call_receipts': raise OSError('Receipt storage unavailable')
            return original_save(kind,obj)
        config={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'test/model'}
        with patch('workbench.core.config',return_value=config), \
             patch('workbench.web_research.urllib.request.build_opener',return_value=Opener()), \
             patch('workbench.core.save',side_effect=fail_receipt):
            run=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
        self.assertEqual(run['result']['status'],'failed')
        self.assertEqual(run['calls'][0]['usage']['cost'],0.03)
        self.assertEqual(run['receipt_failure']['provider_result']['answer'],'Answer')
        self.assertEqual(core.records('run_call_receipts'),[])
