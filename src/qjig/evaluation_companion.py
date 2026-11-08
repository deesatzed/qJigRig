"""Summarize unique holdout arm records without asserting their provenance."""
from __future__ import annotations

import math
import re
from decimal import Decimal

from .contracts import ContractError



def _aggregate_resource_totals(totals: list[dict]) -> dict:
    """Add complete recorded subtotals without replacing unknown values with zero."""
    for total in totals:
        if not isinstance(total,dict):raise ContractError('assignment resources required')
        for name in ('calls','known_input_tokens','known_output_tokens','unknown_usage_calls'):
            if type(total.get(name)) is not int or total[name]<0:raise ContractError('invalid resource count')
        if total['unknown_usage_calls']>total['calls']:raise ContractError('invalid unknown usage count')
        for name in ('input_tokens','output_tokens'):
            if total.get(name) is not None and (type(total[name]) is not int or total[name]<0):raise ContractError('invalid token total')
        for name in ('cost_usd','known_cost_usd','latency_seconds'):
            value=total.get(name)
            if (value is None and name=='known_cost_usd') or (value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0)):
                raise ContractError('invalid resource value')
        for name,known in (('input_tokens','known_input_tokens'),('output_tokens','known_output_tokens'),('cost_usd','known_cost_usd')):
            value=total.get(name)
            if value is not None and Decimal(str(value))!=Decimal(str(total[known])):
                raise ContractError('resource known subtotal differs')
            if total['unknown_usage_calls']==0 and value is None:
                raise ContractError('complete usage total unavailable')
    def exact(name):
        values=[item.get(name) for item in totals]
        return None if any(value is None for value in values) else sum(values)
    costs=[item.get('cost_usd') for item in totals]
    return {'calls':sum(item['calls'] for item in totals),'input_tokens':exact('input_tokens'),
        'output_tokens':exact('output_tokens'),'cost_usd':None if any(value is None for value in costs) else float(sum((Decimal(str(value)) for value in costs),Decimal(0))),
        'known_input_tokens':sum(item['known_input_tokens'] for item in totals),
        'known_output_tokens':sum(item['known_output_tokens'] for item in totals),
        'known_cost_usd':float(sum((Decimal(str(item['known_cost_usd'])) for item in totals),Decimal(0))),
        'unknown_usage_calls':sum(item['unknown_usage_calls'] for item in totals),'latency_seconds':exact('latency_seconds')}


