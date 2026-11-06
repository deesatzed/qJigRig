"""Bounded isolated cascade experiment; outputs are local research artifacts."""
import argparse, concurrent.futures, copy, hashlib, json, os, random, shutil, sqlite3, time
from pathlib import Path
from quix_knowledge.evidence_recovery import prepare_recovery_request
from quix_knowledge.agent_process import PlannerProcess, validate_role_bindings
from quix_knowledge.agent_review import validate_review_sources
from quix_knowledge.ai_review_v2 import build_review_request, run_review, VERSION
from quix_knowledge.hitm import _check_sources
from quix_knowledge.openrouter import load_settings
from quix_knowledge.research_cascade import escalate, select_context, propose
from quix_knowledge.research_providers import OpenRouterResearchTransport, rerank_candidates
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.retrieve import search
from quix_knowledge.store import corpus_fingerprint
from quix_knowledge.switch_comparison import NodeSwitchRunner, _selected_rows
from quix_knowledge.switch_snapshot import build_snapshot

parser=argparse.ArgumentParser();parser.add_argument('study');parser.add_argument('output');parser.add_argument('--manifest',default='experiments/cascade/manifest-recovery-v1.json');parser.add_argument('--planner',required=True);parser.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env');args=parser.parse_args()
root=Path(__file__).resolve().parents[2]; study=Path(args.study); output=Path(args.output);manifest_path=Path(args.manifest);raw=manifest_path.read_bytes();manifest=json.loads(raw);tasks=manifest['tasks'];
if manifest.get('schema')!='quix-cascade-pilot-v1' or manifest['conditions']!=['baseline','reflex','rerank','combined'] or not 1<=len(tasks)<=8 or len({t['id'] for t in tasks})!=len(tasks): raise ValueError('invalid manifest')
retrieval_manifest_path=root/'experiments/retrieval/manifest.json';retrieval_bytes=retrieval_manifest_path.read_bytes();retrieval_manifest=json.loads(retrieval_bytes);prep=json.loads((study/'preparation.json').read_text());source_packet=json.loads((study/'blind-review-packet.json').read_text());roles=retrieval_manifest['roles'];validate_role_bindings(tasks,roles)
if prep['manifest_sha256']!=hashlib.sha256(retrieval_bytes).hexdigest(): raise ValueError('source manifest changed')
verify_source_snapshot(study,prep,retrieval_manifest)
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
if corpus_fingerprint(db)!=prep['corpus_revision']: raise ValueError('catalog changed')
validate_review_sources(db,source_packet,retrieval_manifest['tasks']);_check_sources(db)
settings=load_settings(args.env_file,2);transport=OpenRouterResearchTransport(settings.api_key);node=shutil.which('node')
if not node: raise ValueError('node unavailable')
runner=NodeSwitchRunner(node,root/'experiments/switch-navigation/src/compare.ts',mode='openrouter',env_file=args.env_file,model=manifest['decision_model'])
planner=PlannerProcess([args.planner],api_key=settings.api_key,model=manifest['planner_model'],role_definitions=roles)
escalator=PlannerProcess([args.planner],api_key=settings.api_key,model=manifest['escalation_model'],role_definitions=roles)
output.mkdir(parents=True,exist_ok=False);(output/'manifest.json').write_bytes(raw)
def verify():
    _check_sources(db)
    if corpus_fingerprint(db)!=prep['corpus_revision']: raise ValueError('catalog changed')
    verify_source_snapshot(study,prep,retrieval_manifest)
