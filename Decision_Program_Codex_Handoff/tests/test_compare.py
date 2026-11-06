import tempfile
import unittest
import uuid
from pathlib import Path
from workbench import core, compare

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_blind_review_exposes_derived_source_provenance(self):
        from workbench import collections
        original=core.snapshot('Original','Original fact.')
        changed=core.derive_snapshot(original['id'],'Changed','Changed fact.','Synthetic test change')
        for source in (changed,collections.create('Collection',[changed['id']])):
            comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q?',
                'scope':'','as_of':'','snapshot_id':source['id'],'items':[]})
            visible=compare.blind(comp['id'])['source']
            provenance=visible['members'][0] if visible['members'] else visible
            self.assertEqual(provenance['parent_snapshot_id'],original['id'])
            self.assertEqual(provenance['intervention_reason'],'Synthetic test change')
    def test_missing_local_batch_count_is_unknown_not_zero(self):
        source=core.snapshot('source','Evidence')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'deferred'},'trace':[],
            'answer_check_backend':'local','local_predicate_batches':[{'backend':'local Unsloth MLX'}],
            'calls':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q?',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Count missing')
        self.assertIsNone(compare.report(comp['id'])['rows'][0]['local_inferences'])
        import json
        run.pop('local_predicate_batches');run['trace']=[{'outcome':'unknown'}]
        (core.DATA/'runs'/(run['id']+'.json')).write_text(json.dumps(run))
        self.assertIsNone(compare.report(comp['id'])['rows'][0]['local_inferences'])
    def test_blind_review_keeps_predicate_quotes_and_retrieved_spans(self):
        from workbench.collections import quote_ref
        source=core.snapshot('source','Predicate fact. Retrieved context.')
        quote='Predicate fact.'; context='Retrieved context.'
        run=core.save('runs',{'id':uuid.uuid4().hex,'request':{'snapshot_id':source['id']},
            'source_sha256':source['sha256'],'result':{'status':'deferred'},
            'trace':[{'predicate':{'question':'Is this applicable?'},'outcome':'unknown','reported_outcome':'false',
                      'quote':quote,'source_ref':quote_ref(source,quote),
                      'evidence_spans':[{'text':context,'source_ref':quote_ref(source,context)}]}]})
        item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q?',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        evidence=compare.blind(comp['id'])['items'][0]['review_evidence']
        self.assertEqual([x['text'] for x in evidence],[quote,context])
        self.assertEqual([x['source_ref']['source_id'] for x in evidence],[source['id']]*2)
        self.assertEqual(evidence[0]['predicate_question'],'Is this applicable?')
        self.assertEqual(evidence[0]['usable_outcome'],'unknown')
        self.assertEqual(evidence[0]['reported_outcome'],'false')
    def test_duplicate_case_assessment_is_a_readable_error_and_keeps_first(self):
        source=core.snapshot('source','Evidence')
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'snapshot_id':source['id'],'items':[]})
        first=compare.assess_case(comp['id'],'Reviewer','uncertain','Cannot decide')
        with self.assertRaisesRegex(ValueError,'assessment already exists'):
            compare.assess_case(comp['id'],'Other reviewer','uncertain','Second submission')
        self.assertEqual(compare.get_case_assessment(comp['id']),first)
    def test_concurrent_adjudication_collision_is_a_readable_error(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        item={'review_id':uuid.uuid4().hex,'arm':'direct','run_id':uuid.uuid4().hex}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'snapshot_id':source['id'],'items':[item]})
        with patch('workbench.compare.core.save',side_effect=FileExistsError):
            with self.assertRaisesRegex(ValueError,'adjudication already exists'):
                compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Reason')
    def test_blind_review_surfaces_citation_attribution_failure(self):
        from workbench.collections import quote_ref
        source=core.snapshot('Actual source','The answer is yes.')
        ref=quote_ref(source,source['text']);ref['source_title']='Wrong source'
        run=core.save('runs',{'id':uuid.uuid4().hex,'request':{'snapshot_id':source['id']},'source_sha256':source['sha256'],
            'source_metadata_sha256':core.source_metadata_sha256(source),'result':{'status':'decided','answer':'yes',
            'quotes':[source['text']],'source_refs':[ref]},'trace':[]})
        item={'review_id':uuid.uuid4().hex,'arm':'direct','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q?',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        review=compare.blind(comp['id'])['items'][0]
        self.assertEqual(compare.blind(comp['id'])['source']['id'],source['id'])
        self.assertEqual(review['citation_integrity'],'failed')
        self.assertNotIn('arm',review)
        with self.assertRaisesRegex(ValueError,'[Cc]itation'):
            compare.adjudicate(comp['id'],item['review_id'],'Reviewer','correct','supported','Looks supported')
        self.assertEqual(core.records('adjudications'),[])
        saved=compare.adjudicate(comp['id'],item['review_id'],'Reviewer','incorrect','unsupported','Attribution conflicts')
        self.assertEqual(saved['evidence_support'],'unsupported')
    def test_report_rejects_supported_judgment_if_citation_later_conflicts(self):
        import json
        from workbench.collections import quote_ref
        source=core.snapshot('Actual source','The answer is yes.')
        ref=quote_ref(source,source['text'])
        run=core.save('runs',{'id':uuid.uuid4().hex,'request':{'snapshot_id':source['id']},'source_sha256':source['sha256'],
            'source_metadata_sha256':core.source_metadata_sha256(source),'result':{'status':'decided','answer':'yes',
            'quotes':[source['text']],'source_refs':[ref]},'trace':[],'calls':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'direct','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q?',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','correct','supported','Correct source')
        run['result']['source_refs'][0]['source_title']='Wrong source'
        (core.DATA/'runs'/(run['id']+'.json')).write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError,'[Cc]itation'):
            compare.report(comp['id'])
    def test_environment_mismatch_stops_after_fresh_receipt(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        expected={'python':'3.12','packages':{'mlx':'1'}}
        def run(*args,**kwargs):
            return core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided'},'calls':[],'trace':[],
                'local_predicate_batch':{'worker_environment':{'python':'3.12','packages':{'mlx':'2'}}}})
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/top'}), \
             patch('workbench.local_judge.inspect_worker_environment',return_value=expected), patch('workbench.core.run',side_effect=run) as invoke:
            with self.assertRaisesRegex(ValueError,'environment'):
                compare.create('Q?',source['id'],consent=True,judge_backend='local',local_threshold=0.8,expected_local_environment=expected)
        self.assertEqual(invoke.call_count,1)
        self.assertEqual([x['arm'] for x in core.records('comparison_arm_receipts')],['fresh'])
        self.assertEqual([x['arm'] for x in core.records('comparison_arm_intents')],['fresh'])
    def test_practical_report_preserves_inconsistent_tool_counts(self):
        source=core.snapshot('source','Evidence')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'failed','reason':'Tool overrun'},
            'calls':[{'usage':{'server_tool_use_details':{'web_search_requests':1,'tool_calls_executed':2}}}],
            'trace':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'frontier','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'practical','question':'Q',
              'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Overrun')
        row=compare.report(comp['id'])['rows'][0]
        self.assertEqual(row['web_search_requests'],1)
        self.assertEqual(row['server_tool_calls_executed'],2)
    def test_interrupted_comparison_keeps_intent_and_completed_arm_receipt(self):
        from unittest.mock import patch
        source=core.snapshot('source','Evidence')
        ident=uuid.uuid4().hex
        def run(*args,**kwargs):
            if args[4]=='direct': raise RuntimeError('interrupted')
            return core.save('runs',{'id':uuid.uuid4().hex,'mode':args[4],
                                      'result':{'status':'deferred'},'calls':[],'trace':[]})
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/top'}), \
             patch('workbench.core.run',side_effect=run):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                compare.create('Q?',source['id'],consent=True,comparison_id=ident)
        intent=core.load('comparison_intents',ident)
        receipts=core.records('comparison_arm_receipts')
        started=core.records('comparison_arm_intents')
        self.assertEqual(intent['arms'],list(compare.ARMS))
        self.assertEqual(len(receipts),1)
        self.assertEqual({item['arm'] for item in started},{'fresh','direct'})
        self.assertEqual((receipts[0]['comparison_id'],receipts[0]['arm']),(ident,'fresh'))
        self.assertEqual(core.load('runs',receipts[0]['run_id'])['mode'],'fresh')
        self.assertFalse((core.DATA/'comparisons'/(ident+'.json')).exists())
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/top'}), \
             patch('workbench.core.run',side_effect=AssertionError('must not retry')):
            with self.assertRaisesRegex(ValueError,'inspect saved arms'):
                compare.create('Q?',source['id'],consent=True,comparison_id=ident)
    def test_search_usage_distinguishes_missing_from_reported_zero(self):
        source=core.snapshot('source','Fact')
        calls=[{'usage':{'server_tool_use':{'web_search_requests':0}}}, {'usage':{'cost':0.01}}]
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'failed'},'calls':calls,'trace':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'direct','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q','scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Incomplete')
        row=compare.report(comp['id'])['rows'][0]
        self.assertIsNone(row['web_search_requests'])
        self.assertEqual(row['observed_web_search_requests'],0)
        self.assertEqual(row['web_search_usage_status'],'incomplete')
    def test_blind_view_marks_saved_judgment_without_revealing_arm(self):
        source=core.snapshot('source','Evidence')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'deferred'},'trace':[]})
        item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        self.assertFalse(compare.blind(comp['id'])['items'][0]['review_saved'])
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Evidence gap')
        result=compare.blind(comp['id'])['items'][0]
        self.assertTrue(result['review_saved'])
        self.assertNotIn('arm',result)
        self.assertNotIn('reviewer',result)
    def test_unblinded_report_shows_answers_and_exact_text_difference(self):
        source=core.snapshot('source','Evidence')
        items=[]
        for arm,answer in (('fresh','Yes'),('direct','No')):
            run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided','answer':answer},'calls':[],'trace':[],'elapsed_seconds':1})
            items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':run['id']})
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':items})
        with self.assertRaisesRegex(ValueError,'adjudicated'): compare.report(comp['id'])
        for item in items: compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Test')
        report=compare.report(comp['id'])
        self.assertEqual([row['answer'] for row in report['rows']],['Yes','No'])
        self.assertTrue(report['answer_texts_differ'])
        self.assertIn('not a semantic',report['answer_difference_interpretation'])
    def test_export_is_review_gated_and_contains_pinned_runs(self):
        source=core.snapshot('source','Evidence')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided','answer':'yes'},'calls':[],'trace':[],'elapsed_seconds':1})
        item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q',
            'scope':'','as_of':'','snapshot_id':source['id'],'snapshot_sha256':source['sha256'],'items':[item]})
        with self.assertRaisesRegex(ValueError,'adjudicated'): compare.export_bundle(comp['id'])
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','correct','supported','Evidence')
        bundle=compare.export_bundle(comp['id'])
        self.assertEqual(bundle['source']['sha256'],source['sha256'])
        self.assertEqual(bundle['runs'][0]['record'],run)
        self.assertEqual(bundle['report']['rows'][0]['arm'],'fresh')
    def test_failed_arm_preserves_observed_provider_cost_as_partial(self):
        source=core.snapshot('source','Fact')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'failed'},
            'calls':[{'usage':{'cost':0.02}},{'usage':{'cost':0.03}}], 'elapsed_seconds':1,'trace':[]})
        item={'review_id':uuid.uuid4().hex,'arm':'direct','run_id':run['id']}
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q',
            'scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
        compare.adjudicate(comp['id'],item['review_id'],'Reviewer','unresolved','unclear','Failed')
        row=compare.report(comp['id'])['rows'][0]
        self.assertAlmostEqual(row['observed_provider_cost_usd'],0.05)
        self.assertIsNone(row['cost_usd'])
        self.assertEqual(row['cost_status'],'incomplete')
    def test_blind_review_rejects_source_metadata_drift(self):
        import json
        source=core.snapshot('source','The answer is yes.',observed_at='2026-01-01')
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Question?',
            'scope':'','as_of':'','snapshot_id':source['id'],'snapshot_sha256':source['sha256'],
            'snapshot_metadata_sha256':core.source_metadata_sha256(source),'items':[]})
        source['observed_at']='2020-01-01'
        (core.DATA/'snapshots'/(source['id']+'.json')).write_text(json.dumps(source))
        with self.assertRaisesRegex(ValueError,'source metadata'):
            compare.blind(comp['id'])
    def test_blinding_and_all_reviews_required(self):
        source=core.snapshot('source','The answer is yes.')
        items=[]
        for arm in ('fresh','direct'):
            run=core.save('runs',{'id':uuid.uuid4().hex,'mode':arm,'result':{'status':'decided','answer':'yes','reason':'arm trace'},'calls':[],'elapsed_seconds':1,'trace':[]})
            items.append({'review_id':uuid.uuid4().hex,'arm':arm,'run_id':run['id']})
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Question?','scope':'','as_of':'','snapshot_id':source['id'],'items':items})
        blind=compare.blind(comp['id'])
        self.assertNotIn('fresh',str(blind)); self.assertNotIn('direct',str(blind)); self.assertNotIn('arm trace',str(blind))
        with self.assertRaises(ValueError): compare.report(comp['id'])
        for item in items:
            compare.adjudicate(comp['id'],item['review_id'],'Reviewer','correct','supported','Source says yes')
        report=compare.report(comp['id'])
        self.assertEqual({r['arm'] for r in report['rows']},{'fresh','direct'})
        self.assertTrue(all(r['cost_status']=='incomplete' for r in report['rows']))
        with self.assertRaises(ValueError): compare.adjudicate(comp['id'],items[0]['review_id'],'Reviewer','correct','supported','Duplicate')

