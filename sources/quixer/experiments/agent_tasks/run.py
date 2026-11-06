"""Exercise paired-study orchestration with synthetic context and agent only."""
import argparse
import json
from pathlib import Path
from quix_knowledge.agent_study import run_agent_study

parser=argparse.ArgumentParser()
parser.add_argument('output',help='new JSON output file')
args=parser.parse_args()
manifest=json.loads((Path(__file__).parent/'manifest.json').read_text())
def context(task,condition):
    return {'fixture':True,'source':'synthetic','text':'Synthetic context for '+task['id']+'.'}
def agent(request):
    return {'output':'Synthetic fixture output for '+request['task_id']+'.','usage':None}
result=run_agent_study(manifest['tasks'],context_provider=context,agent=agent,seed=manifest['seed'],max_input_characters=manifest['max_input_characters'])
with Path(args.output).open('x',encoding='utf-8') as stream:
    json.dump(result,stream,indent=2)
print(json.dumps({'output':args.output,'agent_kind':result['agent_kind'],'runs':len(result['runs'])}))
