"""Replay one saved QUIX switch trace without model calls."""
import argparse
import json
from pathlib import Path
import shutil
from quix_knowledge.switch_replay import replay_saved_trace

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('catalog')
parser.add_argument('report')
parser.add_argument('task_id')
args=parser.parse_args()
node=shutil.which('node')
if not node: parser.error('node is required')
receipt=replay_saved_trace(args.catalog,args.report,args.task_id,node=node,script=Path(__file__).parent/'src/replay.ts')
print(json.dumps(receipt,indent=2))
