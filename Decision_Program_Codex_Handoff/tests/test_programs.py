import tempfile
import unittest
import uuid
from pathlib import Path
from workbench import core, programs

class MetadataBindingTests(unittest.TestCase):
    def test_intervention_reports_local_worker_version_drift_or_unknown(self):
        before={'answer_check_backend':'local','local_support_threshold':0.8,
                'local_predicate_batch':{'worker_environment':{'python':'3.12','packages':{'mlx':'1'}}}}
        after={'answer_check_backend':'local','local_support_threshold':0.8,
               'local_predicate_batch':{'worker_environment':{'python':'3.12','packages':{'mlx':'2'}}}}
        result=programs.execution_comparison(before,after)
        self.assertIn('local_worker_environment',result['differences'])
        after['local_predicate_batch']={}
        self.assertIn('local_worker_environment',programs.execution_comparison(before,after)['unknown'])
    def test_intervention_execution_comparison_marks_differences_and_missing(self):
        original={'answer_check_backend':'remote','evidence_mode':'shared','requested_model':'model/a'}
        intervention={'answer_check_backend':'local','evidence_mode':'lexical','requested_model':'model/a'}
        result=programs.execution_comparison(original,intervention)
        self.assertEqual(result['differences']['answer_check_backend'],{'original':'remote','intervention':'local'})
        self.assertEqual(result['differences']['evidence_mode'],{'original':'shared','intervention':'lexical'})
        self.assertIn('execution_policy',result['unknown'])
        self.assertNotIn('requested_model',result['differences'])
    def test_draft_review_rejects_changed_source_metadata(self):
        import json
        import tempfile
        import uuid
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                source=core.snapshot('source','Evidence',scope='v1')
                plan={'predicates':[{'id':'p','question':'Evidence?','evidence_requirement':'proof'}],
                      'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                run=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','plan':plan,
                    'request':{'question':'Evidence?','scope':'v1','as_of':'','snapshot_id':source['id']},
                    'source_sha256':source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(source)})
                draft=programs.draft(run['id'])
                source['scope']='v2'
                (core.DATA/'snapshots'/(source['id']+'.json')).write_text(json.dumps(source))
                with self.assertRaisesRegex(ValueError,'metadata'):
                    programs.review(draft['id'],'reviewer','test')
            finally: core.DATA=old

class ProgramTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_instruction_guard_prevents_promotion_and_reuse_of_contaminated_plan(self):
        import json
        from unittest.mock import patch
        probe=json.loads((Path(__file__).resolve().parent.parent/'examples/instruction_injection_variant_live_probe.json').read_text())
        source=core.snapshot('synthetic',probe['source']['text'])
        request={'question':'Is the shipment eligible for the discount?','scope':'','as_of':'','snapshot_id':source['id']}
        fresh=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','plan':probe['run']['plan'],
                                'request':request,'source_sha256':source['sha256']})
        draft=programs.draft(fresh['id'])
        with self.assertRaisesRegex(ValueError,'instruction'):
            programs.review(draft['id'],'Developer','Fixture review')
        # A previously reviewed record must not bypass the execution guard either.
        reviewed=core.save('programs',{**draft,'id':uuid.uuid4().hex,'status':'reviewed'})
        with patch('workbench.core.call_model',side_effect=AssertionError('provider must not be called')):
            run=core.run(request['question'],source['id'],mode='reviewed',program_id=reviewed['id'],consent=True)
        self.assertEqual(run['result']['status'],'deferred')
        self.assertIn('instruction',run['result']['reason'].lower())
        self.assertEqual(run['calls'],[])
    def test_reviewed_local_program_runs_without_provider_consent(self):
        from unittest.mock import patch
        source=core.snapshot('source','The flag is enabled.')
        request={'question':'Is the flag enabled?','scope':'','as_of':'','snapshot_id':source['id']}
        predicate={'id':'p','question':'Is the flag enabled?','evidence_requirement':'Flag status',
                   'positive_claim':'The flag is enabled.','negative_claim':'The flag is disabled.'}
        plan={'predicates':[predicate],'expression':{'ref':'p'},'true_answer':'Yes','false_answer':'No'}
        fresh=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','plan':plan,'request':request,'source_sha256':source['sha256']})
        program=programs.review(programs.draft(fresh['id'])['id'],'Developer','Fixture review')
        yes={'choice':'true','probabilities':{'true':1.0,'false':0.0}}
        no={'choice':'false','probabilities':{'true':0.0,'false':1.0}}
        with patch('workbench.core.call_model',side_effect=AssertionError('provider must not be called')), \
             patch('workbench.local_judge.probe_many',return_value={'results':[yes,no]}), \
             patch('workbench.local_judge.probe',return_value=yes):
            run=core.run(request['question'],source['id'],mode='reviewed',program_id=program['id'],
                         judge_backend='local',local_threshold=0.8,consent=False)
        self.assertEqual(run['result']['status'],'decided')
        self.assertEqual(run['calls'],[])
    def test_edited_draft_preserves_history_and_requires_review(self):
        source=core.snapshot('source','The event is exempt.')
        request={'question':'Is it exempt?','scope':'','as_of':'','snapshot_id':source['id']}
        plan={'predicates':[{'id':'p','question':'Exempt?','evidence_requirement':'Status'}],
              'expression':{'ref':'p'},'true_answer':'Yes','false_answer':'No if it is exempt.'}
        run=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','plan':plan,'request':request,'source_sha256':source['sha256']})
        original=programs.draft(run['id'])
        changed={**plan,'false_answer':'No.'}
        revised=programs.revise(original['id'],changed,'Reviewer','Clarify answer')
        self.assertEqual(revised['status'],'draft')
        self.assertEqual(revised['parent_id'],original['id'])
        self.assertEqual(core.load('programs',original['id'])['plan'],plan)
        with self.assertRaises(ValueError): programs.bind(revised['id'],request,source)
        reviewed=programs.review(revised['id'],'Reviewer','Checked')
        self.assertEqual(programs.bind(reviewed['id'],request,source)['plan'],changed)
        with self.assertRaises(ValueError): programs.revise(reviewed['id'],changed,'Reviewer','Edit')

    def test_review_and_binding(self):
        source=core.snapshot('policy','The object is eligible.')
        request={'question':'Is it eligible?','scope':'','as_of':'','snapshot_id':source['id']}
        plan={'predicates':[{'id':'p1','question':'Eligible?','evidence_requirement':'Eligibility'}], 'expression':{'ref':'p1'},'true_answer':'yes','false_answer':'no'}
        run=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','plan':plan,'request':request,'source_sha256':source['sha256']})
        draft=programs.draft(run['id'])
        with self.assertRaises(ValueError): programs.bind(draft['id'],request,source)
        with self.assertRaises(ValueError): programs.review(draft['id'],'','looks good')
        reviewed=programs.review(draft['id'],'Reviewer','Inspected the plan and source')
        self.assertEqual(programs.bind(reviewed['id'],request,source)['plan'],plan)
        self.assertEqual(core.load('programs',draft['id'])['status'],'draft')
        with self.assertRaises(ValueError): programs.bind(reviewed['id'],{**request,'question':'A different question'},source)
        with self.assertRaises(ValueError): programs.bind(reviewed['id'],{**request,'as_of':'2024-01-01'},source)
        with self.assertRaises(ValueError): programs.review(reviewed['id'],'Reviewer','again')

if __name__=='__main__': unittest.main()

class InterventionBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.a=core.snapshot('rule','Permit required.',scope='policy')
        self.b=core.snapshot('exception','School exempt.',scope='policy')
        from workbench import collections
        self.source=collections.create('policies',[self.a['id'],self.b['id']])
        request={'question':'Permit?','scope':'policy','as_of':'','snapshot_id':self.source['id']}
        plan={'predicates':[{'id':'p','question':'Allowed?','evidence_requirement':'Policy'}],'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
        run=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':self.source['sha256']})
        self.reviewed=programs.review(programs.draft(run['id'])['id'],'Reviewer','Reviewed')
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_one_member_removal_or_direct_derivation_is_allowed(self):
        from workbench import collections
        removed=collections.create('without exception',[self.a['id']])
        req={**self.reviewed['binding'],'snapshot_id':removed['id']}
        result=programs.bind_intervention(self.reviewed['id'],req,removed,'Remove exception for experiment')
        self.assertEqual(result['change']['kind'],'removed')
        child=core.derive_snapshot(self.b['id'],'changed exception','Schools are not exempt.','Withdraw exception')
        changed=collections.create('changed',[self.a['id'],child['id']])
        req['snapshot_id']=changed['id']
        self.assertEqual(programs.bind_intervention(self.reviewed['id'],req,changed,'Change exception')['change']['kind'],'modified')
    def test_unrelated_or_multiple_changes_are_rejected(self):
        from workbench import collections
        other=core.snapshot('other','Other text',scope='policy')
        new=collections.create('unrelated',[self.a['id'],other['id']])
        req={**self.reviewed['binding'],'snapshot_id':new['id']}
        with self.assertRaises(ValueError): programs.bind_intervention(self.reviewed['id'],req,new,'Unrelated source')
        changed_a=core.derive_snapshot(self.a['id'],'a2','Rule changed','Test')
        changed_b=core.derive_snapshot(self.b['id'],'b2','Exception changed','Test')
        both=collections.create('both',[changed_a['id'],changed_b['id']])
        req['snapshot_id']=both['id']
        with self.assertRaises(ValueError): programs.bind_intervention(self.reviewed['id'],req,both,'Two changes')

class InterventionComparisonTests(unittest.TestCase):
    def test_report_rejects_baseline_metadata_mismatch(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp);source=core.snapshot('source','original')
                request={'question':'Q?','scope':'','as_of':'','snapshot_id':source['id']}
                plan={'predicates':[{'id':'p','question':'P?','evidence_requirement':'Fact'}],'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                original=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':source['sha256'],
                    'source_metadata_sha256':core.source_metadata_sha256(source),'result':{'status':'decided','answer':'yes'},'trace':[]})
                program=programs.review(programs.draft(original['id'])['id'],'Reviewer','Reviewed')
                changed=core.derive_snapshot(source['id'],'changed','new text','Change fact');req={**request,'snapshot_id':changed['id']}
                binding=programs.bind_intervention(program['id'],req,changed,'Change fact')
                intervention=core.save('runs',{'id':uuid.uuid4().hex,'mode':'intervention','request':req,'plan':plan,'source_sha256':changed['sha256'],
                    'source_metadata_sha256':core.source_metadata_sha256(changed),'program_id':program['id'],'intervention':binding['change'],'result':{'status':'decided','answer':'no'},'trace':[]})
                original['source_metadata_sha256']='0'*64
                (core.DATA/'runs'/(original['id']+'.json')).write_text(json.dumps(original))
                with self.assertRaisesRegex(ValueError,'metadata'):
                    programs.intervention_report(original['id'],intervention['id'])
            finally: core.DATA=old
    def test_report_rejects_intervention_with_different_or_missing_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp);source=core.snapshot('source','original')
                request={'question':'Q?','scope':'','as_of':'','snapshot_id':source['id']}
                plan={'predicates':[{'id':'p','question':'P?','evidence_requirement':'Fact'}],'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                original=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':source['sha256'],'result':{'status':'decided','answer':'yes'},'trace':[]})
                program=programs.review(programs.draft(original['id'])['id'],'Reviewer','Reviewed')
                changed=core.derive_snapshot(source['id'],'changed','new text','Change fact');req={**request,'snapshot_id':changed['id']}
                binding=programs.bind_intervention(program['id'],req,changed,'Change fact')
                for saved_plan in (None,{**plan,'true_answer':'different'}):
                    intervention=core.save('runs',{'id':uuid.uuid4().hex,'mode':'intervention','request':req,'plan':saved_plan,'program_id':program['id'],'intervention':binding['change'],'result':{'status':'decided','answer':'no'},'trace':[]})
                    with self.subTest(plan=saved_plan), self.assertRaisesRegex(ValueError,'plan'):
                        programs.intervention_report(original['id'],intervention['id'])
            finally: core.DATA=old
    def test_report_rejects_intervention_source_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp);source=core.snapshot('source','original')
                request={'question':'Q?','scope':'','as_of':'','snapshot_id':source['id']}
                plan={'predicates':[{'id':'p','question':'P?','evidence_requirement':'Fact'}],'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                original=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':source['sha256'],'result':{'status':'decided','answer':'yes'},'trace':[]})
                program=programs.review(programs.draft(original['id'])['id'],'Reviewer','Reviewed')
                changed=core.derive_snapshot(source['id'],'changed','new text','Change fact');req={**request,'snapshot_id':changed['id']}
                binding=programs.bind_intervention(program['id'],req,changed,'Change fact')
                intervention=core.save('runs',{'id':uuid.uuid4().hex,'mode':'intervention','request':req,'plan':plan,'source_sha256':'wrong','program_id':program['id'],'intervention':binding['change'],'result':{'status':'decided','answer':'no'},'trace':[]})
                with self.assertRaisesRegex(ValueError,'source'): programs.intervention_report(original['id'],intervention['id'])
            finally: core.DATA=old
    def test_edited_plan_requires_matching_reviewed_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp);source=core.snapshot('source','original')
                request={'question':'Q?','scope':'','as_of':'','snapshot_id':source['id']}
                plan={'predicates':[{'id':'p','question':'P?','evidence_requirement':'Fact'}], 'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                original=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':source['sha256'],'result':{'status':'decided','answer':'yes'},'trace':[]})
                draft=programs.draft(original['id']); revised=programs.revise(draft['id'],{**plan,'false_answer':'No.'},'Reviewer','Clarify')
                program=programs.review(revised['id'],'Reviewer','Reviewed')
                baseline=core.save('runs',{'id':uuid.uuid4().hex,'mode':'reviewed','program_id':program['id'],'request':request,'plan':program['plan'],'source_sha256':source['sha256'],'result':{'status':'decided','answer':'yes'},'trace':[]})
                changed=core.derive_snapshot(source['id'],'changed','new text','Change fact');req={**request,'snapshot_id':changed['id']}
                binding=programs.bind_intervention(program['id'],req,changed,'Change fact')
                intervention=core.save('runs',{'id':uuid.uuid4().hex,'mode':'intervention','request':req,'plan':program['plan'],'source_sha256':changed['sha256'],'program_id':program['id'],'intervention':binding['change'],'result':{'status':'decided','answer':'no'},'trace':[]})
                with self.assertRaises(ValueError): programs.intervention_report(original['id'],intervention['id'])
                self.assertTrue(programs.intervention_report(baseline['id'],intervention['id'])['result_changed'])
            finally: core.DATA=old
    def test_report_preserves_original_and_validates_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                source=core.snapshot('source','original')
                request={'question':'Q?','scope':'','as_of':'','snapshot_id':source['id']}
                plan={'predicates':[{'id':'p','question':'P?','evidence_requirement':'Fact'}], 'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                original=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':source['sha256'],'result':{'status':'decided','answer':'yes'},'trace':[]})
                program=programs.review(programs.draft(original['id'])['id'],'Reviewer','Reviewed')
                changed=core.derive_snapshot(source['id'],'changed','new text','Change fact')
                req={**request,'snapshot_id':changed['id']}
                binding=programs.bind_intervention(program['id'],req,changed,'Change fact')
                intervention=core.save('runs',{'id':uuid.uuid4().hex,'mode':'intervention','request':req,'plan':program['plan'],'source_sha256':changed['sha256'],'program_id':program['id'],'intervention':binding['change'],'result':{'status':'decided','answer':'no'},'trace':[]})
                report=programs.intervention_report(original['id'],intervention['id'])
                self.assertTrue(report['result_changed']); self.assertEqual(report['change']['kind'],'modified')
                with self.assertRaises(ValueError): programs.intervention_report(intervention['id'],original['id'])
            finally: core.DATA=old

