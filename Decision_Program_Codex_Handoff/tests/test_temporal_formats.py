import tempfile
import unittest
from pathlib import Path
from workbench import core, datasets


class TemporalFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = core.DATA
        core.DATA = Path(self.tmp.name)

    def tearDown(self):
        core.DATA = self.old
        self.tmp.cleanup()

    def test_import_normalizes_accepted_iso_formats(self):
        source = core.snapshot('source', 'Evidence', effective_from='20260101',
                               effective_to='2026-W53-7', observed_at='20260102')
        self.assertEqual(source['effective_from'], '2026-01-01')
        self.assertEqual(source['effective_to'], '2027-01-03')
        self.assertEqual(source['observed_at'], '2026-01-02')

    def test_compact_and_week_dates_work_with_python_310_style_parser(self):
        import datetime
        from unittest.mock import patch
        class Date310(datetime.date):
            @classmethod
            def fromisoformat(cls, value):
                if len(value)!=10 or value[4]!='-' or value[7]!='-': raise ValueError('Invalid isoformat string')
                return super().fromisoformat(value)
        with patch.object(core.dt,'date',Date310):
            self.assertEqual(core.canonical_date('20260101'),'2026-01-01')
            self.assertEqual(core.canonical_date('2026-W53-7'),'2027-01-03')
            self.assertEqual(core.canonical_date('2026W537'),'2027-01-03')
            with self.assertRaises(ValueError): core.canonical_date('2026-W537')
            self.assertFalse(core.source_covers_date({'effective_from':'20260201'},'2026-01-31'))

    def test_compact_dates_cannot_bypass_source_effectivity(self):
        source = core.snapshot('source', 'Evidence', effective_from='2026-02-01')
        with self.assertRaisesRegex(ValueError, 'date'):
            datasets.freeze('set', [{'case_id': 'c', 'question': 'Q?',
                                     'snapshot_id': source['id'], 'as_of': '20260131'}])
        run = core.run('Q?', source['id'], as_of='20260131')
        self.assertIn('date', run['result']['reason'])
        self.assertEqual(run['calls'], [])

    def test_legacy_compact_source_metadata_is_compared_as_date(self):
        source = core.snapshot('source', 'Evidence')
        # A legacy record can contain compact metadata; its text hash remains valid.
        path = core.DATA / 'snapshots' / (source['id'] + '.json')
        import json
        source['effective_from'] = '20260201'
        path.write_text(json.dumps(source))
        with self.assertRaisesRegex(ValueError, 'date'):
            datasets.freeze('set', [{'case_id': 'c', 'question': 'Q?',
                                     'snapshot_id': source['id'], 'as_of': '2026-01-31'}])
        dataset = datasets.freeze('set', [{'case_id': 'c', 'question': 'Q?',
                                           'snapshot_id': source['id'], 'as_of': '20261201'}])
        self.assertEqual(dataset['cases'][0]['as_of'], '2026-12-01')
        run = core.run('Q?', source['id'], as_of='2026-01-31')
        self.assertIn('date', run['result']['reason'])
