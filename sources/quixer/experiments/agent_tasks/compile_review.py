"""Validate and unblind a completed independent agent outcome packet."""
import argparse
import json
from pathlib import Path
from quix_knowledge.agent_review import compile_agent_review

parser=argparse.ArgumentParser()
parser.add_argument('packet')
parser.add_argument('key')
parser.add_argument('output',help='new output JSON file')
args=parser.parse_args()
packet=json.loads(Path(args.packet).read_text(encoding='utf-8'))
key=json.loads(Path(args.key).read_text(encoding='utf-8'))
result=compile_agent_review(packet,key)
with Path(args.output).open('x',encoding='utf-8') as stream:
    json.dump(result,stream,ensure_ascii=False,indent=2)
print(json.dumps({'outcomes':len(result['outcomes']),'complete_pairs':len(result['complete_pairs']),'missing':len(result['missing'])}))
