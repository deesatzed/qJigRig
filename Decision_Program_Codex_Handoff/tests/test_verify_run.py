import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from workbench import core, verify_run
from workbench.collections import quote_ref


class VerifyRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        self.source=core.snapshot('source','The flag is enabled.')
        predicate={'id':'p1','question':'Is the flag enabled?','evidence_requirement':'flag status'}
        plan={'predicates':[predicate],'expression':{'ref':'p1'},'true_answer':'Yes','false_answer':'No','ambiguity':''}
        ref=quote_ref(self.source,'flag is enabled')
        self.run=core.save('runs',{'id':uuid.uuid4().hex,'request':{'snapshot_id':self.source['id']},
            'source_sha256':self.source['sha256'],'source_metadata_sha256':core.source_metadata_sha256(self.source),
            'plan':plan,'trace':[{'predicate':predicate,'outcome':'true','quote':'flag is enabled','source_ref':ref}],
            'candidate_result':{'status':'decided','answer':'Yes'},'result':{'status':'decided','answer':'Yes'}})
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def rewrite(self):
        (core.DATA/'runs'/(self.run['id']+'.json')).write_text(json.dumps(self.run))
    def test_legacy_collection_member_metadata_is_not_fully_verified(self):
        from workbench import collections
        collection=collections.create('legacy',[self.source['id']])
        for member in collection['members']:
            member.pop('origin');member.pop('source_metadata_sha256')
        (core.DATA/'snapshots'/(collection['id']+'.json')).write_text(json.dumps(collection))
        self.run['request']['snapshot_id']=collection['id']
        self.run['source_sha256']=collection['sha256']
        self.run['source_metadata_sha256']=core.source_metadata_sha256(collection)
        self.rewrite()
        result=verify_run.verify(self.run['id'])
        self.assertIn('member metadata not pinned',result['source'])
        self.assertEqual(result['citations'],'verified')
    def test_recomputes_without_provider_and_detects_changed_candidate(self):
        with patch('workbench.core.call_model',side_effect=AssertionError('model call')):
            result=verify_run.verify(self.run['id'])
        self.assertEqual((result['source'],result['citations'],result['composition']),('verified','verified','verified'))
        self.run['candidate_result']['answer']='No'; self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['composition'],'failed')
    def test_detects_changed_citation_and_missing_source_metadata(self):
        self.run['trace'][0]['source_ref']['source_start']+=1; self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['citations'],'failed')
        self.run['trace'][0].pop('source_ref'); self.run.pop('source_metadata_sha256'); self.rewrite()
        result=verify_run.verify(self.run['id'])
        self.assertEqual(result['source'],'text verified; metadata not recorded')
        self.assertEqual(result['citations'],'unavailable; quotes lack references')
    def test_recorded_whitespace_only_citation_is_not_verified(self):
        self.run['trace'][0]['quote']=' '
        self.run['trace'][0]['source_ref']['source_start']=3
        self.run['trace'][0]['source_ref']['source_end']=4
        self.rewrite()
        result=verify_run.verify(self.run['id'])
        self.assertEqual(result['citations'],'failed')
    def test_single_citation_alias_cannot_conflict_with_citation_list(self):
        ref=quote_ref(self.source,'flag is enabled')
        self.run['result'].update({'quotes':['flag is enabled'],'source_refs':[ref],
                                   'quote':'The flag','source_ref':quote_ref(self.source,'The flag')})
        self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['citations'],'failed')
        self.run['result']['quote']='flag is enabled'
        self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['citations'],'failed')
        self.run['result']['source_ref']=ref
        self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['citations'],'verified')
    def test_citation_attribution_must_match_pinned_source(self):
        original=dict(self.run['trace'][0]['source_ref'])
        for field,value in (('source_title','Different source'),('observed_at','1900-01-01')):
            with self.subTest(field=field):
                self.run['trace'][0]['source_ref']={**original,field:value}; self.rewrite()
                result=verify_run.verify(self.run['id'])
                self.assertEqual(result['citations'],'failed')
                self.assertTrue(result['issues'])
        self.run['trace'][0]['source_ref']=dict(original)
        del self.run['trace'][0]['source_ref']['source_title']; self.rewrite()
        self.assertIn('partial',verify_run.verify(self.run['id'])['citations'])
    def test_missing_predicate_evidence_is_not_hidden_by_other_citation(self):
        ref=self.run['trace'][0]['source_ref']
        self.run['trace'][0].pop('quote'); self.run['trace'][0].pop('source_ref')
        self.run['answer_check']={'verdict':'supported','quotes':['flag is enabled'],'source_refs':[ref]}
        self.rewrite()
        result=verify_run.verify(self.run['id'])
        self.assertIn('partial',result['citations'])
        self.assertIn('predicate',result['citations'])
    def test_cli_returns_nonzero_on_failed_verification(self):
        import os, subprocess, sys
        env={**os.environ,'WORKBENCH_DATA':str(core.DATA)}
        command=[sys.executable,'-m','workbench','verify-run',self.run['id']]
        valid=subprocess.run(command,env=env,capture_output=True,text=True)
        self.assertEqual(valid.returncode,0)
        self.run['trace'][0]['source_ref']['source_start']+=1; self.rewrite()
        invalid=subprocess.run(command,env=env,capture_output=True,text=True)
        self.assertNotEqual(invalid.returncode,0)
        self.assertEqual(json.loads(invalid.stdout)['citations'],'failed')
    def test_source_metadata_change_fails_before_recomputation(self):
        path=core.DATA/'snapshots'/(self.source['id']+'.json')
        changed={**self.source,'scope':'different'}; path.write_text(json.dumps(changed))
        result=verify_run.verify(self.run['id'])
        self.assertEqual(result['source'],'failed')
        self.assertEqual(result['composition'],'unavailable')
    def test_trace_predicate_must_match_the_saved_plan(self):
        self.run['trace'][0]['predicate']={**self.run['plan']['predicates'][0],'question':'Different question?'}
        self.rewrite()
        self.assertEqual(verify_run.verify(self.run['id'])['composition'],'failed')