contexts={};stage={}
for t in tasks:
    verify();purpose=roles[t['role']]['purpose']; snapshot=build_snapshot(db,task=t['query'],role=t['role'],role_version=t['role_version'],max_steps=5,max_model_calls=10,max_characters=5000,include_proposed=True,matched_candidates=True,choice_mode='bounded-v1')
    ordered=search(db,t['query'],variant='baseline',limit=100,ranking='bm25',include_generated=False)
    candidates={x['id']:x for x in snapshot['candidates']};ids=[x['id'] for x in ordered if x['id'] in candidates];ids+=sorted(set(candidates)-set(ids));pool=[candidates[i] for i in ids]
    start=time.monotonic();rerank=rerank_candidates(t['query'],t['role'],purpose,pool,transport,model=manifest['rerank_model']);rerank['elapsed_seconds']=time.monotonic()-start;verify()
    try: sw=runner(snapshot)
    except Exception as e: sw={'status':'insufficient_evidence','reason':'runner_error','error_type':type(e).__name__,'receipts':None}
    verify();selected=_selected_rows(snapshot,sw,manifest['result_limit']); switch={'status':'complete','rows':selected} if selected is not None else {'status':'insufficient_evidence','rows':None}
    stage[t['id']]={'candidate_ids':ids,'rerank':{k:v for k,v in rerank.items() if k!='candidates'},'rerank_order':[x['id'] for x in rerank['candidates']],
        'switch':{'status':sw.get('status'),'reason':sw.get('reason'),'decision_detail':sw.get('decision_detail'),'receipts':sw.get('receipts'),'trace':sw.get('trace'),'model_requests':sw.get('model_requests')}}
    for condition in manifest['conditions']:
        rows,signals=select_context(condition,pool,rerank,switch,limit=max(1,len(pool)))
        recovered=prepare_recovery_request(t,rows,pool,fingerprint=prep['corpus_revision'],limit=manifest['result_limit'],body_characters=manifest['body_characters'],role_purpose=purpose)
        contexts[(t['id'],condition)]=(recovered,signals)
(output/'stages.json').write_text(json.dumps(stage,ensure_ascii=False,indent=2));(output/'packets.json').write_text(json.dumps([{'task_id':k[0],'condition':k[1],'packet':v[0]['request']['context'] if v[0]['request'] else None,'recovery':{key:value for key,value in v[0]['recovery'].items() if key!='results'},'signals':v[1]} for k,v in contexts.items()],ensure_ascii=False,indent=2))
schedule=[(t['id'],c) for t in tasks for c in manifest['conditions']];random.Random(manifest['seed']).shuffle(schedule);(output/'schedule.json').write_text(json.dumps(schedule,indent=2));taskmap={t['id']:t for t in tasks}; results=[]
with (output/'runs.jsonl').open('x') as journal:
    for tid,condition in schedule:
        t=taskmap[tid]; recovered,signals=contexts[(tid,condition)]; request=recovered['request']
        requested_signal=t.get('escalation') if condition=='combined' else None
        signal=requested_signal or ('insufficient_evidence' if condition=='combined' and signals else 'clear')
        started=time.monotonic()
        if request is None: result={'status':'insufficient_evidence','call':None}
        elif condition=='combined' and signal!='clear': result=escalate(request,signal=signal,planner=escalator,verify_sources=verify)
        else:
            result=propose(request,planner=planner,verify_sources=verify)
        result.update(task_id=tid,condition=condition,signals=signals,escalation_signal=signal,planner_attempted=request is not None,recovery_status=recovered['status'],elapsed_seconds=time.monotonic()-started)
        journal.write(json.dumps(result,ensure_ascii=False)+'\n');journal.flush();os.fsync(journal.fileno());results.append(result)
        print(json.dumps({'completed':len(results),'total':len(schedule),'status':result['status']}),flush=True)
verify();db.close();(output/'agent-report.json').write_text(json.dumps({'schema':'quix-cascade-pilot-report-v1','manifest_sha256':hashlib.sha256(raw).hexdigest(),'corpus_revision':prep['corpus_revision'],'planner_executable_sha256':planner.executable_sha256,'stage_sha256':hashlib.sha256((output/'stages.json').read_bytes()).hexdigest(),'packets_sha256':hashlib.sha256((output/'packets.json').read_bytes()).hexdigest(),'schedule_sha256':hashlib.sha256((output/'schedule.json').read_bytes()).hexdigest(),'escalation_reasoning_enabled':False,'recovery_contract':'quix-evidence-recovery-v1','runs':results},ensure_ascii=False,indent=2));print('pilot complete',flush=True)
