"""Prepare a frozen, blind retrieval study without claiming independent labels."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .hitm import _check_sources
from .decisions import assess_role
from .indexing import index_source
from .ingest import ingest
from .labeling import compile_review, prepare_review
from .records import add_record
from .store import corpus_fingerprint, open_catalog
from .switch_comparison import run_switch_comparison


def verify_source_snapshot(study, preparation, manifest):
    """Verify every copied input, including templates not indexed as live sources."""
    if preparation.get('source_mode') != 'isolated_copy':
        return
    root=Path(study).resolve()
    expected=[]
    for source in manifest.get('sources',[]):
        name=source['path']
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('invalid snapshot path')
        expected.append({'source':name,'snapshot':str(Path('source-snapshot')/name),
            'sha256':source['sha256'],'kind':source['kind']})
    if preparation.get('source_snapshot') != expected:
        raise ValueError('source snapshot manifest differs')
    for item in expected:
        path=(root/item['snapshot']).resolve()
        if not path.is_relative_to(root/'source-snapshot'):
            raise ValueError('snapshot path escapes study')
        try:
            text=path.read_text(encoding='utf-8')
        except (OSError,UnicodeError) as exc:
            raise ValueError('source snapshot unavailable') from exc
        if hashlib.sha256(text.encode('utf-8')).hexdigest()!=item['sha256']:
            raise ValueError('source snapshot changed')


def prepare_study(root, manifest_path, output, *, role_provider=None, role_call_limit=None, isolated_sources=False):
    root=Path(root).resolve()
    manifest_path=Path(manifest_path)
    raw=manifest_path.read_bytes()
    manifest=json.loads(raw)
    if manifest.get('schema') != 'quix-retrieval-study-v1':
        raise ValueError('invalid study manifest')
    sources=manifest.get('sources')
    tasks=manifest.get('tasks')
    groups=manifest.get('groups',{})
    roles=manifest.get('roles',{})
    if type(isolated_sources) is not bool:
        raise ValueError('isolated_sources must be boolean')
    if role_provider is not None and (not callable(role_provider) or type(role_call_limit) is not int or not 0 < role_call_limit <= 200):
        raise ValueError('role scoring requires a bounded call limit')
    if not isinstance(sources,list) or not sources or not isinstance(tasks,list) or not tasks:
        raise ValueError('study sources and tasks are required')
    if len({item.get('id') for item in tasks}) != len(tasks):
        raise ValueError('duplicate task ID')
    for task in tasks:
        role=roles.get(task.get('role'),{})
        if groups.get(task.get('group')) != task.get('split') or role.get('version') != task.get('role_version') or task.get('labels') is not None:
            raise ValueError('invalid task grouping, role version or prior label')
    files={}
    for source in sources:
        if not isinstance(source,dict) or source.get('kind') not in ('project','synthetic','synthetic_lifecycle_template') or not isinstance(source.get('path'),str) or source['path'] in files:
            raise ValueError('invalid source declaration')
        if isolated_sources and (Path(source['path']).is_absolute() or '..' in Path(source['path']).parts):
            raise ValueError('isolated source path must be relative')
        path=(root/source['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('source path escapes project root')
        try:
            body=path.read_text(encoding='utf-8')
        except (OSError,UnicodeError) as exc:
            raise ValueError('study source unavailable') from exc
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != source.get('sha256'):
            raise ValueError('study source revision changed')
        files[source['path']]=(path,body,source['kind'])
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    output=output.resolve()
    source_snapshot=[]
    if isolated_sources:
        for name,(_,body,kind) in list(files.items()):
            snapshot=output/'source-snapshot'/name
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            with snapshot.open('x',encoding='utf-8',newline='\n') as stream:
                stream.write(body)
            files[name]=(snapshot,body,kind)
            source_snapshot.append({'source':name,'snapshot':str(snapshot.relative_to(output)),
                'sha256':hashlib.sha256(body.encode('utf-8')).hexdigest(),'kind':kind})
    db=open_catalog(output/'catalog.db')
    try:
        source_ids={}
        for name,(path,_,kind) in files.items():
            if kind != 'synthetic_lifecycle_template':
                result=index_source(db,path)
                if not result.get('source_id') or result.get('status') == 'source_changed':
                    raise ValueError('study source could not be indexed')
                source_ids[name]=result['source_id']
        conflict='experiments/retrieval/fixtures/conflicting-finding.md'
        old='experiments/retrieval/fixtures/stale-original.txt'
        current='experiments/retrieval/fixtures/stale-current.txt'
        if any(name not in files for name in (conflict,old,current)):
            raise ValueError('required synthetic lifecycle fixtures missing')
        section=db.execute('SELECT id FROM sections WHERE source_id=? ORDER BY id LIMIT 1',(source_ids[conflict],)).fetchone()
        if section is None:
            raise ValueError('conflict fixture has no source section')
        add_record(db,'synthetic-conflicting-finding','finding','Synthetic agent claim: the retry limit is five attempts.','synthetic-fixture',evidence=[section['id']])
        add_record(db,'synthetic-unsupported-finding','finding','Synthetic agent claim: the retry limit is ten attempts.','synthetic-fixture')
        lifecycle=output/'stale-policy.txt'
        lifecycle.write_text(files[old][1],encoding='utf-8')
        old_id=ingest(db,lifecycle)
        old_section=db.execute('SELECT id FROM sections WHERE source_id=? ORDER BY id LIMIT 1',(old_id,)).fetchone()
        if old_section is None:
            raise ValueError('old lifecycle fixture has no source section')
        add_record(db,'synthetic-stale-finding','finding','Synthetic agent claim based on the old five-attempt limit.','synthetic-fixture',evidence=[old_section['id']])
        lifecycle.write_text(files[current][1],encoding='utf-8')
        if not ingest(db,lifecycle):
            raise ValueError('current lifecycle fixture could not be indexed')
        _check_sources(db)
        role_scoring=None
        if role_provider is not None:
            section_ids=[row[0] for row in db.execute("SELECT s.id FROM sections s JOIN sources x ON x.id=s.source_id WHERE x.status='current' ORDER BY s.id")]
            record_ids=[row[0] for row in db.execute("""SELECT r.id FROM records r WHERE r.status IN ('current','proposed') AND NOT EXISTS
                (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current') ORDER BY r.id""")]
            targets=section_ids+record_ids
            planned=len(targets)*len(roles)
            if planned>role_call_limit:
                raise ValueError('role scoring exceeds call limit')
            results=[]
            for role in sorted(roles):
                definition=roles[role]
                for target in targets:
                    _check_sources(db)
                    results.append(assess_role(db,target,role,definition['version'],definition['purpose'],role_provider))
                    _check_sources(db)
                    if isolated_sources:
                        verify_source_snapshot(output,{'source_mode':'isolated_copy','source_snapshot':source_snapshot},manifest)
            costs=[(item.get('usage') or {}).get('cost') for item in results]
            role_scoring={'scope':'all_current_sections_and_nonstale_records','roles':sorted(roles),'targets':len(targets),
                'call_limit':role_call_limit,'calls':len(results),'unknown':sum(item['outcome']=='unknown' for item in results),
                'annotations':db.execute('SELECT count(*) FROM role_annotations').fetchone()[0],
                'reported_cost':sum(costs) if costs and all(isinstance(c,(int,float)) and not isinstance(c,bool) and c>=0 for c in costs) else None,
                'models':sorted({item.get('model') for item in results if isinstance(item.get('model'),str)}),
                'status':'proposed_uncalibrated'}
        if isolated_sources:
            verify_source_snapshot(output,{'source_mode':'isolated_copy','source_snapshot':source_snapshot},manifest)
        packet=prepare_review(db,tasks,include_proposed=True,candidate_scope='sections_and_records')
        (output/'blind-review-packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
        summary={'schema':'quix-retrieval-preparation-v1','manifest_sha256':hashlib.sha256(raw).hexdigest(),
            'corpus_revision':packet['corpus_revision'],'task_contract_sha256':packet['task_contract_sha256'],
            'tasks':len(packet['tasks']),'candidates':len(packet['candidates']),'candidate_scope':packet['candidate_scope'],
            'labels':'unreviewed','synthetic_records':['synthetic-conflicting-finding','synthetic-unsupported-finding','synthetic-stale-finding'],
            'role_scoring':role_scoring,'source_mode':'isolated_copy' if isolated_sources else 'original_paths',
            'source_snapshot':source_snapshot if isolated_sources else None}
        (output/'preparation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        return summary
    finally:
        db.close()


def run_prepared_study(root, manifest_path, study, output, *, switch_runner, count_tokens, tokenizer_name, packet_tokens, provider=None, reviewed_packet=None):
    """Run against a copy; the original review packet and catalog are unchanged."""
    root=Path(root).resolve()
    manifest_bytes=Path(manifest_path).read_bytes()
    manifest=json.loads(manifest_bytes)
    study=Path(study)
    preparation=json.loads((study/'preparation.json').read_text(encoding='utf-8'))
    packet=json.loads((study/'blind-review-packet.json').read_text(encoding='utf-8'))
    if preparation.get('manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest():
        raise ValueError('study manifest changed since preparation')
    verify_source_snapshot(study,preparation,manifest)
    if packet.get('task_contract_sha256') != preparation.get('task_contract_sha256') or packet.get('corpus_revision') != preparation.get('corpus_revision'):
        raise ValueError('study packet differs from preparation')
    original=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True)
    original.row_factory=sqlite3.Row
    try:
        if original.execute('PRAGMA user_version').fetchone()[0] != 7 or corpus_fingerprint(original) != preparation['corpus_revision']:
            raise ValueError('study catalog differs from preparation')
        _check_sources(original)
        expected=prepare_review(original,manifest['tasks'],include_proposed=True,candidate_scope='sections_and_records')
        fields=('id','query','role','role_version','split')
        try:
            task_contracts=[[task[field] for field in fields] for task in packet['tasks']]
        except (KeyError, TypeError):
            raise ValueError('study packet differs from preparation') from None
        if (any(packet.get(key) != expected[key] for key in ('schema','corpus_revision','task_contract_sha256','include_proposed','candidate_scope','candidates'))
                or task_contracts != [[task[field] for field in fields] for task in expected['tasks']]):
            raise ValueError('study packet differs from preparation')
        if reviewed_packet is not None:
            reviewed=json.loads(Path(reviewed_packet).read_text(encoding='utf-8'))
            compiled=compile_review(original,reviewed)
            if compiled['candidate_scope'] != 'sections_and_records' or not compiled['include_proposed']:
                raise ValueError('reviewed packet does not match study scope')
            if compiled['corpus_revision'] != preparation['corpus_revision'] or reviewed.get('task_contract_sha256') != preparation['task_contract_sha256']:
                raise ValueError('reviewed packet does not match prepared tasks')
            tasks=compiled['tasks']
            provenance=compiled['label_provenance']
        else:
            tasks=[{key:task[key] for key in ('id','query','role','role_version','split')} | {'labels':None} for task in packet['tasks']]
            provenance={'kind':'unreviewed','independent':False}
        output=Path(output)
        output.mkdir(parents=True,exist_ok=False)
        target=sqlite3.connect(output/'catalog-copy.db')
        try:
            original.backup(target)
        finally:
            target.close()
    finally:
        original.close()
    db=open_catalog(output/'catalog-copy.db')
    try:
        cfg=manifest['comparison']
        report=run_switch_comparison(db,tasks,switch_runner=switch_runner,packet_tokens=packet_tokens,count_tokens=count_tokens,tokenizer_name=tokenizer_name,
            limit=cfg['limit'],provider=provider,include_proposed=cfg['include_proposed'],ranking=cfg['ranking'],label_provenance=provenance,
            switch_view_characters=cfg['switch_view_characters'],switch_max_steps=cfg['switch_max_steps'],switch_max_model_calls=cfg['switch_max_model_calls'])
        report['manifest']['study']={'manifest_sha256':preparation['manifest_sha256'],'preparation_corpus_revision':preparation['corpus_revision'],
            'task_contract_sha256':preparation['task_contract_sha256'],'roles':manifest['roles'],'groups':manifest['groups'],
            'role_annotation_count':db.execute('SELECT count(*) FROM role_annotations').fetchone()[0],
            'role_scoring':preparation.get('role_scoring'),
            'source_mode':preparation.get('source_mode','not_recorded'),
            'source_snapshot':preparation.get('source_snapshot'),
            'preregistered_packet_tokens':cfg['packet_tokens'],'preregistered_tokenizer':cfg['tokenizer'],
            'budget_deviation':packet_tokens != cfg['packet_tokens'] or tokenizer_name != cfg['tokenizer'],
            'limits':cfg['limits']}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    finally:
        db.close()
