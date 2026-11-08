"""Summarize unique holdout arm records without asserting their provenance."""
from __future__ import annotations

import math
from decimal import Decimal

from .contracts import ContractError


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
        totals=[]; coverage={'covered':0,'not_covered':0,'unknown':0};cases=[]
        for key in keys:
            score=records[key]['score']; covered=score.get('required_evidence_covered')
            if type(covered) not in (bool,type(None)):
                raise ContractError('invalid evidence coverage')
            coverage['covered' if covered is True else 'not_covered' if covered is False else 'unknown']+=1
            total=score.get('resources',{}).get('total')
            if not isinstance(total,dict):raise ContractError('assignment resources required')
            for name in ('calls','known_input_tokens','known_output_tokens','unknown_usage_calls'):
                if type(total.get(name)) is not int or total[name]<0:raise ContractError('invalid resource count')
            for name in ('input_tokens','output_tokens'):
                if total.get(name) is not None and (type(total[name]) is not int or total[name]<0):raise ContractError('invalid token total')
            for name in ('cost_usd','known_cost_usd','latency_seconds'):
                value=total.get(name)
                if (value is None and name=='known_cost_usd') or (value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0)):
                    raise ContractError('invalid resource value')
            totals.append(total)
            cases.append({'case_id':key[0],'repeat':key[1],'category':outcomes[key]['category'],
                          'review_assurance':outcomes[key].get('assurance'),'evidence_covered':covered,
                          'request_status':score.get('request_status'),'classification':score.get('classification')})
        def exact(name):
            values=[item.get(name) for item in totals]
            return None if any(value is None for value in values) else sum(values)
        known_cost=sum((Decimal(str(item['known_cost_usd'])) for item in totals),Decimal(0))
        costs=[item.get('cost_usd') for item in totals]
        summaries[arm]={'assignments':len(keys),'outcomes':{category:sum(outcomes[key]['category']==category for key in keys) for category in categories},
            'evidence_coverage':coverage,'cases':cases,
            'resources':{'calls':sum(item['calls'] for item in totals),'input_tokens':exact('input_tokens'),
                'output_tokens':exact('output_tokens'),'cost_usd':None if any(value is None for value in costs) else float(sum((Decimal(str(value)) for value in costs),Decimal(0))),
                'known_input_tokens':sum(item['known_input_tokens'] for item in totals),
                'known_output_tokens':sum(item['known_output_tokens'] for item in totals),'known_cost_usd':float(known_cost),
                'unknown_usage_calls':sum(item['unknown_usage_calls'] for item in totals),'latency_seconds':exact('latency_seconds')}}
    return {'schema':'qjig.holdout-companion.v1','arms':summaries,'assurance':'caller_asserted_unverified',
            'scope':'holdout_five_arms_only' if additional_reports is not None else 'holdout_three_arms_only'}
