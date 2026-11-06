"""Create a fresh local blind-review catalog from the preregistered manifest."""
import argparse
import json
from pathlib import Path

from quix_knowledge.retrieval_study import prepare_study

parser=argparse.ArgumentParser()
parser.add_argument('output',help='new output directory; existing directories are never overwritten')
parser.add_argument('--role-scores',action='store_true',help='score every eligible unit for each declared role before the review packet')
parser.add_argument('--isolated-sources',action='store_true',help='copy pinned source files into the new study before indexing')
parser.add_argument('--role-call-limit',type=int,default=56,help='maximum number of role-scoring calls')
parser.add_argument('--env-file',default='/Volumes/WS4TB/QUIX/.env')
parser.add_argument('--model-slot',type=int,default=2)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
provider=None
if args.role_scores:
    from quix_knowledge.openrouter import OpenRouterDecision, load_settings
    provider=OpenRouterDecision(load_settings(args.env_file,args.model_slot))
print(json.dumps(prepare_study(root,root/'experiments/retrieval/manifest.json',args.output,role_provider=provider,role_call_limit=args.role_call_limit if provider else None,isolated_sources=args.isolated_sources)))
