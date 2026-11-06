import unittest
from workbench import web_research

class WebResearchTests(unittest.TestCase):
    def test_research_requires_observed_search_and_provider_citation(self):
        response={'choices':[{'finish_reason':'stop','message':{'content':'Answer', 'annotations':[{'type':'url_citation','url_citation':{'url':'https://example.com','title':'Source','content':'Excerpt'}}]}}],
                  'usage':{'server_tool_use_details':{'web_search_requests':1}}}
        result=web_research.normalize(response)
        self.assertEqual(result['status'],'decided')
        self.assertEqual(result['citations'][0]['url'],'https://example.com')
        response['usage']={}
        self.assertEqual(web_research.normalize(response)['status'],'deferred')
        response['usage']={'server_tool_use_details':{'web_search_requests':1}}
        response['choices'][0]['message']['annotations']=[]
        self.assertEqual(web_research.normalize(response)['status'],'deferred')
    def test_invalid_citation_is_not_accepted(self):
        response={'choices':[{'message':{'content':'Answer','annotations':[{'type':'url_citation','url_citation':{'url':'file:///private/data'}}]}}],
                  'usage':{'server_tool_use_details':{'web_search_requests':1}}}
        self.assertEqual(web_research.normalize(response)['status'],'deferred')

class WebBudgetTests(unittest.TestCase):
    def test_truncated_or_unknown_finish_reason_cannot_be_a_decision(self):
        response={'choices':[{'finish_reason':'length','message':{'content':'Partial answer',
            'annotations':[{'type':'url_citation','url_citation':{'url':'https://example.com'}}]}}],
            'usage':{'server_tool_use':{'web_search_requests':1}}}
        for reason in ('length','content_filter',None):
            response['choices'][0]['finish_reason']=reason
            with self.subTest(reason=reason):
                result=web_research.normalize(response)
                self.assertEqual(result['status'],'deferred')
                self.assertEqual(result['search_requests'],1)
                self.assertEqual(result['provider_answer'],'Partial answer')
    def test_executed_tool_overrun_fails_even_if_web_count_is_one(self):
        response={'choices':[{'finish_reason':'stop','message':{'content':'Answer','annotations':[{'type':'url_citation','url_citation':{'url':'https://example.com'}}]}}],
                  'usage':{'server_tool_use_details':{'web_search_requests':1,'tool_calls_executed':2}}}
        result=web_research.normalize(response)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['search_requests'],1)
        self.assertEqual(result['tool_calls_executed'],2)
    def test_current_usage_format_and_conflicting_counts(self):
        response={'choices':[{'finish_reason':'stop','message':{'content':'Answer','annotations':[{'type':'url_citation','url_citation':{'url':'https://example.com'}}]}}],
                  'usage':{'server_tool_use':{'web_search_requests':1}}}
        self.assertEqual(web_research.normalize(response)['status'],'decided')
        response['usage']['server_tool_use_details']={'web_search_requests':2}
        self.assertEqual(web_research.normalize(response)['status'],'failed')
    def test_reported_search_over_budget_is_a_failure(self):
        response={'choices':[{'message':{'content':'Answer','annotations':[{'type':'url_citation','url_citation':{'url':'https://example.com'}}]}}],
                  'usage':{'server_tool_use_details':{'web_search_requests':2}}}
        result=web_research.normalize(response)
        self.assertEqual(result['status'],'failed')
        self.assertIn('budget',result['reason'].lower())

