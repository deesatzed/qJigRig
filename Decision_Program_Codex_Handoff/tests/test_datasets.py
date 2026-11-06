import json
import tempfile
import unittest
import uuid
from pathlib import Path
from workbench import core, datasets, compare

class DatasetTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_cli_announces_saved_run_before_work_without_polluting_json(self):
        import contextlib,io,sys
        from unittest.mock import patch
        from workbench.__main__ import main
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('set',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}
        stdout=io.StringIO();stderr=io.StringIO()
        def resume(ident,consent=False):
            self.assertIn(ident,stderr.getvalue())
            return {'id':ident,'status':'synthetic'}
        with patch.object(sys,'argv',['workbench','dataset-run',dataset['id'],'--max-calls','15','--share-sources']), \
             patch('workbench.core.config',return_value=config),patch('workbench.datasets.resume',side_effect=resume), \
             contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            main()
        self.assertEqual(json.loads(stdout.getvalue())['status'],'synthetic')
        self.assertIn(json.loads(stdout.getvalue())['id'],stderr.getvalue())
    def test_launch_error_reports_saved_run_id_for_inspection(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('set',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}
        with patch('workbench.core.config',return_value=config), \
             patch('workbench.datasets.resume',side_effect=ValueError('Synthetic interruption')):
            with self.assertRaisesRegex(ValueError,'Synthetic interruption') as error:
                datasets.launch(dataset['id'],True,15)
        saved=core.records('dataset_runs')
        self.assertEqual(len(saved),1)
        self.assertIn(saved[0]['id'],str(error.exception))
    def test_pilot_size_freeze_keeps_per_case_call_budget(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        cases=[{'case_id':str(i),'question':f'Question {i}?','snapshot_id':source['id']} for i in range(100)]
        dataset=datasets.freeze('pilot-sized development set',cases)
        self.assertEqual(len(dataset['cases']),100)
        with self.assertRaisesRegex(ValueError,'1500'):
            datasets.prepare(dataset['id'],True,1499)
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}):
            run=datasets.prepare(dataset['id'],True,1500)
        self.assertEqual(run['case_count'],100)
        with self.assertRaisesRegex(ValueError,'100'):
            datasets.freeze('too many',cases+[{'case_id':'extra','question':'Extra?','snapshot_id':source['id']}])
    def test_archive_rescore_reports_source_mismatch(self):
        from workbench import archive
        bundle=json.loads((core.ROOT/'examples'/'shared_corpus_reviewed_archive.json').read_text())
        bundle['records']['runs'][0]['source_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'frozen dataset case'):
            archive.verify_dataset(bundle)
    def test_budget_reserves_one_predicate_repair(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('set',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        with self.assertRaisesRegex(ValueError,'15'):
            datasets.prepare(dataset['id'],True,14)
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}):
            run=datasets.prepare(dataset['id'],True,15)
        self.assertEqual(run['max_calls_per_case'],15)
    def test_local_environment_drift_blocks_resume_before_model_call(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('set',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
        config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}
        before={'python':'3.12.16','packages':{'mlx':'1.0'}}
        after={'python':'3.12.16','packages':{'mlx':'2.0'}}
        with patch('workbench.core.config',return_value=config), patch('workbench.local_judge.worker_python',return_value='/unused'), \
             patch('workbench.local_judge.inspect_worker_environment',return_value=before,create=True):
            run=datasets.prepare(dataset['id'],True,15,'local',0.8,'shared-corpus')
        self.assertEqual(run['local_worker_environment'],before)
        with patch('workbench.local_judge.inspect_worker_environment',return_value=after,create=True), \
             patch('workbench.core.call_model',side_effect=AssertionError('must not call provider')):
            with self.assertRaisesRegex(ValueError,'environment.*changed'):
                datasets.resume(run['id'],consent=True)
    def test_freeze_rejects_labels_and_detects_tampering(self):
        source=core.snapshot('source','Evidence')
        case={'case_id':'a','question':'Question?','snapshot_id':source['id']}
        with self.assertRaises(ValueError): datasets.freeze('bad',[{**case,'answer':'yes'}])
        with self.assertRaises(ValueError): datasets.freeze('bad',[case,case])
        dataset=datasets.freeze('test',[case]); self.assertEqual(datasets.load_frozen(dataset['id']),dataset)
        with self.assertRaises(ValueError): datasets.launch(dataset['id'],True,9)
        path=core.DATA/'datasets'/(dataset['id']+'.json'); dataset['cases'][0]['question']='Altered'; path.write_text(json.dumps(dataset))
        with self.assertRaisesRegex(ValueError,'integrity'): datasets.load_frozen(dataset['id'])
    def test_frozen_case_rejects_scope_or_date_metadata_drift(self):
        source=core.snapshot('source','Evidence',scope='original',observed_at='2026-01-01')
        dataset=datasets.freeze('test',[{'case_id':'a','question':'Question?','snapshot_id':source['id']}])
        path=core.DATA/'snapshots'/(source['id']+'.json')
        source['observed_at']='2020-01-01'; path.write_text(json.dumps(source))
        with self.assertRaisesRegex(ValueError,'metadata'):
            datasets.verify_case_source(dataset['cases'][0])
    def test_score_requires_reviews_and_counts_failed_runs(self):
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('test',[{'case_id':'one','question':'Question?','snapshot_id':source['id']}])
        run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'dataset_id':dataset['id'],'dataset_sha256':dataset['sha256'],'case_count':1})
        items=[]
        for arm,status in [('fresh','decided'),('direct','failed')]:
            r=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':status,'answer':'yes'},'calls':[],'elapsed_seconds':1,'trace':[]})
            items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':r['id']})
        c=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Question?','scope':'','as_of':'','snapshot_id':source['id'],'items':items})
        core.save('dataset_receipts',{'id':uuid.uuid4().hex,'dataset_run_id':run['id'],'index':0,'case_id':'one','comparison_id':c['id']})
        with self.assertRaises(ValueError): datasets.score(run['id'])
        compare.adjudicate(c['id'],items[0]['review_id'],'Reviewer','correct','supported','Evidence')
        compare.adjudicate(c['id'],items[1]['review_id'],'Reviewer','unresolved','unclear','Technical failure')
        score=datasets.score(run['id'])
        self.assertEqual(score['arms']['fresh']['correct_supported_or_justified'],1)
        self.assertEqual(score['arms']['direct']['incorrect'],1)
        self.assertIsNone(score['arms']['direct']['provider_cost_usd'])
        self.assertEqual(score['arms']['fresh']['latency_median_seconds'],1)
        self.assertEqual(score['arms']['fresh']['latency_p95_seconds'],1)
        paired=next(p for p in score['paired'] if p['right']=='direct')
        self.assertEqual(paired['left_correct_right_incorrect'],1)
        from workbench import archive
        core.save('comparison_intents',{'id':c['id'],'question':'Question?','arms':['fresh','direct']})
        first_run=items[0]['run_id']
        core.save('run_intents',{'id':first_run,'mode':'fresh','request':{'question':'Question?'}})
        core.save('run_call_intents',{'id':uuid.uuid4().hex,'run_id':first_run,'index':0})
        unrelated=uuid.uuid4().hex
        core.save('run_intents',{'id':unrelated,'mode':'fresh','request':{'question':'Other?'}})
        bundle=archive.export_dataset(run['id'])
        self.assertEqual(bundle['format'],'decision-workbench-dataset-v2')
        self.assertEqual([x['id'] for x in bundle['records']['comparison_intents']],[c['id']])
        self.assertEqual([x['id'] for x in bundle['records']['run_intents']],[first_run])
        self.assertEqual(len(bundle['records']['run_call_intents']),1)
        verification=archive.verify_dataset(bundle)
        self.assertTrue(verification['matches_exported_score'])
        self.assertEqual(verification['score'],score)
        self.assertEqual(verification['journal_status'],'incomplete')
        bundle['records']['run_call_intents'][0]['run_id']=uuid.uuid4().hex
        tampered=archive.verify_dataset(bundle)
        self.assertTrue(tampered['matches_exported_score'])
        self.assertEqual(tampered['journal_status'],'inconsistent')
        import subprocess, sys
        path=Path(self.tmp.name)/'tampered-archive.json'; path.write_text(json.dumps(bundle))
        check=subprocess.run([sys.executable,'-m','workbench','dataset-verify',str(path)],
                             cwd=core.ROOT,capture_output=True,text=True)
        self.assertEqual(check.returncode,1)
        self.assertEqual(json.loads(check.stdout)['journal_status'],'inconsistent')
        bundle['score']['arms']['fresh']['assigned']=999
        self.assertFalse(archive.verify_dataset(bundle)['matches_exported_score'])
    def test_score_rejects_receipt_for_wrong_frozen_case(self):
        source=core.snapshot('source','Evidence')
        dataset=datasets.freeze('set',[{'case_id':'correct','question':'Question?','snapshot_id':source['id']}])
        run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'dataset_id':dataset['id'],'dataset_sha256':dataset['sha256'],'case_count':1})
        core.save('dataset_receipts',{'id':uuid.uuid4().hex,'dataset_run_id':run['id'],'index':0,'case_id':'different','comparison_id':uuid.uuid4().hex})
        with self.assertRaisesRegex(ValueError,'case'):
            datasets.score(run['id'])

