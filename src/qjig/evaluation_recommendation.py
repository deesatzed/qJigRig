"""Read-only, evidence-gated two-baseline recommendation reconstruction."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path

from .contracts import ContractError
from .evaluation import decide_from_criteria, validate_decision_criteria
from .evaluation_campaign import EvaluationCampaign
from .evaluation_scoring import build_reserved_holdout_comparison
from .run_archive import RunArchive
from .journal import Journal
from .live_receipts import inspect_campaign_receipts




_RUBRIC_IMPLEMENTATION_FILES = (
    'evaluation.py', 'evaluation_recommendation.py', 'evaluation_scoring.py',
    'evaluation_outcome_review.py', 'evaluation_semantic_review.py',
    'evaluation_replay.py', 'evaluation_campaign.py', 'evaluation_budget.py',
    'evaluation_cases.py', 'evaluation_companion.py', 'live_receipts.py',
)


def make_rubric_contract() -> dict:
    """Describe the provisional policy and bind current implementation bytes.

    This identity does not certify the policy's semantic or clinical correctness.
    """
    directory=Path(__file__).resolve().parent
    try:
        hashes={name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                for name in _RUBRIC_IMPLEMENTATION_FILES}
    except OSError as exc:
        raise ContractError('rubric implementation unavailable') from exc
    return {'schema':'qjig.rubric-contract.v1',
        'policy':'qjig.provisional-pair-decision.v1',
        'categories':{'supported_match':2,'reference_misaligned':1,'failed':0,'unknown_assessment':None},
        'pairs':{'higher':1,'equal':0.5,'lower':0,'denominator':'all_assigned_pairs','unknown':'null'},
        'thresholds':{'remove_below':0.4,'retain_at_least':0.6},
        'combination':'both_retain_or_both_remove_else_revise',
        'incomplete':['missing_assigned_work','missing_resource_record','unreconciled_call',
                      'no_call_refusal_unverified','followup_refusal_unverified','invalid_receipt_or_isolation'],
        'review_assurance':'ai_reviewed_unvalidated',
        'implementation_sha256':hashes}


def verify_rubric_contract(text: str) -> dict:
    """Verify the exact canonical policy and selected local source-file identities."""
    if not isinstance(text,str):
        raise ContractError('invalid rubric contract')
    try:
        if len(text.encode('utf-8'))>100000:
            raise ContractError('invalid rubric contract')
        value=json.loads(text)
        canonical=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError,UnicodeError) as exc:
        raise ContractError('invalid rubric contract') from exc
    if text!=canonical or value!=make_rubric_contract():
        raise ContractError('rubric contract or implementation differs')
    return {'policy':value['policy'],'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'assurance':'implementation_identity_not_semantic_validation'}


def provisional_pair_decision(design: dict, metrics: dict, *, expected_design_sha256: str) -> dict:
    """Apply the published provisional policy to asserted, not verified, metrics."""
    criteria = {
        'remove': {'metric':'outcome_support','operator':'<','threshold':0.4},
        'revise': {'metric':'outcome_support','operator':'range','threshold':[0.4,0.6]},
        'retain': {'metric':'outcome_support','operator':'>=','threshold':0.6}}
    if not isinstance(design,dict) or design.get('criteria') != criteria:
        raise ContractError('provisional decision criteria differ')
    if not isinstance(metrics,dict) or set(metrics) != {'direct_full_evidence','direct_retrieval'}:
        raise ContractError('both baseline metrics required')
    decisions = {key: decide_from_criteria(design,value,expected_design_sha256=expected_design_sha256,
                                           assignments_complete=True,resources_complete=True)
                 for key,value in metrics.items()}
    values = set(decisions.values())
    decision = None if 'inconclusive' in values else 'retain' if values == {'retain'} else 'remove' if values == {'remove'} else 'revise'
    return {'policy':'qjig.provisional-pair-decision.v1','baseline_decisions':decisions,
            'decision':decision,'assurance':'asserted_metrics_not_campaign_evidence'}

def build_verified_recommendation(campaign: EvaluationCampaign, journal: Journal, archive_root: Path, *,
                                  design: dict, references: dict, expected_design_sha256: str,
                                  expected_config_sha256: str | None = None, expected_run_sha256: dict | None = None,
                                  expected_reference_sha256: dict | None = None, expected_journal_sha256: dict | None = None,
                                  expected_review_sha256: dict | None = None, expected_outcome_review_sha256: dict | None = None,
                                  case_root: Path | None = None, case_inputs: dict | None = None) -> dict:
    """Inspect the entire campaign before reconstructing a recommendation.

    External anchors, provider labels and reference truth remain caller assertions.
    This function makes no model call and never certifies independent accuracy.
    """
    if not isinstance(campaign,EvaluationCampaign) or not isinstance(journal,Journal):
        raise ContractError('campaign and journal required')
    manifest,assignments,_,scored=campaign._snapshot()
    if design!=manifest['design'] or expected_design_sha256!=manifest['design_sha256']:
        raise ContractError('recommendation design differs')
    validate_decision_criteria(design,expected_design_sha256=expected_design_sha256)
    row=campaign._goal._con.execute('SELECT value FROM evaluation_campaign_config WHERE plan_id=?',(campaign._plan_id,)).fetchone()
    frozen=json.loads(row[0]) if row else None
    if not isinstance(frozen,dict) or frozen.get('schema') not in ('qjig.campaign-config.v7','qjig.campaign-config.v8'):
        raise ContractError('reviewed v7 or v8 campaign required')
    inspection=inspect_campaign_receipts(campaign,journal,Path(archive_root),references=references,
        expected_config_sha256=expected_config_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256,
        expected_review_sha256=expected_review_sha256,expected_outcome_review_sha256=expected_outcome_review_sha256,
        case_root=case_root,case_inputs=case_inputs,include_records=True)
    campaign_records=inspection.pop('scored_records',None)
    issues=list(inspection['issues'])
    campaign_companion=None
    if campaign_records is not None:
        from .evaluation_companion import summarize_campaign_assertions
        campaign_companion=summarize_campaign_assertions(design,campaign_records,expected_design_sha256=expected_design_sha256)
        campaign_companion['assurance']='structurally_reconstructed_unvalidated'
    elif inspection['status']=='structurally_complete':
        issues.append('campaign_records_unavailable')
    rubric_checked=None
    if frozen['schema']=='qjig.campaign-config.v7':
        issues.append('frozen_rubric_binding_unavailable')
    else:
        try:
            rubric_checked=verify_rubric_contract(frozen.get('rubric_text'))
            if expected_config_sha256 is not None:
                campaign.require_config(frozen['stages'],want=frozen['want'],max_bytes=frozen['max_bytes'],
                                        expected_config_sha256=expected_config_sha256)
        except (ContractError,KeyError,TypeError,ValueError):
            issues.append('rubric_contract_invalid')
    comparisons=None
    comparison_details=None
    ablation_details=None
    companion=None
    interventions=None
    # A fully anchored synthetic campaign can produce diagnostics, but never a
    # recommendation. All other incomplete or invalid inspection blocks reads.
    if (frozen['schema']=='qjig.campaign-config.v8' and inspection['status']!='invalid'
            and set(inspection['issues']) <= {'provider_attribution_not_live'}):
        families={f['id']:f['partition'] for f in design['families']}
        holdout={c['id'] for c in design['cases'] if families[c['family']]=='holdout'}
        entries={}
        base=Path(archive_root)
        with ExitStack() as stack:
            def archive(directory):
                db=directory/'run.sqlite'
                if directory.is_symlink() or db.is_symlink() or not directory.is_dir() or not db.is_file():
                    raise ContractError('review archive unavailable')
                return RunArchive(stack.enter_context(closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None))))
            for rid in sorted(scored):
                assignment=assignments[rid]
                if assignment['case_id'] not in holdout or assignment['arm'] not in ('direct_full_evidence','direct_retrieval','combined','retrieval_only','decomposition_only'):
                    continue
                if not re.fullmatch(r'qj-[0-9a-f]{64}',rid):
                    raise ContractError('unsafe request identity')
                path=base/rid;case=assignment['case_id']
                entries[(case,assignment['repeat'],assignment['arm'])]={'archive':archive(path),'journal':journal,
                    'reference':references[case],'run_sha256':expected_run_sha256[rid],
                    'reference_sha256':expected_reference_sha256[case],'journal_sha256':(expected_journal_sha256 or {}).get(rid),
                    'review_archive':archive(path/'semantic-review'),'review_sha256':expected_review_sha256[rid],
                    'outcome_archive':archive(path/'outcome-review'),'outcome_sha256':expected_outcome_review_sha256[rid]}
            comparisons={}
            comparison_details={}
            for baseline in ('direct_full_evidence','direct_retrieval'):
                selected=[entry for (_,_,arm),entry in entries.items() if arm in (baseline,'combined')]
                report=build_reserved_holdout_comparison(campaign._goal,design,selected,plan_id=campaign._plan_id,
                    expected_plan_sha256=campaign._digest,expected_design_sha256=expected_design_sha256,
                    baseline_arm=baseline,candidate_arm='combined',expected_config_sha256=expected_config_sha256)
                comparisons[baseline]=report['outcome_reviews']['paired']
                comparison_details[baseline]=report
            ablation_details={}
            for arm in ('retrieval_only','decomposition_only'):
                selected=[entry for (_,_,kind),entry in entries.items() if kind in ('direct_retrieval',arm)]
                ablation_details[arm]=build_reserved_holdout_comparison(campaign._goal,design,selected,plan_id=campaign._plan_id,
                    expected_plan_sha256=campaign._digest,expected_design_sha256=expected_design_sha256,
                    baseline_arm='direct_retrieval',candidate_arm=arm,expected_config_sha256=expected_config_sha256)
            from .evaluation_companion import summarize_companion_assertions,group_holdout_interventions
            companion=summarize_companion_assertions(comparison_details,additional_reports=ablation_details)
            companion['assurance']='structurally_reconstructed_unvalidated'
            interventions=group_holdout_interventions(design,companion,expected_design_sha256=expected_design_sha256)
            interventions['assurance']='structurally_reconstructed_unvalidated'
    if inspection['status']=='structurally_complete' and not issues and rubric_checked is not None and comparisons is not None:
        result=provisional_pair_decision(design,{name:value['outcome_support'] for name,value in comparisons.items()},
                                         expected_design_sha256=expected_design_sha256)
        recommendation=result['decision']
        return {'status':'evaluated' if recommendation is not None else 'inconclusive',
                'recommendation':recommendation,'baseline_decisions':result['baseline_decisions'],
                'issues':[],'inspection':inspection,'comparisons':comparisons,'comparison_details':comparison_details,'ablation_details':ablation_details,'companion':companion,'interventions':interventions,'campaign_companion':campaign_companion,
                'resource_scope':'campaign_totals_in_inspection_shared_arms_repeated_in_comparisons',
                'assurance':'structural_and_ai_reviewed_unvalidated',
                'rubric_assurance':rubric_checked['assurance']}
    return {'status':'invalid' if inspection['status']=='invalid' else 'incomplete','recommendation':None,
            'issues':sorted(set(issues)),'inspection':inspection,'comparisons':comparisons,'comparison_details':comparison_details,'ablation_details':ablation_details,'companion':companion,'interventions':interventions,'campaign_companion':campaign_companion,
            'resource_scope':'campaign_totals_in_inspection_shared_arms_repeated_in_comparisons',
            'assurance':'no_recommendation'}