class WebAuthorizationTests(unittest.TestCase):
    def test_truncated_response_keeps_reported_cost_and_is_deferred(self):
        import io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,request,timeout):
                return Response(b'{"choices":[{"finish_reason":"length","message":{"content":"Partial","annotations":[{"type":"url_citation","url_citation":{"url":"https://example.com"}}]}}],"usage":{"cost":0.01,"server_tool_use":{"web_search_requests":1}}}')
        old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'model'}), \
                     patch('workbench.web_research.urllib.request.build_opener',return_value=Opener()):
                    result=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
                self.assertEqual(result['result']['status'],'deferred')
                self.assertEqual(result['calls'][0]['finish_reason'],'length')
                self.assertEqual(result['calls'][0]['usage']['cost'],0.01)
                receipt=core.records('run_call_receipts')[0]
                self.assertEqual(receipt['run_id'],result['id'])
                self.assertEqual(receipt['metadata']['usage']['cost'],0.01)
                self.assertEqual(receipt['response'],'Partial')
            finally: core.DATA=old
    def test_truthy_nonboolean_flags_do_not_authorize_web(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                for web,ack in (('false',True),(True,'false'),(1,True),(True,1)):
                    with self.subTest(web=web,ack=ack), patch('workbench.web_research.urllib.request.build_opener',side_effect=AssertionError('must not connect')):
                        result=web_research.run('Public question',allow_web=web,acknowledge_unenforced_limit=ack)
                    self.assertEqual(result['result']['status'],'failed')
                    self.assertEqual(result['calls'],[])
            finally: core.DATA=old
    def test_frozen_model_overrides_changed_environment_without_network(self):
        import io, json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,request,timeout):
                self.body=json.loads(request.data)
                return Response(b'{"choices":[{"message":{"content":"Answer","annotations":[]}}],"usage":{}}')
        opener=Opener(); old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'changed/model'}), \
                     patch('workbench.web_research.urllib.request.build_opener',return_value=opener):
                    result=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True,model='frozen/model')
                self.assertEqual(opener.body['model'],'frozen/model')
                self.assertEqual(result['requested_model'],'frozen/model')
            finally: core.DATA=old
    def test_malformed_http_response_preserves_attempt_with_unknown_cost(self):
        import io, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        for body in (b'{bad json', b'[]', b'{"usage":"invalid","choices":[]}'):
            class Opener:
                def open(self,request,timeout): return Response(body)
            old=core.DATA
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp:
                try:
                    core.DATA=Path(tmp)
                    with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'model'}), \
                         patch('workbench.web_research.urllib.request.build_opener',return_value=Opener()):
                        run=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
                    self.assertEqual(run['result']['status'],'failed')
                    self.assertEqual(len(run['calls']),1)
                    self.assertEqual(run['calls'][0]['cost_status'],'unobserved')
                finally: core.DATA=old
    def test_diagnostic_disables_parallel_calls_and_implicit_plugin(self):
        import io, json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,request,timeout):
                self.body=json.loads(request.data)
                return Response(json.dumps({'choices':[{'message':{'content':'Answer','annotations':[]}}],'usage':{}}).encode())
        opener=Opener(); old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'model'}), \
                     patch('workbench.web_research.urllib.request.build_opener',return_value=opener):
                    web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
                self.assertIs(opener.body['parallel_tool_calls'],False)
                self.assertIn({'id':'web','enabled':False},opener.body['plugins'])
            finally: core.DATA=old
    def test_configured_tool_budget_preserves_step_stop_and_is_recorded(self):
        import io, json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        class Opener:
            def open(self,request,timeout):
                self.body=json.loads(request.data)
                return Response(b'{"choices":[{"message":{"content":"Answer","annotations":[]}}],"usage":{}}')
        opener=Opener(); old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'model','OPENROUTER_WEB_TOOL_BUDGET_USD':'0.01'}), \
                     patch('workbench.web_research.urllib.request.build_opener',return_value=opener):
                    result=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
                self.assertEqual(opener.body['stop_server_tools_when'],[
                    {'type':'step_count_is','step_count':1},
                    {'type':'max_cost','max_cost_in_dollars':0.01}])
                self.assertEqual(result['tool_route']['requested_tool_budget_usd'],0.01)
            finally: core.DATA=old
    def test_invalid_tool_budget_fails_before_transport(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                for value in ('-1','nan','infinity','not-a-number'):
                    with self.subTest(value=value), \
                         patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'dummy','OPENROUTER_TOP_MODEL':'model','OPENROUTER_WEB_TOOL_BUDGET_USD':value}), \
                         patch('workbench.web_research.urllib.request.build_opener',side_effect=AssertionError('unexpected transport')):
                        result=web_research.run('Public question',allow_web=True,acknowledge_unenforced_limit=True)
                    self.assertEqual(result['result']['status'],'failed')
                    self.assertIn('budget',result['result']['reason'])
                    self.assertEqual(result['calls'],[])
            finally: core.DATA=old
    def test_unenforced_limit_requires_explicit_acknowledgment(self):
        import tempfile
        from pathlib import Path
        from workbench import core
        old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                result=web_research.run('Public question',allow_web=True)
                self.assertEqual(result['result']['status'],'failed')
                self.assertIn('limit',result['result']['reason'].lower())
                self.assertEqual(result['calls'],[])
            finally: core.DATA=old
