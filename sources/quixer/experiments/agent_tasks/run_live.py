"""Run an isolated, exploratory paired HITMCockpit planner comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import tiktoken
from quix_knowledge.agent_context import build_agent_packets
from quix_knowledge.agent_process import PlannerProcess, validate_role_bindings
from quix_knowledge.agent_study import run_agent_study, validate_agent_manifest, validate_retrieval_replay, validate_replay_evidence, run_agent_retrieval_comparison, retrieval_provider_provenance
from quix_knowledge.hitm import _check_sources
from quix_knowledge.openrouter import load_settings, OpenRouterDecision
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.store import open_catalog, corpus_fingerprint
from quix_knowledge.switch_comparison import NodeSwitchRunner

parser=argparse.ArgumentParser()
parser.add_argument('study',help='prepared retrieval study directory')
parser.add_argument('output',help='new output directory')
parser.add_argument('--planner',required=True,help='built QuixPlannerStudyCLI executable')
parser.add_argument('--model',required=True,help='explicit OpenRouter text model for all conditions')
parser.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env')
parser.add_argument('--decision-slot',type=int,default=2)
parser.add_argument('--manifest',help='agent-study manifest; defaults to the original five-task manifest')
parser.add_argument('--body-characters',type=int,default=300)
parser.add_argument('--result-limit',type=int,default=1)
parser.add_argument('--reuse-retrieval',help='reuse a previous retrieval-report.json with exactly the same tasks, corpus and budget')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
manifest_path=Path(args.manifest) if args.manifest else Path(__file__).parent/'manifest.json'
manifest_bytes=manifest_path.read_bytes(); manifest=json.loads(manifest_bytes)
validate_agent_manifest(manifest)
if not 1 <= args.body_characters <= 300 or not 1 <= args.result_limit <= 3:
    raise ValueError('invalid packet bounds')
study=Path(args.study); prep=json.loads((study/'preparation.json').read_text())
retrieval_manifest_bytes=(root/'experiments/retrieval/manifest.json').read_bytes()
if prep.get('manifest_sha256') != hashlib.sha256(retrieval_manifest_bytes).hexdigest():
    raise ValueError('retrieval manifest changed since preparation')
retrieval_manifest=json.loads(retrieval_manifest_bytes)
verify_source_snapshot(study,prep,retrieval_manifest)
role_definitions=retrieval_manifest['roles']
validate_role_bindings(manifest['tasks'],role_definitions)
output=Path(args.output); output.mkdir(parents=True,exist_ok=False)
(output/'manifest.json').write_bytes(manifest_bytes)
source=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True)
copy=sqlite3.connect(output/'catalog-copy.db')
try: source.backup(copy)
finally: copy.close(); source.close()
db=open_catalog(output/'catalog-copy.db')
try:
    _check_sources(db)
    if corpus_fingerprint(db) != prep['corpus_revision']:
        raise RuntimeError('prepared catalog changed')
    replay_hash=None
    if args.reuse_retrieval:
        replay_bytes=Path(args.reuse_retrieval).read_bytes()
        replay_hash=hashlib.sha256(replay_bytes).hexdigest()
        comparison=json.loads(replay_bytes)
        validate_retrieval_replay(comparison,manifest['tasks'],prep['corpus_revision'])
        validate_replay_evidence(db,comparison,manifest['tasks'])
    else:
        node=shutil.which('node')
        if not node: raise RuntimeError('node unavailable')
        runner=NodeSwitchRunner(node,root/'experiments/switch-navigation/src/compare.ts',mode='openrouter',env_file=args.env_file,model_slot=args.decision_slot)
        encoding=tiktoken.get_encoding('cl100k_base')
        comparison=run_agent_retrieval_comparison(db,manifest['tasks'],switch_runner=runner,count_tokens=lambda x:len(encoding.encode(x)),provider=OpenRouterDecision(load_settings(args.env_file,args.decision_slot)))
    if comparison['manifest']['corpus_revision'] != prep['corpus_revision']:
        raise RuntimeError('prepared catalog changed')
    (output/'retrieval-report.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
    fingerprint=comparison['manifest']['corpus_revision']
    packets=build_agent_packets(db,comparison,manifest['tasks'],body_characters=args.body_characters,result_limit=args.result_limit)
    (output/'packets.json').write_text(json.dumps([{'task_id':key[0],'condition':key[1],'packet':value} for key,value in packets.items()],ensure_ascii=False,indent=2))
    settings=load_settings(args.env_file,args.decision_slot)
    agent=PlannerProcess([str(Path(args.planner).resolve())],api_key=settings.api_key,model=args.model,timeout=60,role_definitions=role_definitions)
    def save_schedule(schedule):
        with (output/'schedule.json').open('x',encoding='utf-8') as stream:
            json.dump(schedule,stream,indent=2); stream.flush(); os.fsync(stream.fileno())
    with (output/'runs.jsonl').open('x',encoding='utf-8') as journal:
        def save_result(result):
            journal.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n'); journal.flush(); os.fsync(journal.fileno())
        report=run_agent_study(manifest['tasks'],context_provider=lambda task,condition:packets[(task['id'],condition)],agent=agent,seed=manifest['seed'],max_input_characters=manifest['max_input_characters'],agent_kind='actual',on_schedule=save_schedule,on_result=save_result,role_definitions=role_definitions)
    report['manifest']={'sha256':hashlib.sha256(manifest_bytes).hexdigest(),'model':args.model,'corpus_revision':fingerprint,
        'planner_executable_sha256':agent.executable_sha256,
        'reused_retrieval_report_sha256':replay_hash,
        'role_annotations':db.execute('SELECT count(*) FROM role_annotations').fetchone()[0],
        'source_mode':prep.get('source_mode','not_recorded'), 'source_snapshot':prep.get('source_snapshot'),
        'role_definitions':role_definitions,'planner_role_purpose_included':True,'planner_prompt_contract':'quix-planner-role-purpose-v1',
        'planner_intent_limit_unicode_scalars':2000,'context_body_character_limit':args.body_characters,'context_result_limit':args.result_limit,
        'retrieval_packet_token_limit':2000,'retrieval_tokenizer':'cl100k_base','decision_slot':args.decision_slot,
        'retrieval_provider':retrieval_provider_provenance(comparison),
        'limitations':'Exploratory shared corpus; no independent labels, no agent outcome review; provider/model input budgets are not matched across retrieval policies. Costs and failures are per call; local compute unknown.'}
    (output/'agent-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'runs':len(report['runs']),'statuses':{status:sum(x['status']==status for x in report['runs']) for status in sorted({x['status'] for x in report['runs']})},'output':str(output)}))
finally: db.close()
