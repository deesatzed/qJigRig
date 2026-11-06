import tempfile
import unittest
import uuid
from pathlib import Path
from workbench import core, datasets, experiments

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.source=core.snapshot('source','Evidence.')
        self.ds=datasets.freeze('set',[{'case_id':'case','question':'Question?','snapshot_id':self.source['id']}])
        self.config=experiments.freeze_config({'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'})
        self.run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'dataset_id':self.ds['id'],'dataset_sha256':self.ds['sha256'],'case_count':1,'journal_version':1,'targeted':True,'model_config':self.config,'stage':'shared-evidence','answer_check_backend':'remote','local_support_threshold':None,'web_authorized':False,'max_provider_calls':15,'max_calls_per_case':15})
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_all_arm_failures_stop_before_next_case_and_resume_does_not_repeat(self):
        from unittest.mock import patch
        cases=[{'case_id':str(i),'question':f'Question {i}?','snapshot_id':self.source['id']} for i in range(2)]
        ds=datasets.freeze('two cases',cases)
        config={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/large'}
        failure=core.ProviderError('Synthetic provider failure',{'usage':None,'cost_status':'unobserved'})
        with patch('workbench.core.config',return_value=config), patch('workbench.core.call_model',side_effect=failure) as model:
            with self.assertRaisesRegex(ValueError,'All comparison arms failed') as error:
                datasets.launch(ds['id'],True,30)
            run=next(x for x in core.records('dataset_runs') if x.get('dataset_id')==ds['id'])
            self.assertIn(run['id'],str(error.exception))
            self.assertEqual(model.call_count,3)
            self.assertEqual(len(core.records('dataset_receipts')),1)
            self.assertEqual(len(core.records('dataset_intents')),1)
            # Explicit resumption skips the saved failed case and attempts only the next one.
            status=datasets.resume(run['id'],True)
            self.assertEqual(status['status'],'awaiting adjudication')
            self.assertEqual(model.call_count,6)
    def test_completed_case_rejects_conflicting_fresh_execution_policy(self):
        case=self.ds['cases'][0]; run={**self.run,'extra_search':True}
        items=[]
        for arm in ('fresh','direct','frontier'):
            record={'id':uuid.uuid4().hex,'mode':arm,'requested_model':'test/large' if arm=='frontier' else 'test/small',
                    'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
                    'evidence_mode':'shared','extra_search':True,
                    'request':{'question':'Question?','scope':'','as_of':'','snapshot_id':self.source['id']},
                    'result':{'status':'decided'},'answer_check_backend':'remote' if arm=='fresh' else 'not_applicable',
                    'execution_policy':'exhaustive' if arm=='fresh' else 'not_applicable'}
            core.save('runs',record);items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':record['id']})
        comparison={'question':case['question'],'scope':case['scope'],'as_of':case['as_of'],
                    'snapshot_id':case['snapshot_id'],'snapshot_sha256':case['snapshot_sha256'],
                    'snapshot_metadata_sha256':case['snapshot_metadata_sha256'],'stage':run['stage'],
                    'model_config':run['model_config'],'answer_check_backend':'remote','local_support_threshold':None,
                    'targeted':True,'extra_search':True,'items':items}
        with self.assertRaisesRegex(ValueError,'execution policy'):
            datasets._verify_completed(comparison,run,case)
        import json
        path=core.DATA/'runs'/(items[0]['run_id']+'.json')
        fresh=json.loads(path.read_text());fresh['execution_policy']='targeted'
        for field,value,message in (('answer_check_backend','local','evaluator'),('local_support_threshold',0.9,'threshold')):
            changed={**fresh,field:value};path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,message):
                datasets._verify_completed(comparison,run,case)
    def test_resume_rejects_insufficient_or_missing_saved_budget_before_calls(self):
        from unittest.mock import patch
        for values in ({'max_provider_calls':12,'max_calls_per_case':12}, {'max_provider_calls':13,'max_calls_per_case':14}, {'max_provider_calls':None,'max_calls_per_case':None}):
            old=core.save('dataset_runs',{**self.run,'id':uuid.uuid4().hex,**values})
            with self.subTest(values=values), patch('workbench.compare.create',side_effect=AssertionError('paid call reached')), self.assertRaisesRegex(ValueError,'budget'):
                datasets.resume(old['id'],consent=True)
            self.assertEqual(core.records('dataset_intents'),[])
            self.assertEqual(core.records('runs'),[])
    def test_uncertain_started_case_never_retries(self):
        datasets.record_intent(self.run['id'],0,'case')
        with self.assertRaisesRegex(ValueError,'uncertain'): datasets.resume(self.run['id'],consent=True)
        self.assertEqual(core.records('runs'),[])
    def test_shared_corpus_legacy_policy_cannot_resume(self):
        old=core.save('dataset_runs',{**self.run,'id':uuid.uuid4().hex,'stage':'shared-corpus','answer_check_backend':'local','retrieval_policy_version':1})
        with self.assertRaisesRegex(ValueError,'extra-search control'):
            datasets.resume(old['id'],consent=True)
    def test_recovery_rejects_comparison_with_different_extra_search_policy(self):
        case=self.ds['cases'][0]
        run={**self.run,'extra_search':False}
        comparison={'question':case['question'],'scope':case['scope'],'as_of':case['as_of'],
                    'snapshot_id':case['snapshot_id'],'snapshot_sha256':case['snapshot_sha256'],
                    'stage':run['stage'],'model_config':run['model_config'],
                    'answer_check_backend':run['answer_check_backend'],'local_support_threshold':None,
                    'targeted':True,'extra_search':True}
        with self.assertRaisesRegex(ValueError,'frozen dataset case'):
            datasets._verify_completed(comparison,run,case)
    def test_recovery_rejects_worker_environment_mismatch_in_saved_arm(self):
        case=self.ds['cases'][0]
        frozen={'python':'3.12','packages':{'mlx':'1'}}
        run={**self.run,'answer_check_backend':'local','local_support_threshold':0.8,'local_worker_environment':frozen}
        items=[]
        for arm in ('fresh','direct','frontier'):
            record={'id':uuid.uuid4().hex,'mode':arm,'requested_model':'test/large' if arm=='frontier' else 'test/small',
                'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
                'evidence_mode':'shared','request':{'question':'Question?','scope':'','as_of':'','snapshot_id':self.source['id']},'result':{'status':'decided'}}
            if arm=='fresh': record['local_predicate_batch']={'worker_environment':{'python':'3.12','packages':{'mlx':'2'}}}
            core.save('runs',record);items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':record['id']})
        comparison={'question':case['question'],'scope':case['scope'],'as_of':case['as_of'],'snapshot_id':case['snapshot_id'],
            'snapshot_sha256':case['snapshot_sha256'],'snapshot_metadata_sha256':case['snapshot_metadata_sha256'],
            'stage':run['stage'],'model_config':run['model_config'],'answer_check_backend':'local','local_support_threshold':0.8,'items':items}
        with self.assertRaisesRegex(ValueError,'environment'):
            datasets._verify_completed(comparison,run,case)
    def test_decided_local_arm_requires_recorded_inference_evidence(self):
        from workbench.local_judge import validate_recorded_environment
        environment={'python':'3.12','packages':{'mlx':'1'}}
        for incomplete in ({'result':{'status':'decided'},'answer_check':{'worker_environment':environment}},
                           {'result':{'status':'decided'},'local_predicate_batch':{'worker_environment':environment}}):
            with self.subTest(record=incomplete), self.assertRaisesRegex(ValueError,'inference.*missing'):
                validate_recorded_environment(incomplete,environment)
    def test_finished_comparison_is_recovered_without_calls(self):
        intent=datasets.record_intent(self.run['id'],0,'case')
        items=[]
        for arm in ('fresh','direct','frontier'):
            r=core.save('runs',{'id':uuid.uuid4().hex,'mode':arm,'requested_model':'test/large' if arm=='frontier' else 'test/small','source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),'evidence_mode':'shared','request':{'question':'Question?','scope':'','as_of':'','snapshot_id':self.source['id']},'result':{'status':'failed'}})
            items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':r['id']})
        core.save('comparisons',{'id':intent['comparison_id'],'question':'Question?','scope':'','as_of':'','snapshot_id':self.source['id'],'snapshot_sha256':self.source['sha256'],'snapshot_metadata_sha256':core.source_metadata_sha256(self.source),'stage':'shared-evidence','model_config':self.config,'answer_check_backend':'remote','local_support_threshold':None,'items':items})
        before=len(core.records('runs')); status=datasets.resume(self.run['id'],consent=True)
        self.assertEqual(status['status'],'awaiting adjudication'); self.assertEqual(len(core.records('runs')),before)
        self.assertEqual(datasets.resume(self.run['id'],consent=True)['status'],'awaiting adjudication')

class AtomicStorageTests(unittest.TestCase):
    def test_duplicate_id_cannot_replace_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); obj={'id':uuid.uuid4().hex,'value':'first'}
                core.save('runs',obj)
                with self.assertRaises(FileExistsError): core.save('runs',{**obj,'value':'second'})
                self.assertEqual(core.load('runs',obj['id'])['value'],'first')
            finally: core.DATA=old

class UnblindDuringRecoveryTests(unittest.TestCase):
    def test_intent_blocks_unblinding_before_receipt_exists(self):
        from workbench import compare
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); dataset_run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'case_count':1})
                intent=datasets.record_intent(dataset_run['id'],0,'case')
                run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided'},'calls':[],'elapsed_seconds':1,'trace':[]})
                item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
                c=core.save('comparisons',{'id':intent['comparison_id'],'items':[item]})
                compare.adjudicate(c['id'],item['review_id'],'Reviewer','correct','supported','Fact')
                with self.assertRaisesRegex(ValueError,'dataset'): compare.report(c['id'])
            finally: core.DATA=old

