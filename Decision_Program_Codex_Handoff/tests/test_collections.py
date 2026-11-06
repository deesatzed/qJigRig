import tempfile
import unittest
from pathlib import Path
from workbench import core, collections

class CollectionsTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
    def tearDown(self): core.DATA=self.old; self.tmp.cleanup()
    def test_new_collection_pins_member_origin_and_metadata(self):
        import json
        a=core.snapshot('A','Evidence A.',origin='https://example.invalid/v1')
        b=core.snapshot('B','Evidence B.',origin='Archive B')
        collection=collections.create('Both',[a['id'],b['id']])
        self.assertEqual(collection['members'][0]['origin'],a['origin'])
        self.assertEqual(collection['members'][0]['source_metadata_sha256'],core.source_metadata_sha256(a))
        a['origin']='https://example.invalid/changed'
        (core.DATA/'snapshots'/(a['id']+'.json')).write_text(json.dumps(a))
        with self.assertRaisesRegex(ValueError,'metadata'):
            core.load('snapshots',collection['id'])
    def test_legacy_collection_remains_readable_without_member_metadata_hash(self):
        import json
        a=core.snapshot('A','Evidence A.',origin='Original')
        collection=collections.create('Collection',[a['id']])
        for member in collection['members']:
            member.pop('origin');member.pop('source_metadata_sha256')
        (core.DATA/'snapshots'/(collection['id']+'.json')).write_text(json.dumps(collection))
        a['origin']='Changed'
        (core.DATA/'snapshots'/(a['id']+'.json')).write_text(json.dumps(a))
        self.assertEqual(core.load('snapshots',collection['id'])['id'],collection['id'])
    def test_new_experiments_reject_legacy_unpinned_collection(self):
        import json
        from unittest.mock import patch
        from workbench import compare,datasets
        source=core.snapshot('A','Evidence.')
        collection=collections.create('Collection',[source['id']])
        for member in collection['members']:
            member.pop('origin');member.pop('source_metadata_sha256')
        (core.DATA/'snapshots'/(collection['id']+'.json')).write_text(json.dumps(collection))
        case={'case_id':'c','question':'Question?','snapshot_id':collection['id']}
        with self.assertRaisesRegex(ValueError,'member metadata'):
            datasets.freeze('new set',[case])
        frozen_case={**case,'snapshot_sha256':collection['sha256'],
                     'snapshot_metadata_sha256':core.source_metadata_sha256(collection)}
        with self.assertRaisesRegex(ValueError,'member metadata'):
            datasets.verify_case_source(frozen_case)
        with patch('workbench.core.config',return_value={'OPENROUTER_PLANNER_MODEL':'test/small','OPENROUTER_TOP_MODEL':'test/top'}), \
             patch('workbench.core.call_model',side_effect=AssertionError('provider must not be called')):
            with self.assertRaisesRegex(ValueError,'member metadata'):
                compare.create('Question?',collection['id'],consent=True)
        self.assertEqual(core.records('comparison_intents'),[])
    def test_direct_answer_accepts_separately_mapped_member_passages(self):
        import json
        from unittest.mock import patch
        a=core.snapshot('A','Alpha provides function X.')
        b=core.snapshot('B','Beta provides function Y.')
        c=collections.create('Both',[a['id'],b['id']])
        response={'status':'decided','answer':'Yes','quotes':['Alpha provides function X.','Beta provides function Y.'],'reason':'Both are documented.'}
        with patch('workbench.core.call_model',return_value=(json.dumps(response),{'usage':{}})):
            run=core.run('Are both functions provided?',c['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'decided')
        self.assertEqual([x['source_id'] for x in run['result']['source_refs']],[a['id'],b['id']])
        from workbench import compare
        import uuid
        comp=core.save('comparisons',{'id':uuid.uuid4().hex,'stage':'shared-evidence','question':'Q','scope':'','as_of':'','snapshot_id':c['id'],'items':[{'review_id':uuid.uuid4().hex,'arm':'direct','run_id':run['id']}]})
        blinded=compare.blind(comp['id'])['items'][0]['result']
        self.assertEqual(blinded['quotes'],response['quotes'])
        self.assertEqual([x['source_id'] for x in blinded['source_refs']],[a['id'],b['id']])
        response['quotes']=['function X.\n\nBeta']
        with patch('workbench.core.call_model',return_value=(json.dumps(response),{'usage':{}})):
            run=core.run('Are both functions provided?',c['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'failed')
    def test_direct_repairs_one_invalid_citation_with_recorded_calls(self):
        import json
        from unittest.mock import patch
        source=core.snapshot('A','The blue widget is enabled.')
        bad={'status':'decided','answer':'Yes','quotes':['The blue widget is enabled']}
        good={'status':'decided','answer':'Yes','quotes':['The blue widget is enabled.']}
        # The initial excerpt is fabricated, and the repair must produce an exact source span.
        bad['quotes']=['The blue widgets are enabled.']
        responses=[(json.dumps(x),{'usage':{}}) for x in (bad,good)]
        with patch('workbench.core.call_model',side_effect=responses):
            run=core.run('Is the blue widget enabled?',source['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'decided')
        self.assertEqual([r['stage'] for r in run['model_responses']],['direct_answer','direct_repair'])
        self.assertEqual(len(run['calls']),2)
        self.assertEqual(run['result']['quotes'],good['quotes'])
    def test_deferred_answer_cannot_smuggle_unvalidated_legacy_citation(self):
        import json
        from unittest.mock import patch
        source=core.snapshot('A','Known source.')
        response={'status':'deferred','answer':None,'quotes':[], 'quote':'Invented source.',
                  'source_ref':{'source_id':'forged'},'citations':[{'url':'https://example.invalid'}], 'reason':'No evidence.'}
        with patch('workbench.core.call_model',return_value=(json.dumps(response),{'usage':{}})):
            run=core.run('Is this true?',source['id'],mode='direct',consent=True)
        self.assertEqual(run['result']['status'],'deferred')
        self.assertFalse(run['result'].get('quote'))
        self.assertFalse(run['result'].get('source_ref'))
        self.assertNotIn('citations',run['result'])
        self.assertIn('Invented source.',run['model_responses'][0]['text'])
    def test_direct_decision_requires_nonempty_answer(self):
        import json
        from unittest.mock import patch
        source=core.snapshot('A','Known source.')
        for value in ('', None, ['Yes']):
            response={'status':'decided','answer':value,'quotes':['Known source.']}
            with self.subTest(value=value), patch('workbench.core.call_model',return_value=(json.dumps(response),{'usage':{}})):
                run=core.run('Is this true?',source['id'],mode='direct',consent=True)
                self.assertEqual(run['result']['status'],'failed')
    def test_member_citations_and_boundary_rejection(self):
        a=core.snapshot('Rule','A permit is required.',scope='policy')
        b=core.snapshot('Exception','Schools are exempt.',scope='policy')
        c=collections.create('Policy collection',[a['id'],b['id']])
        ref=collections.quote_ref(c,'Schools are exempt.')
        self.assertEqual(ref['source_id'],b['id'])
        self.assertEqual(ref['source_start'],0)
        with self.assertRaises(ValueError): collections.quote_ref(c,'required.\n\nSchools')
        with self.assertRaises(ValueError): core.derive_snapshot(c['id'],'bad','changed','test')
    def test_mismatched_scope_or_date_cannot_be_combined(self):
        a=core.snapshot('A','rule',scope='a')
        b=core.snapshot('B','exception',scope='b')
        with self.assertRaises(ValueError): collections.create('bad',[a['id'],b['id']])
        c=core.snapshot('C','future',scope='a',effective_from='2025-01-01')
        with self.assertRaises(ValueError): collections.create('bad',[a['id'],c['id']])
    def test_missing_pinned_member_rejected(self):
        a=core.snapshot('A','rule'); b=core.snapshot('B','exception')
        c=collections.create('collection',[a['id'],b['id']])
        (core.DATA/'snapshots'/(b['id']+'.json')).unlink()
        with self.assertRaises(FileNotFoundError): core.load('snapshots',c['id'])
