import unittest
from workbench import retrieval

class RetrievalTests(unittest.TestCase):
    def test_prerelease_version_is_not_a_shorter_version_match(self):
        source='Release candidate 3.9.0rc1.\n\nStable release 3.9.'
        stable=retrieval.search(source,'3.9',limit=5)
        prerelease=retrieval.search(source,'3.9.0rc1',limit=5)
        self.assertEqual([x['text'] for x in stable],['Stable release 3.9.'])
        self.assertEqual([x['text'] for x in prerelease],['Release candidate 3.9.0rc1.'])
        self.assertEqual(retrieval.terms('3.9rc1'),{'3.9rc1'})
        self.assertNotIn('3.9',retrieval.terms('3.9rc1'))
    def test_dotted_version_query_retrieves_exact_version_context(self):
        source=('.. function:: older(x)\n\n   Old feature.\n\n   .. versionadded:: 3.9\n\n'
                '.. function:: newer(x)\n\n   New feature.\n\n   .. versionadded:: 3.10')
        hits=retrieval.search(source,'3.9',limit=5)
        self.assertEqual(len(hits),1)
        self.assertIn('older(x)',hits[0]['text'])
        self.assertIn('versionadded:: 3.9',hits[0]['text'])
        self.assertNotIn('newer(x)',hits[0]['text'])
    def test_rst_description_preserves_preceding_function_directive(self):
        source='.. function:: ISTERMINAL(x)\n\n   Return True for terminal token values.'
        hit=retrieval.search(source,'Which function returns true for terminal token values?',limit=1)[0]
        self.assertEqual(hit['text'],source)
        self.assertEqual(source[hit['start']:hit['end']],hit['text'])
    def test_rst_context_after_prior_paragraph_with_supported_line_endings(self):
        for newline in ('\n','\r\n','\r'):
            with self.subTest(newline=repr(newline)):
                context='.. function:: target(x)'+newline+newline+'   Return True for terminal values.'
                source='Introduction.'+newline+newline+context
                hit=retrieval.search(source,'terminal values',limit=1)[0]
                self.assertEqual(hit['text'],context)
                self.assertEqual(source[hit['start']:hit['end']],context)
    def test_inline_directive_text_is_not_treated_as_heading(self):
        source='Prefix .. function:: target(x)\r\r   Return True for terminal values.'
        hit=retrieval.search(source,'terminal values',limit=1)[0]
        self.assertEqual(hit['text'],'Return True for terminal values.')
    def test_rst_directive_and_combined_passage_do_not_consume_two_slots(self):
        source='.. function:: ISTERMINAL(x)\n\n   Return True for terminal token values.'
        hits=retrieval.search(source,'ISTERMINAL',limit=5)
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['text'],source)
        self.assertEqual(retrieval.search(source,'ISTERMINAL',limit=5,
                         exclude={(hits[0]['start'],hits[0]['end'])}),[])
    def test_rst_version_annotation_remains_with_function_context(self):
        for newline in ('\n','\r\n','\r'):
            with self.subTest(newline=repr(newline)):
                source='.. function:: issoftkeyword(s)'+newline+newline+'   Return True for soft keywords.'+newline+newline+'   .. versionadded:: 3.9'
                hits=retrieval.search(source,'Was issoftkeyword added in Python 3.9?',limit=5)
                self.assertEqual(len(hits),1)
                self.assertEqual(hits[0]['text'],source)
                self.assertEqual(source[hits[0]['start']:hits[0]['end']],source)
    def test_rst_annotation_never_crosses_member_boundary(self):
        first='.. function:: f(x)\n\n   Return True.'; second='   .. versionadded:: 3.9'
        source=first+'\n\n'+second
        hits=retrieval.search(source,'function true',limit=5,boundaries=[(0,len(first)),(len(first)+2,len(source))])
        self.assertTrue(all(not (h['start']<len(first) and h['end']>len(first)) for h in hits))
    def test_rst_context_never_crosses_collection_member_boundary(self):
        heading='.. function:: unrelated(x)'; body='   Return True for terminal token values.'
        source=heading+'\n\n'+body
        hit=retrieval.search(source,'terminal token values',limit=1,
                             boundaries=[(0,len(heading)),(len(heading)+2,len(source))])[0]
        self.assertEqual(hit['text'],'Return True for terminal token values.')
        self.assertGreaterEqual(hit['start'],len(heading)+2)
    def test_windows_and_classic_line_endings_preserve_paragraph_offsets(self):
        for newline in ('\n','\r\n','\r'):
            with self.subTest(newline=repr(newline)):
                source='Alpha apples.'+newline+'  '+newline+'Beta oranges.'
                spans=list(retrieval.spans(source))
                self.assertEqual([s['text'] for s in spans],['Alpha apples.','Beta oranges.'])
                self.assertTrue(all(source[s['start']:s['end']]==s['text'] for s in spans))
                self.assertEqual(retrieval.search(source,'oranges')[0]['text'],'Beta oranges.')
    def test_single_crlf_does_not_split_a_paragraph(self):
        source='Function heading\r\n  Description text.\r\n\r\nAnother paragraph.'
        spans=list(retrieval.spans(source))
        self.assertEqual([s['text'] for s in spans],['Function heading\r\n  Description text.','Another paragraph.'])
        self.assertTrue(all(source[s['start']:s['end']]==s['text'] for s in spans))
    def test_exact_offsets_and_relevance(self):
        source='Apples are red.\n\nSchool events are exempt from permits.\n\nDogs have tails.'
        found=retrieval.search(source,'school events exempt',limit=2)
        self.assertEqual(found[0]['text'],'School events are exempt from permits.')
        self.assertTrue(all(source[x['start']:x['end']]==x['text'] for x in found))
    def test_no_hit_is_not_negative_evidence(self):
        self.assertEqual(retrieval.search('Apples are red.','unrelated elephant',limit=3),[])
    def test_exclusion_and_long_spans(self):
        source=('Alpha '+('x'*1800))+'\n\nBeta alpha exceptions apply.'
        first=retrieval.search(source,'alpha',limit=1,max_chars=300)
        self.assertLessEqual(len(first[0]['text']),300)
        second=retrieval.search(source,'alpha',limit=10,max_chars=300,exclude={(first[0]['start'],first[0]['end'])})
        self.assertNotIn((first[0]['start'],first[0]['end']),{(x['start'],x['end']) for x in second})

