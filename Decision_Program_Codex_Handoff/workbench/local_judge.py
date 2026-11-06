"""Safe, unthresholded adapter for the local decision judge."""
import json
import math
import os
import subprocess
import time
from pathlib import Path
from . import core

MODEL='MaziyarPanahi/Qwen3.5-4B-Jev-Judge'
REVISION='da378185714efec50fb4393fb88b2198b8de072b'
MAX_TOKENS=4096
QUESTION={'decision':{'type':'choice',
    'instructions':'Is every factual claim in `assistant_response` supported by `authoritative_context`?',
    'criteria':{'true':'Every factual claim in the response is supported by the context.',
                'false':'The response contains at least one unsupported or contradicted claim.'}}}

def validate_prediction(raw):
    try:
        decision=raw['decision']; probabilities=decision['probabilities']; choice=decision['choice']
        if decision['type']!='choice' or choice not in ('true','false') or set(probabilities)!={'true','false'}: raise ValueError()
        for value in probabilities.values():
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1: raise ValueError()
        if abs(sum(probabilities.values())-1)>0.01: raise ValueError()
    except (KeyError,TypeError,ValueError): raise ValueError('Invalid local judge response') from None
    return {'choice':choice,'probabilities':probabilities,
        'interpretation':'Raw model scores; false may mean unsupported or contradicted. No calibrated threshold is applied.'}

def support_decision(result, threshold):
    if isinstance(threshold,bool) or not isinstance(threshold,(float,int)) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError('Local judge requires an explicit support threshold between 0 and 1')
    return 'supported' if result['choice']=='true' and result['probabilities']['true'] >= threshold else 'unknown'

def combine_support(positive, negative):
    if positive not in ('supported','unknown') or negative not in ('supported','unknown'):
        raise ValueError('Invalid support result')
    return {('supported','unknown'):'true', ('unknown','supported'):'false',
            ('unknown','unknown'):'unknown', ('supported','supported'):'conflict'}[(positive,negative)]

def worker_python():
    python=core.config().get('LOCAL_JUDGE_PYTHON') or str(core.ROOT/'.venv-judge'/'bin'/'python')
    if not Path(python).is_file() or not os.access(python,os.X_OK):
        raise ValueError('Local judge Python not found or not executable; configure LOCAL_JUDGE_PYTHON')
    return python

def inspect_worker_environment():
    python=worker_python()
    try:
        process=subprocess.run([python,'-m','workbench.local_worker','--environment'],
            cwd=core.ROOT,text=True,capture_output=True,timeout=15,env={**os.environ,'PYTHONUNBUFFERED':'1'})
        value=json.loads(process.stdout) if process.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired,ValueError):
        value=None
    if not isinstance(value,dict) or not isinstance(value.get('python'),str) or not isinstance(value.get('packages'),dict):
        raise ValueError('Could not inspect local judge environment')
    missing=[name for name in ('unsloth','mlx','transformers','huggingface-hub')
             if not isinstance(value['packages'].get(name),str) or not value['packages'][name]]
    if missing: raise ValueError('Local judge dependencies missing: '+', '.join(missing))
    return value

def validate_recorded_environment(run,expected):
    batches=list(run.get('local_predicate_batches',[]))
    if run.get('local_predicate_batch') is not None: batches.append(run['local_predicate_batch'])
    has_predicate_inference=bool(batches)
    if run.get('answer_check') is not None: batches.append(run['answer_check'])
    if any(not isinstance(batch,dict) or batch.get('worker_environment')!=expected for batch in batches):
        raise ValueError('Saved local judge environment does not match frozen environment')
    if run.get('result',{}).get('status')=='decided' and (not has_predicate_inference or run.get('answer_check') is None):
        raise ValueError('Recorded local inference evidence is missing for a decided run')

def probe_many(source, claims, timeout=300):
    return probe_pairs([(source,claim) for claim in claims],timeout=timeout)

def probe_pairs(pairs, timeout=300):
    if not pairs or any(not isinstance(source,str) or not source.strip() or not isinstance(claim,str) or not claim.strip() for source,claim in pairs):
        raise ValueError('Source and claims are required')
    python=worker_python()
    request=''.join(json.dumps({'source':source,'claim':claim})+'\n' for source,claim in pairs)
    start=time.monotonic()
    try:
        process=subprocess.run([python,'-m','workbench.local_worker'],input=request,text=True,capture_output=True,
            cwd=core.ROOT,timeout=timeout,env={**os.environ,'PYTHONUNBUFFERED':'1'})
    except subprocess.TimeoutExpired: raise RuntimeError('Local judge timed out') from None
    if process.returncode != 0: raise RuntimeError('Local judge worker failed; check its environment and model availability')
    try: responses=[json.loads(line) for line in process.stdout.splitlines()]
    except ValueError: raise RuntimeError('Invalid local judge worker response') from None
    if len(responses)!=len(pairs): raise RuntimeError('Incomplete local judge worker response')
    environments=[response.get('environment') for response in responses]
    if any(environment!=environments[0] for environment in environments): raise RuntimeError('Local judge worker environment changed within batch')
    results=[]
    for response in responses:
        if response.get('error'): raise RuntimeError(response['error'])
        result=validate_prediction(response['prediction'])
        results.append({**result,'input_tokens':response['input_tokens'],'elapsed_seconds':response['elapsed_seconds']})
    return {'backend':'local Unsloth MLX','model':MODEL,'revision':REVISION,'max_tokens':MAX_TOKENS,
            'worker_wall_seconds':round(time.monotonic()-start,3),'inference_count':len(results),'usage_status':'local resource cost unobserved','worker_environment':environments[0],'results':results}

def probe(source, claim, timeout=300):
    if not source.strip() or not claim.strip(): raise ValueError('Source and claim are required')
    python=worker_python()
    request=json.dumps({'source':source,'claim':claim})+'\n'
    start=time.monotonic()
    try:
        process=subprocess.run([python,'-m','workbench.local_worker'],input=request,text=True,capture_output=True,
            cwd=core.ROOT,timeout=timeout,env={**os.environ,'PYTHONUNBUFFERED':'1'})
    except subprocess.TimeoutExpired: raise RuntimeError('Local judge timed out') from None
    if process.returncode != 0: raise RuntimeError('Local judge worker failed; check its environment and model availability')
    try: response=json.loads(process.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError): raise RuntimeError('Invalid local judge worker response') from None
    if response.get('error'): raise RuntimeError(response['error'])
    result=validate_prediction(response['prediction'])
    return {**result, 'backend':'local Unsloth MLX','model':MODEL,'revision':REVISION,
            'input_tokens':response['input_tokens'],'max_tokens':MAX_TOKENS,
            'elapsed_seconds':response['elapsed_seconds'],'worker_wall_seconds':round(time.monotonic()-start,3),'usage_status':'local resource cost unobserved','worker_environment':response.get('environment')}