if __name__=='__main__': unittest.main()

class StageValidationTests(unittest.TestCase):
    def test_shared_corpus_rejects_remote_fresh_backend_before_calls(self):
        with self.assertRaisesRegex(ValueError,'requires local'):
            compare.create('Question?','0'*32,consent=True,stage='shared-corpus',judge_backend='remote')

class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_deferred_review_includes_reason_and_gaps(self):
        source=core.snapshot('source','Known fact.')
        run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'deferred','answer':None,'reason':'Vendor is missing'},'trace':[{'outcome':'unknown','predicate':{'question':'Is the vendor approved?'}}]})
        c=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Question?','scope':'','as_of':'','snapshot_id':source['id'],'items':[{'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}]})
        result=compare.blind(c['id'])['items'][0]
        self.assertEqual(result['result']['reason'],'Vendor is missing')
        self.assertIn('Is the vendor approved?',result['unresolved_questions'])
    def test_dataset_unblind_waits_for_all_cases(self):
        source=core.snapshot('source','Fact')
        dataset_run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'case_count':2})
        comparisons=[]
        for index in range(2):
            run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided','answer':'yes'},'calls':[],'elapsed_seconds':1,'trace':[]})
            item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':run['id']}
            c=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q','scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
            core.save('dataset_receipts',{'id':uuid.uuid4().hex,'dataset_run_id':dataset_run['id'],'comparison_id':c['id'],'index':index})
            comparisons.append((c,item))
        compare.adjudicate(comparisons[0][0]['id'],comparisons[0][1]['review_id'],'Reviewer','correct','supported','Reason')
        with self.assertRaisesRegex(ValueError,'dataset'): compare.report(comparisons[0][0]['id'])
        with self.assertRaisesRegex(ValueError,'dataset'): compare.export_bundle(comparisons[0][0]['id'])
        compare.adjudicate(comparisons[1][0]['id'],comparisons[1][1]['review_id'],'Reviewer','correct','supported','Reason')
        self.assertEqual(compare.report(comparisons[0][0]['id'])['status'],'adjudicated')
