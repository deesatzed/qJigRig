import tempfile
import json
import unittest
import uuid
from pathlib import Path
from workbench import core, compare, datasets

class CaseReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.source=core.snapshot('source','Evidence.')
        self.run=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'deferred','answer':None},'calls':[],'elapsed_seconds':1,'trace':[]})
        self.item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':self.run['id']}
        self.comp=core.save('comparisons',{'id':uuid.uuid4().hex,'schema_version':2,'stage':'shared-evidence','question':'Q?','scope':'','as_of':'','snapshot_id':self.source['id'],'items':[self.item]})
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_case_assessment_precedes_access_to_review_items(self):
        self.assertEqual(compare.blind(self.comp['id'])['items'],[])
        with self.assertRaisesRegex(ValueError,'answerability'):
            compare.adjudicate(self.comp['id'],self.item['review_id'],'Reviewer','unresolved','unclear','Reason')
        compare.assess_case(self.comp['id'],'Reviewer','uncertain','Needs further reference')
        self.assertEqual(len(compare.blind(self.comp['id'])['items']),1)
    def test_legacy_comparison_remains_reviewable(self):
        self.comp['schema_version']=1
        (core.DATA/'comparisons'/(self.comp['id']+'.json')).write_text(json.dumps(self.comp))
        self.assertEqual(len(compare.blind(self.comp['id'])['items']),1)
        compare.adjudicate(self.comp['id'],self.item['review_id'],'Reviewer','unresolved','unclear','Reason')
    def test_answerability_required_before_unblinding(self):
        with self.assertRaisesRegex(ValueError,'answerability'): compare.report(self.comp['id'])
        compare.assess_case(self.comp['id'],'Reviewer','answerable','Evidence establishes an answer','source snapshot: Evidence')
        compare.adjudicate(self.comp['id'],self.item['review_id'],'Reviewer','correct','unclear','Reason')
        self.assertEqual(compare.report(self.comp['id'])['case_assessment']['answerability'],'answerable')
    def test_review_rejects_arm_bound_to_different_source(self):
        compare.assess_case(self.comp['id'],'Reviewer','uncertain','Reason')
        compare.adjudicate(self.comp['id'],self.item['review_id'],'Reviewer','unresolved','unclear','Reason')
        self.run['source_sha256']='0'*64
        (core.DATA/'runs'/(self.run['id']+'.json')).write_text(json.dumps(self.run))
        with self.assertRaisesRegex(ValueError,'source'):
            compare.blind(self.comp['id'])
        with self.assertRaisesRegex(ValueError,'source'):
            compare.report(self.comp['id'])
    def test_coverage_never_counts_deferrals_as_answered(self):
        row={'status':'deferred','verdict':'correct','evidence_support':'unclear'}
        self.assertEqual(datasets.score_category(row,'answerable'),'incorrect')
        self.assertEqual(datasets.score_category(row,'unanswerable'),'correct')
        self.assertEqual(datasets.score_category(row,'uncertain'),'unresolved')
    def test_mismatched_arm_cannot_receive_reviews(self):
        self.comp['snapshot_sha256']=self.source['sha256']
        (core.DATA/'comparisons'/(self.comp['id']+'.json')).write_text(json.dumps(self.comp))
        self.run['source_sha256']='0'*64
        (core.DATA/'runs'/(self.run['id']+'.json')).write_text(json.dumps(self.run))
        with self.assertRaisesRegex(ValueError,'source'):
            compare.assess_case(self.comp['id'],'Reviewer','uncertain','Reason')
        with self.assertRaisesRegex(ValueError,'source'):
            compare.adjudicate(self.comp['id'],self.item['review_id'],'Reviewer','unresolved','unclear','Reason')
        self.assertEqual(core.records('case_assessments'),[])
        self.assertEqual(core.records('adjudications'),[])
    def test_current_comparison_requires_complete_arm_source_binding(self):
        self.comp['snapshot_sha256']=self.source['sha256']
        self.comp['snapshot_metadata_sha256']=core.source_metadata_sha256(self.source)
        (core.DATA/'comparisons'/(self.comp['id']+'.json')).write_text(json.dumps(self.comp))
        with self.assertRaisesRegex(ValueError,'source.*missing'):
            compare.blind(self.comp['id'])

class DatasetCaseAssessmentTests(unittest.TestCase):
    def test_all_case_assessments_required_and_coverage_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp); source=core.snapshot('source','Evidence.')
                data=datasets.freeze('fixture',[{'case_id':'one','question':'Q1','snapshot_id':source['id']},{'case_id':'two','question':'Q2','snapshot_id':source['id']}])
                job=core.save('dataset_runs',{'id':uuid.uuid4().hex,'dataset_id':data['id'],'dataset_sha256':data['sha256'],'case_count':2})
                cases=[]
                for i in range(2):
                    r=core.save('runs',{'id':uuid.uuid4().hex,'result':{'status':'decided' if i==0 else 'deferred','answer':'yes' if i==0 else None},'calls':[],'elapsed_seconds':1,'trace':[]})
                    item={'review_id':uuid.uuid4().hex,'arm':'fresh','run_id':r['id']}
                    c=core.save('comparisons',{'id':uuid.uuid4().hex,'schema_version':2,'stage':'shared-evidence','question':f'Q{i+1}','scope':'','as_of':'','snapshot_id':source['id'],'items':[item]})
                    core.save('dataset_receipts',{'id':uuid.uuid4().hex,'dataset_run_id':job['id'],'comparison_id':c['id'],'index':i,'case_id':data['cases'][i]['case_id']})
                    cases.append(c)
                compare.assess_case(cases[0]['id'],'Reviewer','answerable','Review','Source')
                with self.assertRaisesRegex(ValueError,'adjudicated'): compare.report(cases[0]['id'])
                compare.assess_case(cases[1]['id'],'Reviewer','answerable','Review','Source')
                for c in cases:
                    compare.adjudicate(c['id'],c['items'][0]['review_id'],'Reviewer','correct','supported','Fixture review')
                score=datasets.score(job['id'])['arms']['fresh']
                self.assertEqual(score['answerable_cases_assessed'],2)
                self.assertEqual(score['decisions_on_answerable'],1)
                self.assertEqual(score['coverage_on_assessed_answerable'],0.5)
                self.assertEqual(score['incorrect'],1)
            finally: core.DATA=old