class ResumeStatusTests(unittest.TestCase):
    def test_running_dataset_cannot_return_partial_score(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                source=core.snapshot('source','Evidence')
                dataset=datasets.freeze('set',[{'case_id':'c','question':'Question?','snapshot_id':source['id']}])
                run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'case_count':1,'dataset_id':dataset['id'],'dataset_sha256':dataset['sha256']})
                lockdir=core.DATA/'locks'; lockdir.mkdir()
                with (lockdir/(run['id']+'.lock')).open('a') as lock:
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaisesRegex(ValueError,'running'):
                        datasets.score(run['id'])
            finally: core.DATA=old
    def test_live_lock_is_reported_as_running(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'case_count':1,'journal_version':1})
                lockdir=core.DATA/'locks'; lockdir.mkdir()
                with (lockdir/(run['id']+'.lock')).open('a') as lock:
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    self.assertEqual(datasets.status(run['id'])['status'],'running')
            finally: core.DATA=old

class AtomicFailureTests(unittest.TestCase):
    def test_unserializable_record_leaves_no_visible_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); ident=uuid.uuid4().hex
                with self.assertRaises(TypeError): core.save('runs',{'id':ident,'invalid':{1,2}})
                self.assertFalse((core.DATA/'runs'/(ident+'.json')).exists())
                self.assertEqual(list((core.DATA/'runs').iterdir()),[])
            finally: core.DATA=old
