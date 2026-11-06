"""Review-gated dataset exports and isolated offline score reproduction."""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from . import core, compare, datasets

KINDS=('datasets','dataset_runs','dataset_receipts','dataset_intents','comparisons',
       'snapshots','runs','adjudications','case_assessments')
JOURNAL_KINDS=('comparison_intents','comparison_arm_intents','comparison_arm_receipts',
               'run_intents','run_call_intents','run_call_receipts')

def check_journal(records):
    """Check recorded relationships, not authenticity or completeness of history."""
    if not any(records[k] for k in JOURNAL_KINDS):
        return 'not recorded',[]
    comparisons={x['id']:x for x in records['comparisons']}
    runs={x['id']:x for x in records['runs']}
    issues=[]; missing=[]
    for item in records['comparison_intents']:
        comp=comparisons.get(item['id'])
        if not comp: issues.append('Comparison intent references a missing comparison'); continue
        if any(k in item and item[k]!=comp.get(k) for k in ('question','stage','snapshot_id','snapshot_sha256')):
            issues.append('Comparison intent differs from its comparison')
    arm_intents={x['id']:x for x in records['comparison_arm_intents']}
    arm_receipts={x['id']:x for x in records['comparison_arm_receipts']}
    for item in records['comparison_intents']:
        comp=comparisons.get(item['id'])
        if comp and len([x for x in arm_intents.values() if x.get('comparison_id')==item['id']])<len(comp.get('items',[])):
            missing.append('Comparison has fewer arm intents than recorded arms')
    for ident,intent in arm_intents.items():
        if intent.get('comparison_id') not in comparisons: issues.append('Arm intent references a missing comparison')
        if ident not in arm_receipts: missing.append('Arm intent has no receipt')
    for ident,receipt in arm_receipts.items():
        intent=arm_intents.get(ident); comp=comparisons.get(receipt.get('comparison_id'))
        if not intent or not comp or intent.get('comparison_id')!=receipt.get('comparison_id') or intent.get('arm')!=receipt.get('arm'):
            issues.append('Arm receipt does not match its intent'); continue
        if not any(all(item.get(k)==receipt.get(k) for k in ('arm','run_id','review_id')) for item in comp.get('items',[])):
            issues.append('Arm receipt does not match the comparison item')
    for item in records['run_intents']:
        run=runs.get(item['id'])
        if not run: issues.append('Run intent references a missing run'); continue
        for key in ('mode','request','source_sha256'):
            if key in item and key in run and item[key]!=run[key]: issues.append('Run intent differs from its run'); break
    call_intents={x['id']:x for x in records['run_call_intents']}
    call_receipts={x['id']:x for x in records['run_call_receipts']}
    responses={}
    for ident,run in runs.items():
        entries=run.get('model_responses',[])
        responses[ident]=Counter((x.get('stage'),x.get('text')) for x in entries
            if isinstance(x,dict) and isinstance(x.get('stage'),str) and isinstance(x.get('text'),str)) if isinstance(entries,list) else Counter()
    run_intent_ids={x['id'] for x in records['run_intents']}
    for run_id,run in runs.items():
        if run.get('calls') and run_id not in run_intent_ids: missing.append('Run with provider calls has no run intent')
        indices=[x.get('index') for x in call_intents.values() if x.get('run_id')==run_id]
        valid_indices=[i for i in indices if isinstance(i,int) and not isinstance(i,bool) and i>=0]
        if len(valid_indices)!=len(indices) or len(set(valid_indices))!=len(valid_indices):
            issues.append('Call intents have invalid or duplicate indices')
        expected=set(range(len(run.get('calls',[]))))
        if not expected.issubset(valid_indices):
            missing.append('Run has fewer call intents than recorded provider calls')
        if set(valid_indices)-expected:
            missing.append('Call intent has no matching recorded run call')
    for ident,intent in call_intents.items():
        if intent.get('run_id') not in runs: issues.append('Call intent references a missing run')
        if ident not in call_receipts: missing.append('Call intent has no receipt')
    for ident,receipt in call_receipts.items():
        intent=call_intents.get(ident)
        if not intent or intent.get('run_id')!=receipt.get('run_id') or intent.get('stage')!=receipt.get('stage'):
            issues.append('Call receipt does not match its intent'); continue
        run=runs.get(receipt.get('run_id')); index=intent.get('index')
        if not run or not isinstance(index,int) or isinstance(index,bool) or index<0 or index>=len(run.get('calls',[])):
            issues.append('Call receipt references a missing run call'); continue
        if receipt.get('metadata')!=run['calls'][index]: issues.append('Call receipt metadata differs from the run')
        if receipt.get('status')=='returned':
            response=receipt.get('response')
            if not isinstance(response,str):
                missing.append('Returned call receipt has no response text')
            elif run.get('mode')=='frontier-web':
                result=run.get('result') or {}
                saved=result.get('provider_answer') or result.get('answer')
                if not isinstance(saved,str): missing.append('Web run has no comparable response text')
                elif saved!=response: issues.append('Call receipt response differs from the web run')
            else:
                key=(receipt.get('stage'),response)
                if responses[run['id']][key]: responses[run['id']][key]-=1
                else: issues.append('Call receipt response differs from the run responses')
    return ('inconsistent' if issues else ('incomplete' if missing else 'consistent')),issues+missing

