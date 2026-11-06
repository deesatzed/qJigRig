"""Analyze blind AI reviews without presenting them as independent human labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from quix_knowledge.ai_review_v2 import VERSION, RETRIEVAL_PROMPT, PLAN_PROMPT, validate_review, summarize_review
from quix_knowledge.agent_review import _contract, _key_contract, validate_review_sources
from quix_knowledge.agent_analysis import validate_recorded_packets, validate_study_requests, validate_recorded_role_definitions
from quix_knowledge.agent_study import validate_retrieval_replay, validate_replay_evidence
from quix_knowledge.agent_context import build_agent_packets
from quix_knowledge.hitm import _check_sources
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.store import corpus_fingerprint

p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('study');p.add_argument('review');p.add_argument('output');p.add_argument('--retry');args=p.parse_args()
root=Path(__file__).resolve().parents[2];run=Path(args.run);study=Path(args.study);review=Path(args.review)
load=lambda path:json.loads(path.read_text(encoding='utf-8'))
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest=load(run/'manifest.json');report=load(run/'agent-report.json');retrieval=load(run/'retrieval-report.json');packets=load(run/'packets.json');packet=load(run/'outcome-review.json');key=load(run/'outcome-key.json');prep=load(study/'preparation.json');source_packet=load(study/'blind-review-packet.json');source_manifest_path=root/'experiments/retrieval/manifest.json';source_manifest=load(source_manifest_path)
if report['manifest']['sha256']!=digest(run/'manifest.json') or prep['manifest_sha256']!=digest(source_manifest_path) or report['manifest']['corpus_revision']!=prep['corpus_revision']: raise ValueError('manifest or corpus changed')
if _contract(packet)!=key.get('packet_contract_sha256') or _key_contract(key)!=key.get('key_contract_sha256') or packet['source_candidates']!=source_packet['candidates']: raise ValueError('review contract changed')
verify_source_snapshot(study,prep,source_manifest); validate_retrieval_replay(retrieval,manifest['tasks'],prep['corpus_revision']); validate_recorded_packets(report,packets,manifest['tasks']); validate_study_requests(report,packets,manifest['tasks']); validate_recorded_role_definitions(report,manifest['tasks'],source_manifest['roles'])
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
try:
    if corpus_fingerprint(db)!=prep['corpus_revision']: raise ValueError('catalog changed')
    _check_sources(db);validate_review_sources(db,source_packet,source_manifest['tasks']);validate_replay_evidence(db,retrieval,manifest['tasks'])
    rebuilt=build_agent_packets(db,retrieval,manifest['tasks'],body_characters=report['manifest']['context_body_character_limit'],result_limit=report['manifest']['context_result_limit'])
    if {(x['task_id'],x['condition']):x['packet'] for x in packets}!=rebuilt: raise ValueError('packets changed')
finally: db.close()
runmap={(r['task_id'],r['condition']):r for r in report['runs']}
for item in packet['items']:
    mapping=key['conditions'][item['blind_id']]; recorded=runmap[(mapping['task_id'],mapping['condition'])]
    if item['task_id']!=mapping['task_id'] or item['output']!=recorded.get('output') or recorded.get('status')!='completed': raise ValueError('plan output differs')
valid_ids={c['id'] for c in source_packet['candidates']};expected={('retrieval',x['id']) for x in manifest['tasks']}|{('plan',x['blind_id']) for x in packet['items']}
all_attempts=[];final={};model=None
for index,folder in enumerate([review]+([Path(args.retry)] if args.retry else [])):
    spec=load(folder/'review-spec.json')
    if spec.get('schema')!=VERSION or spec.get('retrieval_prompt')!=RETRIEVAL_PROMPT or spec.get('plan_prompt')!=PLAN_PROMPT or spec.get('agent_manifest_sha256')!=digest(run/'manifest.json') or spec.get('agent_report_sha256')!=digest(run/'agent-report.json') or spec.get('review_packet_sha256')!=digest(run/'outcome-review.json') or spec.get('condition_key_sent_to_model') is not False: raise ValueError('AI review contract differs')
    if index and (spec.get('retry_of_sha256')!=digest(review/'reviews.jsonl') or spec.get('model')!=model): raise ValueError('retry contract differs')
    model=spec['model']; rows=[json.loads(line) for line in (folder/'reviews.jsonl').read_text().splitlines()]
    if len(rows)!=spec['calls_planned']: raise ValueError('review journal incomplete')
    seen=set()
    for row in rows:
        ident=(row.get('kind'),row.get('id'))
        if ident not in expected or ident in seen or (index and (ident not in final or final[ident]['status'] not in ('unknown','uncertain'))): raise ValueError('invalid or duplicate review')
        seen.add(ident);all_attempts.append(row)
        if row.get('status') in ('ai_reviewed','uncertain'):
            verdict=validate_review(ident[0],row.get('verdict'),valid_ids)
            if (row['status']=='ai_reviewed') != (verdict['status']=='complete'): raise ValueError('review status mismatch')
            if row.get('used_model')!=model: raise ValueError('review model mismatch')
        elif row.get('status')!='unknown': raise ValueError('invalid review status')
        final[ident]=row
    if not index and seen!=expected: raise ValueError('review set incomplete')
summary=summarize_review(manifest['tasks'],packet,key,list(final.values()),retrieval['variants'])
summary.update(model=model,corpus_revision=prep['corpus_revision'],review_calls=len(all_attempts),
    source_check='source snapshot, catalog, packet, task and output bindings checked; point-in-time only',
    limitations=['AI review is not human validation or calibrated ground truth.','Shared previously explored source corpus; new questions are not an independent held-out study.','Identical packet limits do not match total model input or token costs.','Essential-source labels are model judgments, and exact-ID recall does not verify truncated evidence.'])
with Path(args.output).open('x',encoding='utf-8') as f: json.dump(summary,f,ensure_ascii=False,indent=2)
print(json.dumps({'retrieval_reviewed':sum(final.get(('retrieval',t['id']),{}).get('status')=='ai_reviewed' for t in manifest['tasks']), 'plan_reviews':sum(x.get('status')=='ai_reviewed' for k,x in final.items() if k[0]=='plan'),'unknown':sum(x.get('status')!='ai_reviewed' for x in final.values()),'calls':len(all_attempts),'output':args.output}))
