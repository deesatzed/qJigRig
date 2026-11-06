import json
from pathlib import Path

import pytest


def test_isolated_study_uses_copies_and_detects_snapshot_changes(tmp_path):
    import shutil
    import sqlite3
    from quix_knowledge.hitm import _check_sources, SourceChanged
    from quix_knowledge.retrieval_study import prepare_study
    source_root=Path(__file__).resolve().parents[1]
    manifest_path=source_root/'experiments/retrieval/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    original=tmp_path/'original'; original.mkdir()
    for source in manifest['sources']:
        target=original/source['path']; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source_root/source['path'],target)
    output=tmp_path/'study'
    summary=prepare_study(original,manifest_path,output,isolated_sources=True)
    db=sqlite3.connect(output/'catalog.db'); db.row_factory=sqlite3.Row
    try:
        paths=[Path(row['path']) for row in db.execute("select path from sources where status='current'")]
        assert paths and all(path.is_relative_to(output) for path in paths)
        assert summary['source_mode']=='isolated_copy'
        assert len(summary['source_snapshot'])==len(manifest['sources'])
        project=next(s for s in manifest['sources'] if s['kind']=='project')
        (original/project['path']).write_text('original changed')
        _check_sources(db)
        (output/'source-snapshot'/project['path']).write_text('snapshot changed')
        with pytest.raises(SourceChanged): _check_sources(db)
    finally: db.close()