class RetrievalRunTests(unittest.TestCase):
    def test_direct_uses_adjacent_exposed_paragraphs_without_hidden_text(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workbench import core
        old=core.DATA
        with tempfile.TemporaryDirectory() as tmp:
            try:
                core.DATA=Path(tmp)
                text='.. function:: issoftkeyword(s)\n\n   Return True if soft keyword.'
                source=core.snapshot('source',text)
                response={'status':'decided','answer':'issoftkeyword','quotes':['.. function:: issoftkeyword(s)\n\nReturn True if soft keyword.']}
                with patch('workbench.core.call_model',return_value=(json.dumps(response),{'usage':{}})):
                    run=core.run('What function issoftkeyword checks a soft keyword?',source['id'],mode='direct',consent=True,evidence_mode='lexical',extra_search=False)
                self.assertEqual(run['result']['status'],'decided')
                self.assertEqual(run['result']['quotes'],[text])
                self.assertEqual(len(run['calls']),1)
            finally: core.DATA=old
    def test_no_match_defers_before_any_model_call(self):
        import tempfile
        from pathlib import Path
        from workbench import core
        with tempfile.TemporaryDirectory() as tmp:
            old=core.DATA
            try:
                core.DATA=Path(tmp)
                source=core.snapshot('unrelated','Apples are red.')
                run=core.run('Does elephant migration occur?',source['id'],consent=True,judge_backend='local',local_threshold=0.9,evidence_mode='lexical')
                self.assertEqual(run['result']['status'],'deferred')
                self.assertEqual(run['calls'],[])
                self.assertIn('not a negative finding',run['result']['reason'])
            finally: core.DATA=old

class ExposedEvidenceTests(unittest.TestCase):
    def test_adjacent_exposed_spans_allow_only_whitespace_gaps(self):
        source='Function heading\n\n   Description text.'
        spans=[{'start':0,'end':16,'text':'Function heading'},
               {'start':21,'end':38,'text':'Description text.'}]
        self.assertTrue(retrieval.exposed_quote(source,spans,source))
        hidden='Function heading\nSECRET\nDescription text.'
        self.assertFalse(retrieval.exposed_quote(hidden,[{'start':0,'end':16,'text':'Function heading'},
                         {'start':24,'end':41,'text':'Description text.'}],hidden))
        self.assertFalse(retrieval.exposed_quote('same',[{'start':5,'end':9,'text':'same'}],'same same',0))
        self.assertFalse(retrieval.exposed_quote('   ',[], '   '))
    def test_citation_must_come_from_exposed_passage(self):
        spans=[{'text':'The alpha rule applies.'}]
        self.assertTrue(retrieval.exposed_quote('alpha rule',spans))
        self.assertFalse(retrieval.exposed_quote('hidden exception',spans))
        self.assertFalse(retrieval.exposed_quote('',spans))
        self.assertFalse(retrieval.exposed_quote('alpha rule applies.\n\nhidden',spans))