def summarize_companion_assertions(reports: dict, *, additional_reports: dict | None = None) -> dict:
    """Summarize supplied comparison records; caller must establish provenance."""
    baselines=('direct_full_evidence','direct_retrieval')
    if not isinstance(reports,dict) or set(reports)!=set(baselines):
        raise ContractError('both comparison reports required')
    if additional_reports is not None and (not isinstance(additional_reports,dict)
            or set(additional_reports)!={'retrieval_only','decomposition_only'}):
        raise ContractError('both ablation reports required')
    comparison_specs=[(baseline,'combined',reports[baseline]) for baseline in baselines]
    if additional_reports is not None:
        comparison_specs.extend(('direct_retrieval',arm,additional_reports[arm]) for arm in ('retrieval_only','decomposition_only'))
    records={}
    outcomes={}
    reference_pairs=None
    for baseline,candidate,report in comparison_specs:
        if not isinstance(report,dict) or not isinstance(report.get('scored_assignments'),list):
            raise ContractError('comparison assignments required')
        review=report.get('outcome_reviews')
        if not isinstance(review,dict) or not isinstance(review.get('records'),list):
            raise ContractError('comparison outcomes required')
        seen=set()
        for entry in report['scored_assignments']:
            if not isinstance(entry,dict) or not isinstance(entry.get('score'),dict):
                raise ContractError('invalid companion assignment')
            arm,repeat,score=entry.get('arm'),entry.get('repeat'),entry['score']
            case=score.get('case_id')
            if arm not in (baseline,candidate) or type(repeat) is not int or repeat<1 or not isinstance(case,str) or not case:
                raise ContractError('invalid companion assignment identity')
            key=(case,repeat,arm)
            if key in seen or (key in records and records[key]!=entry):
                raise ContractError('duplicate or inconsistent companion assignment')
            seen.add(key);records[key]=entry
        seen_outcomes=set()
        for entry in review['records']:
            if not isinstance(entry,dict):raise ContractError('invalid companion outcome')
            key=(entry.get('case_id'),entry.get('repeat'),entry.get('arm'))
            if (key not in seen or key in seen_outcomes or entry.get('category') not in
                    ('supported_match','reference_misaligned','failed','unknown_assessment')
                    or (key in outcomes and outcomes[key]!=entry)):
                raise ContractError('duplicate or inconsistent companion outcome')
            seen_outcomes.add(key);outcomes[key]=entry
        if seen_outcomes!=seen:
            raise ContractError('companion outcome set differs')
        baseline_pairs={(case,repeat) for case,repeat,arm in seen if arm==baseline}
        candidate_pairs={(case,repeat) for case,repeat,arm in seen if arm==candidate}
        if not baseline_pairs or baseline_pairs!=candidate_pairs or (reference_pairs is not None and baseline_pairs!=reference_pairs):
            raise ContractError('companion pair set incomplete')
        reference_pairs=baseline_pairs
    summaries={}
    categories=('supported_match','reference_misaligned','failed','unknown_assessment')
    arms=(*baselines,'combined') + (('retrieval_only','decomposition_only') if additional_reports is not None else ())
    for arm in arms:
        keys=sorted(key for key in records if key[2]==arm)
        totals=[]; stages={}; coverage={'covered':0,'not_covered':0,'unknown':0};cases=[]
        for key in keys:
            score=records[key]['score']; covered=score.get('required_evidence_covered')
            if type(covered) not in (bool,type(None)):
                raise ContractError('invalid evidence coverage')
            coverage['covered' if covered is True else 'not_covered' if covered is False else 'unknown']+=1
            resources=score.get('resources')
            if not isinstance(resources,dict) or not isinstance(resources.get('stages'),dict):
                raise ContractError('assignment stages required')
            total=resources.get('total'); _aggregate_resource_totals([total])
            stage_values=resources['stages']
            if any(not isinstance(name,str) or not name for name in stage_values):
                raise ContractError('invalid resource stage')
            stage_aggregate=_aggregate_resource_totals(list(stage_values.values()))
            for name in ('calls','input_tokens','output_tokens','cost_usd','known_input_tokens','known_output_tokens','known_cost_usd','unknown_usage_calls'):
                if stage_aggregate[name]!=total[name]:
                    raise ContractError('stage resources differ from total')
            for name,value in stage_values.items():
                stages.setdefault(name,[]).append(value)
            totals.append(total)
            cases.append({'case_id':key[0],'repeat':key[1],'category':outcomes[key]['category'],
                          'review_assurance':outcomes[key].get('assurance'),'evidence_covered':covered,
                          'request_status':score.get('request_status'),'classification':score.get('classification')})
        summaries[arm]={'assignments':len(keys),'outcomes':{category:sum(outcomes[key]['category']==category for key in keys) for category in categories},
            'evidence_coverage':coverage,'cases':cases,'resources':_aggregate_resource_totals(totals),
            'stages':{name:_aggregate_resource_totals(values) for name,values in sorted(stages.items())}}
    return {'schema':'qjig.holdout-companion.v1','arms':summaries,'assurance':'caller_asserted_unverified',
            'scope':'holdout_five_arms_only' if additional_reports is not None else 'holdout_three_arms_only'}


