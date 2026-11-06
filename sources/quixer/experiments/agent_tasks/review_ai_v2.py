"""Blind AI review of a completed isolated study; no condition key in model requests."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sqlite3
from quix_knowledge.ai_review_v2 import VERSION, RETRIEVAL_PROMPT, PLAN_PROMPT, build_review_request, run_review
from quix_knowledge.agent_review import _contract, _key_contract, validate_review_sources
from quix_knowledge.retrieval_study import verify_source_snapshot

parser=argparse.ArgumentParser()
parser.add_argument('run'); parser.add_argument('study'); parser.add_argument('output')
parser.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env')
parser.add_argument('--retry',help='prior review directory; retry only unknown or uncertain results once')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2];run=Path(args.run);study=Path(args.study);output=Path(args.output)
load=lambda path:json.loads(path.read_text(encoding='utf-8'))
hashfile=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
manifest=load(run/'manifest.json'); report=load(run/'agent-report.json'); packet=load(run/'outcome-review.json'); key=load(run/'outcome-key.json'); source_packet=load(study/'blind-review-packet.json'); preparation=load(study/'preparation.json'); source_manifest_path=root/'experiments/retrieval/manifest.json'; source_manifest=load(source_manifest_path)
if report['manifest']['sha256']!=hashfile(run/'manifest.json') or preparation['manifest_sha256']!=hashfile(source_manifest_path): raise ValueError('manifest changed')
if _contract(packet)!=key.get('packet_contract_sha256') or _key_contract(key)!=key.get('key_contract_sha256'): raise ValueError('review contract changed')
if packet['source_candidates']!=source_packet['candidates'] or packet['corpus_revision']!=preparation['corpus_revision'] or report['manifest']['corpus_revision']!=packet['corpus_revision']: raise ValueError('sources or catalog differ')
verify_source_snapshot(study,preparation,source_manifest)
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
try: validate_review_sources(db,source_packet,source_manifest['tasks'])
finally: db.close()
env={}
for raw in Path(args.env_file).read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if line.startswith('export '): line=line[7:]
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    if k.strip() in ('OPENROUTER_API_KEY','OPENROUTER_REVIEWER_MODEL'): env[k.strip()]=v.strip().strip('\"\'')
api_key=env.get('OPENROUTER_API_KEY'); model=env.get('OPENROUTER_REVIEWER_MODEL')
if not api_key or not model or model==report['manifest']['model']: raise ValueError('separate reviewer model and API key required')
candidates=[{k:c.get(k) for k in ('id','record_type','title','body','evidence','evidence_status','source_status')} for c in packet['source_candidates']]; valid_ids={c['id'] for c in candidates}
work=[]
for task in manifest['tasks']:
    work.append(('retrieval',task['id'],build_review_request('retrieval',task,candidates)))
for item in packet['items']:
    work.append(('plan',item['blind_id'],build_review_request('plan',{'query':item['task'],'output':item['output']},candidates)))
if args.retry:
    prior=Path(args.retry); old=load(prior/'review-spec.json')
    if old.get('schema')!=VERSION or old.get('retrieval_prompt')!=RETRIEVAL_PROMPT or old.get('plan_prompt')!=PLAN_PROMPT or old.get('agent_manifest_sha256')!=hashfile(run/'manifest.json') or old.get('agent_report_sha256')!=hashfile(run/'agent-report.json') or old.get('review_packet_sha256')!=hashfile(run/'outcome-review.json') or old.get('model')!=model: raise ValueError('retry does not match review contract')
    prior_rows=[json.loads(line) for line in (prior/'reviews.jsonl').read_text(encoding='utf-8').splitlines()]
    identity=[(row.get('kind'),row.get('id')) for row in prior_rows]
    if len(identity)!=len(set(identity)) or set(identity)!={(kind,ident) for kind,ident,_ in work}: raise ValueError('prior review incomplete')
    needed={(row['kind'],row['id']) for row in prior_rows if row.get('status') in ('unknown','uncertain')}
    work=[job for job in work if (job[0],job[1]) in needed]
output.mkdir(parents=True,exist_ok=False)
spec={'schema':VERSION,'review_type':'AI, not human; uncalibrated','model':model,'planner_model':report['manifest']['model'],
      'catalog_revision':packet['corpus_revision'],'agent_manifest_sha256':hashfile(run/'manifest.json'),
      'agent_report_sha256':hashfile(run/'agent-report.json'),'review_packet_sha256':hashfile(run/'outcome-review.json'),
      'retrieval_prompt':RETRIEVAL_PROMPT,'plan_prompt':PLAN_PROMPT,'condition_key_sent_to_model':False,
      'reasoning_enabled':False,'max_output_tokens':3000,'calls_planned':len(work),'retry_of_sha256':hashfile(Path(args.retry)/'reviews.jsonl') if args.retry else None}
(output/'review-spec.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
def call(job):
    kind,ident,request=job
    return {'kind':kind,'id':ident,**run_review(request,kind=kind,valid_ids=valid_ids,api_key=api_key,model=model)}
with (output/'reviews.jsonl').open('x',encoding='utf-8') as stream:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for i,future in enumerate(concurrent.futures.as_completed([pool.submit(call,job) for job in work]),1):
            row=future.result();stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
            print(json.dumps({'completed':i,'total':len(work),'kind':row['kind'],'status':row['status']}),flush=True)
verify_source_snapshot(study,preparation,source_manifest)
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
try: validate_review_sources(db,source_packet,source_manifest['tasks'])
finally: db.close()
print(json.dumps({'finished':len(work),'output':str(output),'source_snapshot_rechecked':True}))
