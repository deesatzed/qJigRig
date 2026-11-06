"""Run real synthetic FastDecisionModel probes; requires the isolated judge environment."""
import argparse
import importlib.metadata
import json
import time
from pathlib import Path

MODEL='MaziyarPanahi/Qwen3.5-4B-Jev-Judge'
REVISION='da378185714efec50fb4393fb88b2198b8de072b'
QUESTION={'decision':{'type':'choice',
    'instructions':'Is every factual claim in `assistant_response` supported by `authoritative_context`?',
    'criteria':{'true':'Every factual claim in the response is supported by the context.',
                'false':'The response contains at least one unsupported or contradicted claim.'}}}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True); parser.add_argument('--local-files-only',action='store_true'); args=parser.parse_args()
    output=Path(args.output)
    if output.exists(): parser.error('Output already exists; choose a new path')
    output.parent.mkdir(parents=True,exist_ok=True)
    from unsloth import FastDecisionModel
    start=time.monotonic()
    model,tokenizer=FastDecisionModel.from_pretrained(MODEL,revision=REVISION,max_seq_length=4096,
        load_in_4bit=False,local_files_only=args.local_files_only)
    FastDecisionModel.for_inference(model)
    loaded=time.monotonic()
    probes=[('support','The ball is red.','The ball is red.'),
            ('unsupported','The ball is red.','The ball is heavy.'),
            ('negation','The ball is not red.','The ball is red.'),
            ('negation_supported','The ball is not red.','The ball is not red.')]
    results=[]
    for name,context,claim in probes:
        state=json.dumps({'authoritative_context':context,'assistant_response':claim})
        begun=time.monotonic()
        answer=FastDecisionModel.predict(model,tokenizer,state,QUESTION)
        results.append({'probe':name,'state':state,'output':answer,'elapsed_seconds':round(time.monotonic()-begun,3)})
        print(name,json.dumps(answer,default=str),flush=True)
    output={'model':MODEL,'revision':REVISION,'unsloth':importlib.metadata.version('unsloth'),
        'max_seq_length':4096,'load_in_4bit':False,'load_seconds':round(loaded-start,3),
        'probes':results,'interpretation':'Synthetic adapter probes only; not model quality validation.'}
    with open(args.output,'x') as f: json.dump(output,f,indent=2,default=str)

if __name__=='__main__': main()
