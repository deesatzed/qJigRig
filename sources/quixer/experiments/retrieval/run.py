"""Run a frozen study in a new directory, with optional reviewed labels."""
import argparse
import json
import shutil
from pathlib import Path

import tiktoken
from quix_knowledge.openrouter import OpenRouterDecision, load_settings
from quix_knowledge.retrieval_study import run_prepared_study
from quix_knowledge.switch_comparison import NodeSwitchRunner

parser=argparse.ArgumentParser()
parser.add_argument('study')
parser.add_argument('output',help='new output directory; existing directories are never overwritten')
parser.add_argument('--mode',choices=('fixture','openrouter'),default='fixture')
parser.add_argument('--reviewed',help='reviewed packet; omit to run without relevance labels')
parser.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env')
parser.add_argument('--model-slot',type=int,default=2)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
manifest_path=root/'experiments/retrieval/manifest.json'
config=json.loads(manifest_path.read_text())['comparison']
node=shutil.which('node')
if not node:
    parser.error('node is required')
runner=NodeSwitchRunner(node,root/'experiments/switch-navigation/src/compare.ts',mode=args.mode,env_file=args.env_file,model_slot=args.model_slot)
provider=OpenRouterDecision(load_settings(args.env_file,args.model_slot)) if args.mode == 'openrouter' else None
encoding=tiktoken.get_encoding(config['tokenizer'])
report=run_prepared_study(root,manifest_path,args.study,args.output,switch_runner=runner,
    count_tokens=lambda value: len(encoding.encode(value)),tokenizer_name=config['tokenizer'],packet_tokens=config['packet_tokens'],
    provider=provider,reviewed_packet=args.reviewed)
print(json.dumps({'output':str(Path(args.output)/'report.json'),'label_provenance':report['manifest']['label_provenance'],
    'role_annotation_count':report['manifest']['study']['role_annotation_count'],
    'metrics':{name:variant['metrics'] for name,variant in report['variants'].items()}},indent=2))
