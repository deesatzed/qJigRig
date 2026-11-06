import pytest

from quix_knowledge.indexing import index_source
from quix_knowledge.labeling import prepare_review, compile_review
from quix_knowledge.store import open_catalog


def test_review_can_include_proposals_but_label_only_matched_units(tmp_path):
    db=open_catalog(':memory:')
    source=tmp_path/'manual.txt'; source.write_text('Retry after timeout.\n\nRecord the failure.')
    index_source(db,source)
    task=[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'development'}]
    packet=prepare_review(db,task,include_proposed=True,candidate_scope='sections_and_records')
    assert packet['candidate_scope'] == 'sections_and_records'
    assert {c['record_type'] for c in packet['candidates']} == {'section'}
    packet['reviewer']='fixture reviewer'
    packet['tasks'][0]['reviewed']=True
    packet['tasks'][0]['labels']=[packet['candidates'][0]['id']]
    compiled=compile_review(db,packet)
    assert compiled['candidate_scope'] == 'sections_and_records'
    from quix_knowledge.experiment import run_reviewed_experiment
    with pytest.raises(ValueError,match='matched'):
        run_reviewed_experiment(db,compiled)
    report=run_reviewed_experiment(db,compiled,matched_candidates=True)
    assert report['manifest']['candidate_scope'] == 'sections_and_records'
    altered=dict(packet,candidate_scope='variant_specific')
    with pytest.raises(ValueError,match='candidate'):
        compile_review(db,altered)
