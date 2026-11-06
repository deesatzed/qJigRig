"""Verify an isolated cascade study and pair exploratory AI reviews."""
import argparse,collections,hashlib,json,math,random,re,sqlite3,statistics
from pathlib import Path
from quix_knowledge.agent_review import validate_review_sources
from quix_knowledge.ai_review_v2 import VERSION,validate_review
from quix_knowledge.hitm import _check_sources
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.research_cascade import unrecognized_hashes
from quix_knowledge.evidence_recovery import add_recovery_notice
from quix_knowledge.store import corpus_fingerprint
p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('study');p.add_argument('review');p.add_argument('output');p.add_argument('--retry');args=p.parse_args()
root=Path(__file__).resolve().parents[2];run=Path(args.run);study=Path(args.study);review=Path(args.review);load=lambda path:json.loads(path.read_text());digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest=load(run/'manifest.json');report=load(run/'agent-report.json');stages=load(run/'stages.json');packets=load(run/'packets.json');schedule=load(run/'schedule.json');prep=load(study/'preparation.json');source=load(study/'blind-review-packet.json');sm=root/'experiments/retrieval/manifest.json';source_manifest=load(sm)
if report['manifest_sha256']!=digest(run/'manifest.json') or report['corpus_revision']!=prep['corpus_revision'] or prep['manifest_sha256']!=digest(sm):raise ValueError('study binding changed')
for key,file in [('stage_sha256','stages.json'),('packets_sha256','packets.json'),('schedule_sha256','schedule.json')]:
    if report.get(key) is not None and report[key]!=digest(run/file):raise ValueError('recorded artifact changed')
verify_source_snapshot(study,prep,source_manifest);db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
try:
    validate_review_sources(db,source,source_manifest['tasks']);_check_sources(db)
    if corpus_fingerprint(db)!=prep['corpus_revision']:raise ValueError('catalog changed')
finally:db.close()
tasks={x['id']:x for x in manifest['tasks']};candidate={x['id']:x for x in source['candidates']}; runs={(x['task_id'],x['condition']):x for x in report['runs']};packetrows={(x['task_id'],x['condition']):x for x in packets};packetmap={k:v['packet'] for k,v in packetrows.items()};expected={(t,c) for t in tasks for c in manifest['conditions']}
if set(runs)!=expected or len(runs)!=len(report['runs']) or set(packetmap)!=expected or len(packetmap)!=len(packets) or set(map(tuple,schedule))!=expected or len(schedule)!=len(expected):raise ValueError('schedule or packet mismatch')
for (tid,condition),packet in packetmap.items():
    t=tasks[tid]; recovery=packetrows[(tid,condition)].get('recovery')
    if packet is None:
        if not recovery or recovery.get('status')!='insufficient_evidence' or runs[(tid,condition)]['status']!='insufficient_evidence':raise ValueError('missing packet without explicit failure')
        continue
    expected_task=t['query']
    if recovery is not None:
        expected_task=add_recovery_notice({'query':t['query'],'context':{'task':t['query']}},recovery)['query']
    if packet['task']!=expected_task or packet['role']!=t['role'] or packet['role_version']!=t['role_version'] or packet['catalog_fingerprint']!=prep['corpus_revision']:raise ValueError('packet task mismatch')
    for item in packet['results']:
        c=candidate.get(item['id'])
        if c is None or c['record_type']!=item['record_type'] or not c['body'].startswith(item['body']):raise ValueError('packet content mismatch')
        for k in ('path','revision','start_line','end_line','page_start','page_end','evidence'):
            if k in item and item[k]!=c.get(k):raise ValueError('packet source mismatch')
blind=load(review/'blind-items.json');key=load(review/'condition-key.json');spec=load(review/'review-spec.json')
completed=[x for x in report['runs'] if x.get('status')=='completed' and isinstance(x.get('output'),str)];random.Random(manifest['seed']+1).shuffle(completed)
expected_blind=[{'blind_id':f'answer-{i:03d}','query':tasks[x['task_id']]['query'],'output':x['output']} for i,x in enumerate(completed,1)]
expected_key={'mapping':{f'answer-{i:03d}':{'task_id':x['task_id'],'condition':x['condition']} for i,x in enumerate(completed,1)},'missing':[{'task_id':x['task_id'],'condition':x['condition'],'status':x['status']} for x in report['runs'] if x not in completed]}
if blind!=expected_blind or key!=expected_key:raise ValueError('blind output or mapping changed')
expected_reviews={('retrieval',tid) for tid in tasks}|{('plan',x['blind_id']) for x in blind};final={};attempts=[]
for i,folder in enumerate([review]+([Path(args.retry)] if args.retry else [])):
    s=load(folder/'review-spec.json')
    if s['schema']!=VERSION or s['run_report_sha256']!=digest(run/'agent-report.json') or s['source_packet_sha256']!=digest(study/'blind-review-packet.json') or s['blind_items_sha256']!=digest(folder/'blind-items.json') or load(folder/'blind-items.json')!=blind or load(folder/'condition-key.json')!=key or s['conditions_not_sent'] is not True:raise ValueError('review contract mismatch')
    if i and (s['retry_of_sha256']!=digest(review/'reviews.jsonl') or s['model']!=spec['model']):raise ValueError('retry mismatch')
    rows=[json.loads(line) for line in (folder/'reviews.jsonl').read_text().splitlines()]
    if len(rows)!=s['calls_planned']:raise ValueError('review incomplete')
    seen=set()
    for row in rows:
        ident=(row['kind'],row['id'])
        if ident not in expected_reviews or ident in seen or (i and (ident not in final or final[ident]['status'] not in ('unknown','uncertain'))):raise ValueError('invalid review identity')
        if row['status'] in ('ai_reviewed','uncertain'):
            verdict=validate_review(ident[0],row.get('verdict'),set(candidate))
            if row.get('used_model')!=spec['model'] or (row['status']=='ai_reviewed')!=(verdict['status']=='complete'):raise ValueError('review status mismatch')
        elif row['status']!='unknown':raise ValueError('invalid review status')
        seen.add(ident);final[ident]=row;attempts.append(row)
    if not i and seen!=expected_reviews:raise ValueError('review set incomplete')