def group_holdout_interventions(design: dict, companion: dict, *, expected_design_sha256: str, partition: str = 'holdout') -> dict:
    """Group caller-asserted request outcomes by frozen intervention links."""
    from .evaluation import validate_evaluation_design
    if not isinstance(expected_design_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_design_sha256):
        raise ContractError('frozen design anchor required')
    validate_evaluation_design(design,expected_digest=expected_design_sha256)
    if partition not in ('development','pilot','holdout'):
        raise ContractError('invalid intervention partition')
    arms=companion.get('arms') if isinstance(companion,dict) else None
    if not isinstance(arms,dict) or set(arms)!=set(design['arms']):
        raise ContractError('all intervention arms required')
    families={item['id']:item['partition'] for item in design['families']}
    cases={case['id']:case for case in design['cases'] if families[case['family']]==partition}
    repeats=design['repeats'][partition]
    categories={'supported_match','reference_misaligned','failed','unknown_assessment'}
    indexed={}
    for arm,summary in arms.items():
        rows=summary.get('cases') if isinstance(summary,dict) else None
        if not isinstance(rows,list):raise ContractError('intervention case rows required')
        for row in rows:
            if not isinstance(row,dict):raise ContractError('invalid intervention row')
            case,repeat=row.get('case_id'),row.get('repeat')
            if (not isinstance(case,str) or case not in cases or type(repeat) is not int or not 1<=repeat<=repeats
                    or row.get('category') not in categories or (case,arm,repeat) in indexed):
                raise ContractError('invalid or duplicate intervention row')
            indexed[(case,arm,repeat)]=row
    groups={name:[] for name in ('changed_decisive','missing_decisive','irrelevant_change')}
    for case in sorted(cases.values(),key=lambda item:item['id']):
        parent=case['parent']
        if parent is None:continue
        for group in groups:
            if group not in case['categories']:continue
            for arm in sorted(arms):
                for repeat in range(1,repeats+1):
                    before=indexed.get((parent,arm,repeat));after=indexed.get((case['id'],arm,repeat))
                    known=before is not None and after is not None and before['category']!='unknown_assessment' and after['category']!='unknown_assessment'
                    groups[group].append({'parent_case':parent,'intervention_case':case['id'],'arm':arm,'repeat':repeat,
                        'parent':before,'intervention':after,
                        'category_changed':before['category']!=after['category'] if known else None})
    return {'schema':'qjig.grouped-holdout-interventions.v1','design_sha256':expected_design_sha256,
            'groups':groups,'partition':partition,'assurance':'caller_asserted_unverified',
            'interpretation':'category_changes_are_not_semantic_accuracy'}


def summarize_campaign_assertions(design: dict, records: list[dict], *, expected_design_sha256: str) -> dict:
    """Summarize every assigned partition from caller-asserted scored records."""
    from .evaluation import validate_evaluation_design
    if not isinstance(expected_design_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_design_sha256):
        raise ContractError('frozen design anchor required')
    validate_evaluation_design(design,expected_digest=expected_design_sha256)
    if not isinstance(records,list):raise ContractError('campaign records required')
    families={item['id']:item['partition'] for item in design['families']}
    cases={case['id']:families[case['family']] for case in design['cases']}
    if sum(design['repeats'][partition] for partition in cases.values())*len(design['arms'])>100000:
        raise ContractError('campaign companion exceeds limit')
    expected={(case,arm,repeat) for case,partition in cases.items() for arm in design['arms']
              for repeat in range(1,design['repeats'][partition]+1)}
    indexed={}
    for record in records:
        if not isinstance(record,dict) or not isinstance(record.get('score'),dict):
            raise ContractError('invalid campaign record')
        score=record['score'];key=(score.get('case_id'),record.get('arm'),record.get('repeat'))
        if key not in expected or key in indexed or record.get('outcome_category') not in (
                'supported_match','reference_misaligned','failed','unknown_assessment'):
            raise ContractError('invalid or duplicate campaign assignment')
        indexed[key]=record
    if set(indexed)!=expected:
        raise ContractError('campaign assignment set incomplete')
    partitions={};interventions={}
    for partition in ('development','pilot','holdout'):
        def report(baseline,candidate):
            selected=[indexed[key] for key in sorted(indexed) if cases[key[0]]==partition and key[1] in (baseline,candidate)]
            return {'scored_assignments':[{'arm':r['arm'],'repeat':r['repeat'],'score':r['score']} for r in selected],
                'outcome_reviews':{'records':[{'case_id':r['score']['case_id'],'repeat':r['repeat'],'arm':r['arm'],
                    'category':r['outcome_category'],'assurance':r.get('outcome_assurance')} for r in selected]}}
        comparisons={baseline:report(baseline,'combined') for baseline in ('direct_full_evidence','direct_retrieval')}
        ablations={arm:report('direct_retrieval',arm) for arm in ('retrieval_only','decomposition_only')}
        summary=summarize_companion_assertions(comparisons,additional_reports=ablations)
        summary['scope']=partition+'_five_arms_only'
        partitions[partition]=summary
        interventions[partition]=group_holdout_interventions(design,summary,expected_design_sha256=expected_design_sha256,partition=partition)
    return {'schema':'qjig.campaign-companion.v1','design_sha256':expected_design_sha256,
            'partitions':partitions,'interventions':interventions,'assurance':'caller_asserted_unverified'}