class ScoreCategoryTests(unittest.TestCase):
    def test_journal_check_separates_missing_and_conflicting_receipts(self):
        from workbench import archive
        records={kind:[] for kind in archive.KINDS+archive.JOURNAL_KINDS}
        records['runs']=[{'id':'run','calls':[{'usage':{'cost':0.01}}]}]
        records['run_intents']=[{'id':'run'}]
        records['run_call_intents']=[{'id':'call','run_id':'run','index':0,'stage':'direct_answer'}]
        self.assertEqual(archive.check_journal(records)[0],'incomplete')
        records['run_call_receipts']=[{'id':'call','run_id':'run','stage':'direct_answer','metadata':{'usage':{'cost':0.01}}}]
        self.assertEqual(archive.check_journal(records)[0],'consistent')
        records['run_call_receipts'][0]['metadata']['usage']['cost']=0.02
        self.assertEqual(archive.check_journal(records)[0],'inconsistent')
    def test_journal_checks_returned_text_against_saved_response(self):
        from workbench import archive
        records={kind:[] for kind in archive.KINDS+archive.JOURNAL_KINDS}
        records['runs']=[{'id':'run','mode':'direct','calls':[{'usage':{}}],
                          'model_responses':[{'stage':'direct_answer','text':'original'}]}]
        records['run_intents']=[{'id':'run'}]
        records['run_call_intents']=[{'id':'call','run_id':'run','index':0,'stage':'direct_answer'}]
        records['run_call_receipts']=[{'id':'call','run_id':'run','stage':'direct_answer',
            'status':'returned','metadata':{'usage':{}},'response':'original'}]
        self.assertEqual(archive.check_journal(records)[0],'consistent')
        records['run_call_receipts'][0]['response']='altered'
        self.assertEqual(archive.check_journal(records)[0],'inconsistent')
    def test_duplicate_call_indices_are_not_consistent(self):
        from workbench import archive
        records={kind:[] for kind in archive.KINDS+archive.JOURNAL_KINDS}
        records['runs']=[{'id':'run','calls':[{'usage':{}},{'usage':{}}]}]
        records['run_intents']=[{'id':'run'}]
        records['run_call_intents']=[{'id':'a','run_id':'run','index':0,'stage':'judge'},
                                     {'id':'b','run_id':'run','index':0,'stage':'judge'}]
        self.assertEqual(archive.check_journal(records)[0],'inconsistent')
    def test_adjudication_never_turns_failure_into_success(self):
        self.assertEqual(datasets.score_category({'status':'failed','verdict':'correct','evidence_support':'supported'}),'incorrect')
        self.assertEqual(datasets.score_category({'status':'decided','verdict':'correct','evidence_support':'unclear'}),'unresolved')
        self.assertEqual(datasets.score_category({'status':'decided','verdict':'correct','evidence_support':'unsupported'}),'incorrect')
        self.assertEqual(datasets.score_category({'status':'deferred','verdict':'correct','evidence_support':'unclear'}),'unresolved')
        self.assertEqual(datasets.score_category({'status':'deferred','verdict':'correct','evidence_support':'unclear'},'unanswerable'),'correct')

