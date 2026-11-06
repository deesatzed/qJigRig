"""Separate blind AI assessments of source relevance and completed cascade proposals."""
import argparse,concurrent.futures,hashlib,json,os,random,sqlite3
from pathlib import Path
from quix_knowledge.ai_review_v2 import build_review_request,run_review,VERSION
from quix_knowledge.agent_review import validate_review_sources
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.store import corpus_fingerprint

p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('study');p.add_argument('output');p.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env');p.add_argument('--retry');args=p.parse_args()
root=Path(__file__).resolve().parents[2];run=Path(args.run);study=Path(args.study);output=Path(args.output);load=lambda path:json.loads(path.read_text());digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest=load(run/'manifest.json');report=load(run/'agent-report.json');prep=load(study/'preparation.json');source=load(study/'blind-review-packet.json');source_manifest_path=root/'experiments/retrieval/manifest.json';source_manifest=load(source_manifest_path)
if digest(run/'manifest.json')!=report['manifest_sha256'] or digest(source_manifest_path)!=prep['manifest_sha256'] or report['corpus_revision']!=prep['corpus_revision']: raise ValueError('study bindings changed')
verify_source_snapshot(study,prep,source_manifest)
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
try:
    validate_review_sources(db,source,source_manifest['tasks'])
    if corpus_fingerprint(db)!=prep['corpus_revision']:raise ValueError('catalog changed')
finally:db.close()
env={}
for raw in Path(args.env_file).read_text().splitlines():
    line=raw.strip().removeprefix('export ')
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1)
        if k.strip() in ('OPENROUTER_API_KEY','OPENROUTER_REVIEWER_MODEL'):env[k.strip()]=v.strip().strip('\"\'')
model=env.get('OPENROUTER_REVIEWER_MODEL');api_key=env.get('OPENROUTER_API_KEY')
if not model or not api_key or model in (manifest['planner_model'],manifest['escalation_model']):raise ValueError('separate reviewer model required')
taskmap={t['id']:t for t in manifest['tasks']};runs=report['runs'];identities={(x['task_id'],x['condition']) for x in runs}
if len(runs)!=len(identities) or identities!={(t['id'],c) for t in manifest['tasks'] for c in manifest['conditions']}: raise ValueError('run schedule incomplete')
completed=[x for x in runs if x.get('status')=='completed' and isinstance(x.get('output'),str)];random.Random(manifest['seed']+1).shuffle(completed)
blind=[];key={};missing=[]
for index,x in enumerate(completed,1):
    ident=f'answer-{index:03d}';blind.append({'blind_id':ident,'query':taskmap[x['task_id']]['query'],'output':x['output']});key[ident]={'task_id':x['task_id'],'condition':x['condition']}
for x in runs:
    if x not in completed: missing.append({'task_id':x['task_id'],'condition':x['condition'],'status':x['status']})
candidates=[{k:c.get(k) for k in ('id','record_type','title','body','evidence','evidence_status','source_status')} for c in source['candidates']];valid={x['id'] for x in candidates}
work=[('retrieval',t['id'],build_review_request('retrieval',t,candidates)) for t in manifest['tasks']]+[('plan',x['blind_id'],build_review_request('plan',x,candidates)) for x in blind]
if args.retry:
    prior=Path(args.retry); old=load(prior/'review-spec.json')
    if old.get('schema')!=VERSION or old.get('model')!=model or old.get('run_report_sha256')!=digest(run/'agent-report.json') or old.get('source_packet_sha256')!=digest(study/'blind-review-packet.json') or old.get('blind_items_sha256')!=digest(prior/'blind-items.json'): raise ValueError('retry contract mismatch')
    if load(prior/'blind-items.json')!=blind or load(prior/'condition-key.json')!={'mapping':key,'missing':missing}: raise ValueError('blind mapping changed')
    previous=[json.loads(line) for line in (prior/'reviews.jsonl').read_text().splitlines()]
    ids=[(x['kind'],x['id']) for x in previous]
    if len(ids)!=len(set(ids)) or set(ids)!={(k,i) for k,i,_ in work}: raise ValueError('prior review incomplete')
    retry={(x['kind'],x['id']) for x in previous if x['status'] in ('unknown','uncertain')}
    work=[x for x in work if (x[0],x[1]) in retry]
output.mkdir(parents=True,exist_ok=False)
(output/'blind-items.json').write_text(json.dumps(blind,ensure_ascii=False,indent=2));(output/'condition-key.json').write_text(json.dumps({'mapping':key,'missing':missing},indent=2))
spec={'schema':VERSION,'model':model,'review_type':'AI, not independently validated','run_report_sha256':digest(run/'agent-report.json'),'source_packet_sha256':digest(study/'blind-review-packet.json'),'blind_items_sha256':digest(output/'blind-items.json'),'conditions_not_sent':True,'calls_planned':len(work),'retry_of_sha256':digest(Path(args.retry)/'reviews.jsonl') if args.retry else None,'retrieval_system':next((q['system'] for k,_,q in work if k=='retrieval'),None),'plan_system':next((q['system'] for k,_,q in work if k=='plan'),None)}
(output/'review-spec.json').write_text(json.dumps(spec,indent=2))
def call(job):
    kind,ident,request=job; return {'kind':kind,'id':ident,**run_review(request,kind=kind,valid_ids=valid,api_key=api_key,model=model)}
with (output/'reviews.jsonl').open('x') as f:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for i,future in enumerate(concurrent.futures.as_completed([pool.submit(call,x) for x in work]),1):
            row=future.result();f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno());print(json.dumps({'reviewed':i,'total':len(work),'status':row['status']}),flush=True)
verify_source_snapshot(study,prep,source_manifest)
print('AI review complete',flush=True)
