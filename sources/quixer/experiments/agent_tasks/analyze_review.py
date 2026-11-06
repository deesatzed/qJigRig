"""Validate a completed blind review and create a local paired outcome report."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from quix_knowledge.agent_analysis import analyze_agent_outcomes, validate_recorded_packets, summarize_retrieval_accounting, validate_recorded_role_definitions, validate_study_requests
from quix_knowledge.agent_context import build_agent_packets
from quix_knowledge.agent_review import validate_review_sources
from quix_knowledge.agent_study import validate_agent_manifest, validate_retrieval_replay, validate_replay_evidence
from quix_knowledge.hitm import _check_sources
from quix_knowledge.retrieval_study import verify_source_snapshot
from quix_knowledge.store import corpus_fingerprint

parser=argparse.ArgumentParser()
parser.add_argument('packet',help='completed, still-blind reviewer draft')
parser.add_argument('key',help='separate condition key; use only after review')
parser.add_argument('run',help='original completed agent-run directory')
parser.add_argument('study',help='matching prepared retrieval study directory')
parser.add_argument('output',help='new local report file')
args=parser.parse_args()
run=Path(args.run); study=Path(args.study); root=Path(__file__).resolve().parents[2]
packet=json.loads(Path(args.packet).read_text(encoding='utf-8'))
key=json.loads(Path(args.key).read_text(encoding='utf-8'))
report=json.loads((run/'agent-report.json').read_text(encoding='utf-8'))
agent_manifest_bytes=(run/'manifest.json').read_bytes(); agent_manifest=json.loads(agent_manifest_bytes)
validate_agent_manifest(agent_manifest)
if report.get('manifest',{}).get('sha256')!=hashlib.sha256(agent_manifest_bytes).hexdigest():
    raise ValueError('agent manifest differs from recorded run')
retrieval_manifest_bytes=(root/'experiments/retrieval/manifest.json').read_bytes()
retrieval_manifest=json.loads(retrieval_manifest_bytes)
role_purpose_status=validate_recorded_role_definitions(report,agent_manifest['tasks'],retrieval_manifest['roles'])
preparation=json.loads((study/'preparation.json').read_text(encoding='utf-8'))
if preparation.get('manifest_sha256')!=hashlib.sha256(retrieval_manifest_bytes).hexdigest():
    raise ValueError('retrieval manifest differs from preparation')
verify_source_snapshot(study,preparation,retrieval_manifest)
revision=preparation['corpus_revision']
if report['manifest'].get('corpus_revision')!=revision or packet.get('corpus_revision')!=revision:
    raise ValueError('review, agent run and source catalog differ')
source_packet=json.loads((study/'blind-review-packet.json').read_text(encoding='utf-8'))
retrieval_bytes=(run/'retrieval-report.json').read_bytes(); comparison=json.loads(retrieval_bytes)
replay_hash=report['manifest'].get('reused_retrieval_report_sha256')
if replay_hash is not None and replay_hash!=hashlib.sha256(retrieval_bytes).hexdigest():
    raise ValueError('replayed retrieval report changed')
validate_retrieval_replay(comparison,agent_manifest['tasks'],revision)
packets=json.loads((run/'packets.json').read_text(encoding='utf-8'))
validate_recorded_packets(report,packets,agent_manifest['tasks'])
request_hash_status=validate_study_requests(report,packets,agent_manifest['tasks'])
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
try:
    if db.execute('PRAGMA user_version').fetchone()[0]!=7 or corpus_fingerprint(db)!=revision:
        raise ValueError('study catalog changed')
    _check_sources(db)
    validate_review_sources(db,source_packet,retrieval_manifest['tasks'])
    if packet.get('source_candidates')!=source_packet['candidates']:
        raise ValueError('review source candidates differ from catalog')
    validate_replay_evidence(db,comparison,agent_manifest['tasks'])
    body_limit=report['manifest'].get('context_body_character_limit')
    result_limit=report['manifest'].get('context_result_limit')
    if type(body_limit) is not int or type(result_limit) is not int:
        raise ValueError('recorded packet bounds unavailable')
    rebuilt=build_agent_packets(db,comparison,agent_manifest['tasks'],body_characters=body_limit,result_limit=result_limit)
    if {(entry['task_id'],entry['condition']):entry['packet'] for entry in packets}!=rebuilt:
        raise ValueError('saved packets differ from source-bound retrieval')
    _check_sources(db)
    verify_source_snapshot(study,preparation,retrieval_manifest)
    if corpus_fingerprint(db)!=revision:
        raise ValueError('study catalog changed during analysis')
finally:
    db.close()
analysis=analyze_agent_outcomes(packet,key,report,agent_manifest['tasks'])
analysis['source_verification']={'catalog_current_at_analysis':True,
    'source_mode':preparation.get('source_mode','not_recorded'),
    'isolated_snapshot_verified':True if preparation.get('source_mode')=='isolated_copy' else None,
    'retrieval_bodies_and_anchors_match_catalog':True,'saved_packets_match_recorded_runs':True,
    'note':'Point-in-time source checks; PDF extracted text and agent claims are not independently verified.'}
analysis['experiment']={'corpus_revision':revision,'agent_manifest_sha256':report['manifest']['sha256'],
    'model':report['manifest'].get('model'),'reused_retrieval_report_sha256':replay_hash,
    'planner_role_purpose_status':role_purpose_status,'planner_prompt_contract':report['manifest'].get('planner_prompt_contract'),
    'study_request_hash_status':request_hash_status,
    'retrieval_and_indexing':summarize_retrieval_accounting(comparison,preparation)}
with Path(args.output).open('x',encoding='utf-8') as stream:
    json.dump(analysis,stream,ensure_ascii=False,indent=2)
print(json.dumps({'tasks':len(analysis['tasks']),'complete_pairs':len(analysis['complete_pairs']),
    'unknown_costs':analysis['cost']['unknown_count'],'output':args.output}))