def test_isolated_study_rejects_altered_nonindexed_template_before_running(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study, run_prepared_study
    root=Path(__file__).resolve().parents[1]
    manifest=root/'experiments/retrieval/manifest.json'
    study=tmp_path/'study'; prepare_study(root,manifest,study,isolated_sources=True)
    template=study/'source-snapshot/experiments/retrieval/fixtures/stale-original.txt'
    template.write_text('tampered template')
    output=tmp_path/'run'
    with pytest.raises(ValueError,match='snapshot'):
        run_prepared_study(root,manifest,study,output,switch_runner=lambda _: {},count_tokens=len,tokenizer_name='fixture',packet_tokens=10000)
    assert not output.exists()


def test_isolated_preparation_rechecks_templates_after_role_model_calls(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    output=tmp_path/'study'; count=0
    def provider(*_):
        nonlocal count
        count+=1
        if count==1:
            (output/'source-snapshot/experiments/retrieval/fixtures/stale-original.txt').write_text('changed during scoring')
        return {'outcome':'unclear','provider':'fixture','model':'fixture','probability':0.5}
    with pytest.raises(ValueError,match='snapshot'):
        prepare_study(root,root/'experiments/retrieval/manifest.json',output,isolated_sources=True,role_provider=provider,role_call_limit=56)
    assert not (output/'blind-review-packet.json').exists()


def test_preregistered_study_creates_blind_packet_with_lifecycle_fixtures(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    output=tmp_path/'study'
    summary=prepare_study(root,root/'experiments/retrieval/manifest.json',output)
    packet=json.loads((output/'blind-review-packet.json').read_text())
    assert summary['tasks'] == 16
    assert summary['candidate_scope'] == 'sections_and_records'
    assert all(task['labels'] is None and not task['reviewed'] for task in packet['tasks'])
    assert not any(candidate['record_type']=='generated_index' for candidate in packet['candidates'])
    by_id={candidate['id']:candidate for candidate in packet['candidates']}
    assert by_id['synthetic-stale-finding']['evidence_status'] == 'stale'
    assert by_id['synthetic-unsupported-finding']['evidence_status'] == 'unsupported'
    assert by_id['synthetic-conflicting-finding']['evidence_status'] == 'current'
    with pytest.raises(FileExistsError):
        prepare_study(root,root/'experiments/retrieval/manifest.json',output)


def test_study_rejects_changed_source_before_creating_catalog(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study
    root=tmp_path/'root'; root.mkdir()
    (root/'source.txt').write_text('changed')
    manifest={'schema':'quix-retrieval-study-v1','sources':[{'path':'source.txt','sha256':'a'*64,'kind':'project'}],'groups':{'g':'development'},'roles':{'reviewer':{'version':'1'}},'tasks':[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'development','group':'g'}]}
    path=root/'manifest.json'; path.write_text(json.dumps(manifest))
    output=tmp_path/'out'
    with pytest.raises(ValueError,match='source revision'):
        prepare_study(root,path,output)
    assert not output.exists()


def test_unlabeled_study_run_uses_copy_and_reports_no_quality(tmp_path):
    import hashlib
    from quix_knowledge.retrieval_study import prepare_study, run_prepared_study
    root=Path(__file__).resolve().parents[1]
    manifest=root/'experiments/retrieval/manifest.json'
    study=tmp_path/'study'; prepare_study(root,manifest,study)
    original=(study/'catalog.db').read_bytes()
    def switch(snapshot):
        candidate=next(c for c in snapshot['candidates'] if c['record_type']=='section')
        return {'status':'complete','reason':None,'state':{'evidence':[{'id':candidate['id'],'text':candidate['body'],'truncated':candidate['body_truncated']}]},'receipts':[]}
    result=run_prepared_study(root,manifest,study,tmp_path/'run',switch_runner=switch,count_tokens=len,tokenizer_name='fixture-characters',packet_tokens=10000)
    assert result['manifest']['label_provenance']['kind'] == 'unreviewed'
    assert result['manifest']['study']['source_mode']=='original_paths'
    assert result['variants']['baseline']['metrics']['unlabeled'] == 16
    assert result['variants']['switch']['metrics']['mean_recall'] is None
    assert hashlib.sha256((study/'catalog.db').read_bytes()).digest() == hashlib.sha256(original).digest()
    assert (tmp_path/'run'/'report.json').exists()


def test_study_rejects_changed_blind_task_even_if_stored_digest_is_unchanged(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study, run_prepared_study
    root=Path(__file__).resolve().parents[1]
    manifest=root/'experiments/retrieval/manifest.json'
    study=tmp_path/'study'; prepare_study(root,manifest,study)
    path=study/'blind-review-packet.json'
    packet=json.loads(path.read_text()); packet['tasks'][0]['query']='different task'; path.write_text(json.dumps(packet))
    with pytest.raises(ValueError,match='packet'):
        run_prepared_study(root,manifest,study,tmp_path/'run',switch_runner=lambda _: {},count_tokens=len,tokenizer_name='fixture',packet_tokens=10000)


def test_role_scoring_precedes_blind_packet_and_covers_all_eligible_units(tmp_path):
    import sqlite3
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    calls=[]
    def provider(state,question):
        calls.append((state['role'],question))
        return {'outcome':'unclear','provider':'fixture','model':'fixture','probability':0.7,'usage':{'cost':0.01}}
    output=tmp_path/'scored'
    summary=prepare_study(root,root/'experiments/retrieval/manifest.json',output,role_provider=provider,role_call_limit=56)
    packet=json.loads((output/'blind-review-packet.json').read_text())
    db=sqlite3.connect(output/'catalog.db')
    try:
        assert db.execute('select count(*) from role_annotations').fetchone()[0]==56
        assert summary['role_scoring']['calls']==56
        assert summary['role_scoring']['reported_cost']==pytest.approx(.56)
        assert len(calls)==56 and {x[0] for x in calls}=={'implementer','reviewer'}
        assert all(x[1]=='role usefulness' for x in calls)
        assert packet['corpus_revision']==summary['corpus_revision']
        assert all(t['labels'] is None for t in packet['tasks'])
    finally: db.close()


def test_role_scoring_refuses_insufficient_cap_before_any_model_calls(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    calls=[]
    with pytest.raises(ValueError,match='call limit'):
        prepare_study(root,root/'experiments/retrieval/manifest.json',tmp_path/'out',role_provider=lambda *x:calls.append(x),role_call_limit=1)
    assert not calls


def test_role_scoring_provider_failure_stays_unknown_and_has_unknown_cost(tmp_path):
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    def fail(*_): raise TimeoutError()
    summary=prepare_study(root,root/'experiments/retrieval/manifest.json',tmp_path/'unknown',role_provider=fail,role_call_limit=56)
    assert summary['role_scoring']['unknown']==56
    assert summary['role_scoring']['annotations']==0
    assert summary['role_scoring']['reported_cost'] is None