class NoEvidenceInterventionTests(unittest.TestCase):
    def test_removed_source_stays_deferred_without_model_call(self):
        from workbench import collections
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                a=core.snapshot('one','Some unrelated words.')
                b=core.snapshot('two','Zebra condition applies.')
                original=collections.create('original',[a['id'],b['id']])
                request={'question':'Zebra condition?','scope':'','as_of':'','snapshot_id':original['id']}
                plan={'predicates':[{'id':'p','question':'Zebra condition?','evidence_requirement':'Zebra condition','positive_claim':'Zebra condition applies.','negative_claim':'Zebra condition does not apply.'}], 'expression':{'ref':'p'},'true_answer':'yes','false_answer':'no'}
                r=core.save('runs',{'id':uuid.uuid4().hex,'mode':'fresh','request':request,'plan':plan,'source_sha256':original['sha256']})
                program=programs.review(programs.draft(r['id'])['id'],'Reviewer','Reviewed')
                removed=collections.create('without zebra',[a['id']])
                result=core.run('Zebra condition?',removed['id'],mode='intervention',consent=True,program_id=program['id'],judge_backend='local',local_threshold=0.9,evidence_mode='lexical',intervention_reason='Remove source')
                self.assertEqual(result['result']['status'],'deferred'); self.assertEqual(result['calls'],[])
                self.assertEqual(result['intervention']['kind'],'removed')
            finally: core.DATA=old