def summarize_arm_configuration(frozen: dict) -> dict:
    """Describe configured arm access and work without asserting provider compliance."""
    names={'direct','planner','judge','reviewer','semantic_reviewer','outcome_reviewer'}
    if (not isinstance(frozen,dict) or frozen.get('schema')!='qjig.campaign-config.v8'
            or type(frozen.get('want')) is not int or frozen['want']<1
            or type(frozen.get('max_bytes')) is not int or frozen['max_bytes']<1
            or type(frozen.get('max_judge_pairs')) is not int or frozen['max_judge_pairs']<1
            or frozen.get('planner_prompt_version') not in ('legacy_v1','exception_applicability_v2')
            or not isinstance(frozen.get('stages'),dict) or set(frozen['stages'])!=names):
        raise ContractError('complete reviewed campaign configuration required')
    stages={}
    for name,spec in frozen['stages'].items():
        model=spec.get('model') if isinstance(spec,dict) else None
        if (not isinstance(model,dict) or not isinstance(model.get('id'),str) or not model['id']
                or not isinstance(spec.get('provider'),str) or not spec['provider']
                or type(spec.get('input_tokens')) is not int or spec['input_tokens']<0
                or type(spec.get('output_tokens')) is not int or spec['output_tokens']<1
                or (spec.get('route') is not None and not isinstance(spec['route'],str))):
            raise ContractError('invalid configured stage')
        stages[name]={'provider':spec['provider'],'model':model['id'],'route':spec.get('route'),
            'context_length':model.get('context_length'),'input_tokens':spec['input_tokens'],
            'output_tokens':spec['output_tokens'],'max_price':spec.get('max_price'),
            'input_tokens_assurance':'configured_not_provider_verified'}
    definitions={
        'direct_full_evidence':('full_source',0,('direct','semantic_reviewer','outcome_reviewer')),
        'direct_retrieval':('lexical_retrieval',1,('direct','semantic_reviewer','outcome_reviewer')),
        'retrieval_only':('catalog_retrieval',1,('direct','semantic_reviewer','outcome_reviewer')),
        'decomposition_only':('full_source',None,('planner','judge','reviewer','semantic_reviewer','outcome_reviewer')),
        'combined':('catalog_retrieval',None,('planner','judge','reviewer','semantic_reviewer','outcome_reviewer'))}
    arms={}
    for arm,(mode,followups,used) in definitions.items():
        fresh=arm in ('decomposition_only','combined')
        arms[arm]={'source_mode':mode,'direct_followups':followups,'want':frozen['want'],'max_bytes':frozen['max_bytes'],
            'max_judge_pairs':frozen['max_judge_pairs'] if fresh else None,
            'planner_prompt_version':frozen['planner_prompt_version'] if fresh else None,
            'stages':{name:stages[name] for name in used}}
    return {'schema':'qjig.arm-configuration-summary.v1','arms':arms,
            'assurance':'frozen_configuration_assertion',
            'limitations':'configured access and limits do not establish actual provider compliance or comparable work'}
