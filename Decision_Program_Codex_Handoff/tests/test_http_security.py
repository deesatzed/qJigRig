import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from workbench import core
from workbench.__main__ import Handler
from unittest.mock import patch

class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); core.DATA=self.old; self.tmp.cleanup()
    def request(self,method,path,headers=None,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request(method,path,body=body,headers=headers or {})
            r=conn.getresponse(); r.read(); return r.status
        finally: conn.close()
    def test_unknown_host_cannot_read_local_data(self):
        self.assertEqual(self.request('GET','/api/snapshots',{'Host':'attacker.example'}),403)
        self.assertEqual(self.request('GET','/api/snapshots'),200)
    def test_preflight_is_read_only_and_hides_key(self):
        with patch('workbench.core.config',return_value={'OPENROUTER_API_KEY':'never-display-this-secret'}):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
            try:
                conn.request('GET','/api/preflight'); response=conn.getresponse(); raw=response.read()
            finally: conn.close()
        self.assertEqual(response.status,200)
        self.assertTrue(json.loads(raw)['api_key_present'])
        self.assertNotIn(b'never-display-this-secret',raw)
    def test_cross_origin_and_plain_text_post_rejected(self):
        payload='{"title":"x","text":"y"}'
        self.assertEqual(self.request('POST','/api/snapshots',{'Origin':'https://attacker.example','Content-Type':'application/json'},payload),403)
        self.assertEqual(self.request('POST','/api/snapshots',{'Content-Type':'text/plain'},payload),415)
        self.assertEqual(core.records('snapshots'),[])
        self.assertEqual(self.request('POST','/api/snapshots',{'Content-Type':'application/json'},payload),200)
        self.assertEqual(len(core.records('snapshots')),1)

    def test_source_import_records_user_supplied_origin_without_fetching_it(self):
        body=json.dumps({'title':'Policy','text':'Evidence.','origin':'https://example.invalid/version-1'})
        self.assertEqual(self.request('POST','/api/snapshots',{'Content-Type':'application/json'},body),200)
        self.assertEqual(core.records('snapshots')[0]['origin'],'https://example.invalid/version-1')
        bad=json.dumps({'title':'Policy','text':'Evidence.','origin':{'url':'not text'}})
        self.assertEqual(self.request('POST','/api/snapshots',{'Content-Type':'application/json'},bad),400)

    def test_truthy_nonboolean_consent_never_authorizes_model_calls(self):
        from workbench import datasets
        source=core.snapshot('source','private text')
        dataset=datasets.freeze('test',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}
        for value in ('false',1,{'yes':True}):
            with self.subTest(value=value), patch('workbench.core.config',return_value=config), \
                 patch('workbench.core.call_model',side_effect=AssertionError('provider call must not happen')):
                body=json.dumps({'question':'Question?','snapshot_id':source['id'],'consent':value})
                self.assertEqual(self.request('POST','/api/compare',{'Content-Type':'application/json'},body),400)
                body=json.dumps({'dataset_id':dataset['id'],'consent':value,'max_calls':15})
                self.assertEqual(self.request('POST','/api/dataset-run',{'Content-Type':'application/json'},body),400)
                run=core.run('Question?',source['id'],consent=value)
                self.assertIn('consent',run['result']['reason'].lower())
                self.assertEqual(run['calls'],[])
        self.assertEqual(core.records('dataset_runs'),[])

    def test_snapshot_endpoint_returns_only_matching_record(self):
        source=core.snapshot('source','public synthetic text')
        self.assertEqual(self.request('GET','/api/snapshot/'+source['id']),200)
        self.assertEqual(self.request('GET','/api/snapshot/not-valid'),400)

    def test_review_page_accepts_comparison_link(self):
        self.assertEqual(self.request('GET','/review?comparison='+'a'*32),200)

    def test_source_options_list_metadata_without_source_text(self):
        source=core.snapshot('Public title','private source body',scope='scope')
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET','/api/source-options'); response=conn.getresponse(); body=json.loads(response.read())
        finally: conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(body[0]['id'],source['id'])
        self.assertEqual(body[0]['scope'],'scope')
        self.assertNotIn('text',body[0])
        self.assertNotIn('private source body',json.dumps(body))

    def test_run_options_do_not_return_full_trace_and_run_can_be_opened(self):
        import uuid
        run=core.save('runs',{'id':uuid.uuid4().hex,'created_at':'2026-01-01','mode':'fresh',
            'request':{'question':'Public question?'},'result':{'status':'decided','answer':'Sensitive answer'},
            'trace':[{'private_source_text':'Sensitive source excerpt'}]})
        def get(path):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
            try:
                conn.request('GET',path); response=conn.getresponse(); return response.status,json.loads(response.read())
            finally: conn.close()
        status,options=get('/api/run-options'); self.assertEqual(status,200)
        self.assertEqual(options[0]['id'],run['id'])
        self.assertNotIn('Sensitive answer',json.dumps(options))
        self.assertNotIn('Sensitive source excerpt',json.dumps(options))
        status,opened=get('/api/run/'+run['id']); self.assertEqual(status,200)
        self.assertEqual(opened,run)

    def test_comparison_journal_shows_uncertainty_without_arm_identity(self):
        import uuid
        ident=uuid.uuid4().hex
        core.save('comparison_intents',{'id':ident,'question':'Question?','stage':'shared-evidence',
                   'created_at':'2026-01-01','arms':['fresh','direct','frontier']})
        core.save('comparison_arm_intents',{'id':uuid.uuid4().hex,'comparison_id':ident,'arm':'fresh'})
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET','/api/comparison-journal'); response=conn.getresponse(); body=json.loads(response.read())
        finally: conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(body[0]['state'],'in progress or interrupted')
        self.assertEqual((body[0]['started_arms'],body[0]['completed_arms']),(1,0))
        self.assertNotIn('fresh',json.dumps(body))
    def test_run_journal_exposes_unfinished_without_provider_response(self):
        import uuid
        ident=uuid.uuid4().hex
        core.save('run_intents',{'id':ident,'created_at':'2026-01-01','mode':'fresh','request':{'question':'Q'}})
        core.save('run_call_intents',{'id':uuid.uuid4().hex,'run_id':ident,'index':0,'stage':'planner'})
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET','/api/run-journal'); response=conn.getresponse(); body=json.loads(response.read())
        finally: conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(body[0]['state'],'in progress or interrupted')
        self.assertEqual((body[0]['started_calls'],body[0]['recorded_calls']),(1,0))
    def test_run_journal_includes_final_record_with_missing_receipt(self):
        import uuid
        ident=uuid.uuid4().hex
        core.save('run_intents',{'id':ident,'created_at':'2026-01-01','mode':'direct','request':{'question':'Q'}})
        core.save('run_call_intents',{'id':uuid.uuid4().hex,'run_id':ident,'index':0,'stage':'direct_answer'})
        core.save('runs',{'id':ident,'result':{'status':'failed'},'calls':[{'usage':{'cost':0.01}}]})
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET','/api/run-journal'); response=conn.getresponse(); body=json.loads(response.read())
        finally: conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(body[0]['state'],'final run has unconfirmed calls')

    def test_comparison_export_requires_review(self):
        import uuid
        from workbench import compare
        source=core.snapshot('source','Evidence')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided'},'calls':[],'trace':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q','scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        path='/api/export-comparison/'+comp['id']
        self.assertEqual(self.request('GET',path),400)
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','correct','supported','Evidence')
        self.assertEqual(self.request('GET',path),200)

    def test_dataset_start_returns_id_before_background_work_finishes(self):
        from workbench import datasets, jobs
        source=core.snapshot('source','Public evidence')
        dataset=datasets.freeze('test',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        entered=threading.Event(); release=threading.Event()
        def slow_resume(ident,consent=False): entered.set(); release.wait(3)
        try:
            with patch('workbench.datasets.resume',side_effect=slow_resume), patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}):
                conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=2)
                conn.request('POST','/api/dataset-run',body=json.dumps({'dataset_id':dataset['id'],'consent':True,'max_calls':15}),headers={'Content-Type':'application/json'})
                response=conn.getresponse(); result=json.loads(response.read()); conn.close()
                self.assertEqual(response.status,200); self.assertTrue(entered.wait(1))
                self.assertEqual(jobs.status(result['id'])['state'],'running')
                release.set(); jobs.wait(result['id'],3)
        finally: release.set()
    def test_background_resume_surfaces_worker_error(self):
        import uuid
        from workbench import jobs
        run=core.save('dataset_runs',{'id':uuid.uuid4().hex})
        with patch('workbench.datasets.resume',side_effect=ValueError('Inspect saved case')):
            jobs.resume_dataset(run['id'],True)
            jobs.wait(run['id'],3)
        self.assertEqual(jobs.status(run['id']),{'state':'error','error':'Inspect saved case'})
    def test_dataset_resume_is_tracked_and_rejects_duplicate_worker(self):
        import uuid
        from workbench import jobs
        run=core.save('dataset_runs',{'id':uuid.uuid4().hex})
        entered=threading.Event();release=threading.Event()
        def slow_resume(ident,consent=False): entered.set(); release.wait(3)
        body=json.dumps({'dataset_run_id':run['id'],'consent':True})
        headers={'Content-Type':'application/json'}
        try:
            with patch('workbench.datasets.resume',side_effect=slow_resume):
                self.assertEqual(self.request('POST','/api/dataset-resume-background',headers,json.dumps({'dataset_run_id':run['id'],'consent':False})),400)
                self.assertEqual(self.request('POST','/api/dataset-resume-background',headers,body),200)
                self.assertTrue(entered.wait(1))
                self.assertEqual(jobs.status(run['id'])['state'],'running')
                self.assertEqual(self.request('POST','/api/dataset-resume-background',headers,body),400)
                release.set();jobs.wait(run['id'],3)
                self.assertEqual(jobs.status(run['id'])['state'],'finished')
        finally: release.set()