def export_dataset(run_id):
    score=datasets.score(run_id)  # Enforces completion, bindings and review gates.
    run=core.load('dataset_runs',run_id)
    dataset=datasets.load_frozen(run['dataset_id'])
    kinds=KINDS+JOURNAL_KINDS
    records={kind:{} for kind in kinds}
    def add(kind,record):
        ident=record['id']
        if ident in records[kind] and records[kind][ident]!=record: raise ValueError('Conflicting archived records')
        records[kind][ident]=record
    add('datasets',dataset); add('dataset_runs',run)
    for intent in core.records('dataset_intents'):
        if intent['dataset_run_id']==run_id: add('dataset_intents',intent)
    for receipt in datasets.status(run_id)['receipts']:
        add('dataset_receipts',receipt)
        bundle=compare.export_bundle(receipt['comparison_id'])
        add('comparisons',bundle['comparison']); add('snapshots',bundle['source'])
        for source in bundle['source_members']: add('snapshots',source)
        for item in bundle['runs']: add('runs',item['record'])
        for review in bundle['adjudications']: add('adjudications',review)
        assessment=bundle['report']['case_assessment']
        if assessment: add('case_assessments',assessment)
    comparison_ids=set(records['comparisons']); run_ids=set(records['runs'])
    for kind in JOURNAL_KINDS:
        for record in core.records(kind):
            if kind=='comparison_intents': related=record['id'] in comparison_ids
            elif kind.startswith('comparison_'): related=record.get('comparison_id') in comparison_ids
            elif kind=='run_intents': related=record['id'] in run_ids
            else: related=record.get('run_id') in run_ids
            if related: add(kind,record)
    return {'format':'decision-workbench-dataset-v2',
            'notice':'Contains source text, model responses, and human review details; handle accordingly.',
            'dataset_run_id':run_id,'records':{kind:list(entries.values()) for kind,entries in records.items()},
            'score':score}

def verify_dataset(bundle):
    if not isinstance(bundle,dict) or bundle.get('format') not in ('decision-workbench-dataset-v1','decision-workbench-dataset-v2'): raise ValueError('Unsupported dataset archive')
    kinds=KINDS+(JOURNAL_KINDS if bundle['format']=='decision-workbench-dataset-v2' else ())
    ident=bundle.get('dataset_run_id')
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Invalid dataset run ID')
    records=bundle.get('records')
    if not isinstance(records,dict) or set(records)!=set(kinds): raise ValueError('Invalid archived record categories')
    with tempfile.TemporaryDirectory(prefix='decision-workbench-replay-') as tmp:
        root=Path(tmp)
        for kind in kinds:
            items=records[kind]
            if not isinstance(items,list) or len(items)>10000: raise ValueError('Invalid archived records')
            directory=root/kind; directory.mkdir()
            for item in items:
                key=item.get('id') if isinstance(item,dict) else None
                if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key): raise ValueError('Invalid archived record ID')
                path=directory/(key+'.json')
                if path.exists(): raise ValueError('Duplicate archived record ID')
                path.write_text(json.dumps(item,ensure_ascii=False,allow_nan=False))
        env={'PATH':os.defpath,'WORKBENCH_DATA':tmp,'PYTHONIOENCODING':'utf-8'}
        try:
            process=subprocess.run([sys.executable,'-m','workbench','dataset-score',ident],cwd=core.ROOT,env=env,text=True,capture_output=True,timeout=30)
        except subprocess.TimeoutExpired: raise ValueError('Offline score verification timed out') from None
        if process.returncode:
            lines=process.stderr.strip().splitlines()
            detail=lines[0][7:507] if len(lines)==1 and lines[0].startswith('Error: ') else ''
            raise ValueError('Archive cannot be rescored by the current runtime'+(': '+detail if detail else ''))
        try: score=json.loads(process.stdout)
        except ValueError: raise ValueError('Invalid offline score output') from None
    journal_status,journal_issues=check_journal(records) if bundle['format']=='decision-workbench-dataset-v2' else ('not recorded',[])
    return {'matches_exported_score':score==bundle.get('score'),'score':score,
            'journal_status':journal_status,'journal_issues':journal_issues,
            'interpretation':'Offline replay checks score and available journal relationships, not history completeness, authenticity, reviewer independence or correctness.'}