per_condition={};case=[]
for condition in manifest['conditions']:
    outcomes=[];recalls=[]
    for tid,t in tasks.items():
        runrow=runs[(tid,condition)];review_id=next((k for k,v in key['mapping'].items() if v=={'task_id':tid,'condition':condition}),None);rr=final.get(('plan',review_id),{}) if review_id else {}
        labels=final.get(('retrieval',tid),{}); verdict=labels.get('verdict',{}); essential=set(verdict.get('essential_ids',[])) if labels.get('status')=='ai_reviewed' else set(); found={x['id'] for x in (packetmap[(tid,condition)] or {}).get('results',[])}
        if essential:recalls.append(len(essential & found)/len(essential))
        output=runrow.get('output',''); unknown_citations=unrecognized_hashes(output,packetmap[(tid,condition)] or {'results':[]})
        item={'task_id':tid,'run_status':runrow['status'],'review_status':rr.get('status','missing_output'),'review':rr.get('verdict'),'essential_count':len(essential) if essential else None,'essential_ids_found':len(found&essential) if essential else None,'unrecognized_full_hex_tokens':unknown_citations,'call':runrow.get('call'),'escalation_signal':runrow.get('escalation_signal'),'signals':runrow.get('signals'),'recovery':packetrows[(tid,condition)].get('recovery')}
        outcomes.append(item);case.append(item|{'condition':condition})
    per_condition[condition]={'statuses':dict(collections.Counter(x['run_status'] for x in outcomes)),'review_statuses':dict(collections.Counter(x['review_status'] for x in outcomes)),'mean_essential_id_recall_against_ai_labels':statistics.mean(recalls) if recalls else None,'tasks':outcomes}
def money(items):
    vals=[x if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 else None for x in items]
    return {'known_usd':sum(x for x in vals if x is not None),'unknown_count':sum(x is None for x in vals),'calls':len(vals)}
planner_cost=money([(x.get('call') or {}).get('costUSD') for x in report['runs'] if x.get('planner_attempted',x['status'] not in ('unsupported_or_stale_evidence','context_invalid','intent_too_large','insufficient_evidence'))]); review_cost=money([(x.get('usage') or {}).get('cost') for x in attempts]);rerank_cost=money([(x['rerank'].get('usage') or {}).get('cost') for x in stages.values()]);receipts=[i for x in stages.values() for i in (x['switch'].get('receipts') or [])];switch_cost=money([(x.get('usage') or {}).get('cost') for x in receipts]);prompt_tokens={c:[(x.get('call') or {}).get('promptTokens') for x in report['runs'] if x['condition']==c] for c in manifest['conditions']}
summary={'schema':'quix-cascade-pilot-analysis-v1','reviewer_type':'AI, not independently validated','corpus_revision':prep['corpus_revision'],'conditions':per_condition,'retrieval_review_statuses':dict(collections.Counter(final.get(('retrieval',tid),{}).get('status','missing') for tid in tasks)),'costs':{'planner':planner_cost,'rerank':rerank_cost,'reflex':switch_cost,'ai_review':review_cost},'planner_prompt_tokens':prompt_tokens,'switch_statuses':dict(collections.Counter((x['switch']['status'] or 'unknown')+':'+str(x['switch'].get('reason')) for x in stages.values())),'rerank_statuses':dict(collections.Counter(x['rerank']['status'] for x in stages.values())),'recorded_artifact_hashes':{k:('verified' if report.get(k) else 'not_recorded') for k in ('stage_sha256','packets_sha256','schedule_sha256')},'limitations':['Same explored corpus; four new tasks, not independently held out.','AI-generated essential labels and plan assessments are unvalidated proxies.','Exact-ID overlap does not verify that truncated context includes the needed passage.','Full model input budgets and cost differ by condition.','The hex-token check excludes supplied IDs and revision hashes but is not a citation validator; short IDs and paraphrases are not checked.','Evidence source checks are point-in-time.','Shared retrieval stages incur costs once in this experimental design.']}
with Path(args.output).open('x') as f:json.dump(summary,f,indent=2)
print(json.dumps({'conditions':{c:{k:v for k,v in x.items() if k!='tasks'} for c,x in per_condition.items()},'costs':summary['costs'],'switch':summary['switch_statuses'],'review':summary['retrieval_review_statuses']}))
