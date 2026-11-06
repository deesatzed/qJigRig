"""Create a condition-blind review packet; keep the key separate from reviewers."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from quix_knowledge.agent_review import prepare_agent_review, seal_review_packet, validate_review_sources
from quix_knowledge.retrieval_study import verify_source_snapshot

parser=argparse.ArgumentParser()
parser.add_argument('run',help='completed actual-agent run directory')
parser.add_argument('study',help='prepared retrieval study directory')
parser.add_argument('--seed',type=int,default=423)
args=parser.parse_args()
run=Path(args.run); study=Path(args.study)
report=json.loads((run/'agent-report.json').read_text())
manifest=json.loads((run/'manifest.json').read_text())
source_packet=json.loads((study/'blind-review-packet.json').read_text())
if source_packet.get('corpus_revision') != report['manifest']['corpus_revision']:
    raise ValueError('review sources do not match agent run')
root=Path(__file__).resolve().parents[2]
retrieval_manifest_bytes=(root/'experiments/retrieval/manifest.json').read_bytes()
preparation=json.loads((study/'preparation.json').read_text())
if preparation.get('manifest_sha256')!=hashlib.sha256(retrieval_manifest_bytes).hexdigest():
    raise ValueError('retrieval manifest changed')
verify_source_snapshot(study,preparation,json.loads(retrieval_manifest_bytes))
db=sqlite3.connect((study/'catalog.db').resolve().as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
try:
    validate_review_sources(db,source_packet,json.loads(retrieval_manifest_bytes)['tasks'])
finally: db.close()
packet,key=prepare_agent_review(report,manifest['tasks'],seed=args.seed)
packet['corpus_revision']=source_packet['corpus_revision']
packet['source_candidates']=source_packet['candidates']
seal_review_packet(packet,key)
for filename,value in (('outcome-review.json',packet),('outcome-key.json',key)):
    with (run/filename).open('x',encoding='utf-8') as stream: json.dump(value,stream,ensure_ascii=False,indent=2)
print(json.dumps({'review_items':len(packet['items']),'missing_runs':len(key['missing']),'packet':str(run/'outcome-review.json')}))
