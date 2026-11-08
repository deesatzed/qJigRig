"""Read-only, evidence-gated two-baseline recommendation reconstruction."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import ContractError
from .evaluation import decide_from_criteria, validate_decision_criteria
from .evaluation_campaign import EvaluationCampaign
from .journal import Journal
from .live_receipts import inspect_campaign_receipts



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
    if not isinstance(frozen,dict) or frozen.get('schema')!='qjig.campaign-config.v7':
        raise ContractError('reviewed v7 campaign required')
    inspection=inspect_campaign_receipts(campaign,journal,Path(archive_root),references=references,
        expected_config_sha256=expected_config_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256,
        expected_review_sha256=expected_review_sha256,expected_outcome_review_sha256=expected_outcome_review_sha256,
        case_root=case_root,case_inputs=case_inputs)
    issues=list(inspection['issues'])
    # The v7 contract does not bind a rubric or comparison implementation. An
    # arbitrary extra field cannot establish a validated, pre-existing binding.
    issues.append('frozen_rubric_binding_unavailable')
    return {'status':'invalid' if inspection['status']=='invalid' else 'incomplete','recommendation':None,
            'issues':sorted(set(issues)),'inspection':inspection,'comparisons':None,
            'assurance':'no_recommendation'}
