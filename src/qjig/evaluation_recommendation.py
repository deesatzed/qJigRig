"""Read-only, evidence-gated two-baseline recommendation reconstruction."""
from __future__ import annotations

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
        case_root=case_root,case_inputs=case_inputs)
    issues=list(inspection['issues'])
    if frozen['schema']=='qjig.campaign-config.v7':
        issues.append('frozen_rubric_binding_unavailable')
    else:
        # Text identity alone cannot prove that it implements the scoring rubric.
        issues.append('rubric_semantics_not_verified')
    comparisons=None
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
                if assignment['case_id'] not in holdout or assignment['arm'] not in ('direct_full_evidence','direct_retrieval','combined'):
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
            for baseline in ('direct_full_evidence','direct_retrieval'):
                selected=[entry for (_,_,arm),entry in entries.items() if arm in (baseline,'combined')]
                report=build_reserved_holdout_comparison(campaign._goal,design,selected,plan_id=campaign._plan_id,
                    expected_plan_sha256=campaign._digest,expected_design_sha256=expected_design_sha256,
                    baseline_arm=baseline,candidate_arm='combined',expected_config_sha256=expected_config_sha256)
                comparisons[baseline]=report['outcome_reviews']['paired']
    return {'status':'invalid' if inspection['status']=='invalid' else 'incomplete','recommendation':None,
            'issues':sorted(set(issues)),'inspection':inspection,'comparisons':comparisons,
            'assurance':'no_recommendation'}