class ReportRenderingTests(unittest.TestCase):
    def test_markdown_local_inference_totals_preserve_unknown(self):
        arm={'assigned':2,'correct_supported_or_justified':0,'incorrect':0,'unresolved':2,'decided':0,
             'deferred':2,'failed':0,'latency_median_seconds':1,'latency_p95_seconds':1,'provider_cost_usd':None}
        result={'dataset_run_id':'sample','stage':'shared-corpus','interpretation':'Exploratory.',
                'arms':{'fresh':arm},'paired':[],
                'cases':[{'rows':[{'arm':'fresh','local_inferences':3}]},
                         {'rows':[{'arm':'fresh','local_inferences':None}]}]}
        self.assertIn('local inferences: unknown',datasets.render_markdown(result))
        result['cases'][1]['rows'][0]['local_inferences']=2
        self.assertIn('local inferences: 5',datasets.render_markdown(result))
    def test_markdown_includes_experimental_configuration_and_work(self):
        result={'dataset_run_id':'sample','dataset_sha256':'abc','stage':'shared-corpus',
                'targeted':True,'extra_search':False,'answer_check_backend':'local','local_support_threshold':0.8,
                'model_config':{'small_model':'small','frontier_model':'large'},'interpretation':'Exploratory.',
                'arms':{'fresh':{'assigned':1,'correct_supported_or_justified':0,'incorrect':0,'unresolved':1,
                  'decided':0,'deferred':1,'failed':0,'latency_median_seconds':1,'latency_p95_seconds':1,
                  'provider_cost_usd':None,'provider_calls':2,'source_searches':3}},'paired':[]}
        text=datasets.render_markdown(result)
        for expected in ('abc','small','large','0.8','disabled','3 source searches','2 provider calls'):
            self.assertIn(expected,text)
    def test_markdown_names_reviewers_without_claiming_independence(self):
        result={'dataset_run_id':'sample','stage':'shared-corpus','interpretation':'Exploratory.',
                'arms':{},'paired':[],'cases':[{'case_assessment':{'reviewer':'Developer smoke'},
                                                'rows':[{'reviewer':'Reviewer A'}]}]}
        text=datasets.render_markdown(result)
        self.assertIn('Developer smoke',text)
        self.assertIn('Reviewer A',text)
        self.assertIn('independence is not verified',text)
    def test_markdown_identifies_scope_and_unresolved(self):
        result={'dataset_run_id':'sample','stage':'shared-corpus','interpretation':'Exploratory, not confirmatory.',
                'arms':{'fresh':{'assigned':2,'correct_supported_or_justified':1,'incorrect':0,'unresolved':1,'decided':1,'deferred':1,'failed':0,'decision_rate_all_assigned':0.5,'correct_fraction_all_assigned':0.5,'latency_median_seconds':1.0,'latency_p95_seconds':1.5,'provider_cost_usd':None,'provider_calls':3,'source_searches':4}},'paired':[]}
        text=datasets.render_markdown(result)
        self.assertIn('shared-corpus',text); self.assertIn('unresolved',text.lower()); self.assertIn('unobserved',text)

class DatasetReceiptTests(unittest.TestCase):
    def test_duplicate_case_receipts_are_not_a_complete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'case_count':2})
                for i in range(2): core.save('dataset_receipts',{'id':uuid.uuid4().hex,'dataset_run_id':run['id'],'index':0,'comparison_id':uuid.uuid4().hex})
                self.assertEqual(datasets.status(run['id'])['status'],'incomplete')
            finally: core.DATA=old
