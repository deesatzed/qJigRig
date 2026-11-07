"""Complete declared experiment assignments and atomic goal-ledger reservation.

Templates, input bounds, prices and assignment identities are caller assertions;
this module does not authorize hosted calls or establish experimental validity.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter

from .budgets import _valid_cost, _valid_tokens
from .contracts import ContractError
from .evaluation import validate_evaluation_design
from .goal_budget import GoalBudget

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_PLAN_ID = re.compile(r'[A-Za-z0-9_.-]{1,80}\Z')


def _encode(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('evaluation plan is not finite JSON') from exc


def make_evaluation_plan(design: dict, case_hashes: dict, stage_templates: dict, assignments: list[dict], *,
                         expected_design_sha256: str) -> dict:
    """Bind every declared case/arm/repeat to its declared physical call slots."""
    if not isinstance(expected_design_sha256, str) or not _SHA.fullmatch(expected_design_sha256):
        raise ContractError('design anchor required')
    validate_evaluation_design(design, expected_digest=expected_design_sha256)
    cases = {c['id']: c for c in design['cases']}
    families = {f['id']: f['partition'] for f in design['families']}
    arms = set(design['arms'])
    if (not isinstance(case_hashes, dict) or set(case_hashes) != set(cases)
            or any(not isinstance(v, str) or not _SHA.fullmatch(v) for v in case_hashes.values())
            or len(set(case_hashes.values())) != len(case_hashes)):
        raise ContractError('case binding set differs')
    if not isinstance(stage_templates, dict) or set(stage_templates) != arms:
        raise ContractError('stage templates must cover every arm')
    for template in stage_templates.values():
        if (not isinstance(template, dict) or not template or
                any(not isinstance(k, str) or not k.strip() or type(v) is not int or v < 1 for k, v in template.items())
                or sum(template.values()) > 30):
            raise ContractError('invalid stage template')
    count = sum(design['repeats'][families[c['family']]] for c in cases.values()) * len(arms)
    if count > 100_000 or not isinstance(assignments, list) or len(assignments) != count:
        raise ContractError('assignment denominator differs')
    expected = {(c['id'], arm, repeat) for c in cases.values() for arm in arms
                for repeat in range(1, design['repeats'][families[c['family']]] + 1)}
    seen, request_ids, work_ids, normalized = set(), set(), set(), []
    work_keys = {'work_id', 'request_id', 'partition', 'tokens', 'cost_usd', 'stage', 'provider', 'model', 'work_binding_sha256'}
    for assignment in assignments:
        if not isinstance(assignment, dict) or set(assignment) != {'case_id', 'arm', 'repeat', 'request_id', 'work'}:
            raise ContractError('invalid evaluation assignment')
        case_id, arm, repeat, request_id, work = (assignment[k] for k in ('case_id', 'arm', 'repeat', 'request_id', 'work'))
        if not isinstance(case_id, str) or not isinstance(arm, str) or type(repeat) is not int:
            raise ContractError('invalid assignment identity')
        key = (case_id, arm, repeat)
        if (key not in expected or key in seen or not isinstance(request_id, str) or not request_id.strip()
                or request_id in request_ids or not isinstance(work, list) or not work):
            raise ContractError('missing, duplicate or invalid assignment')
        seen.add(key); request_ids.add(request_id)
        partition = families[cases[case_id]['family']]
        for slot in work:
            if (not isinstance(slot, dict) or set(slot) != work_keys or
                    any(not isinstance(slot[k], str) or not slot[k].strip() for k in ('work_id', 'stage', 'provider', 'model'))
                    or slot['request_id'] != request_id or slot['partition'] != partition or slot['work_id'] in work_ids
                    or not _valid_tokens(slot['tokens']) or slot['tokens'] < 1 or not _valid_cost(slot['cost_usd'])
                    or not isinstance(slot['work_binding_sha256'], str) or not _SHA.fullmatch(slot['work_binding_sha256'])):
                raise ContractError('invalid assigned work slot')
            work_ids.add(slot['work_id'])
        if Counter(slot['stage'] for slot in work) != Counter(stage_templates[arm]):
            raise ContractError('assigned work differs from stage template')
        normalized.append({**assignment, 'work': sorted(work, key=lambda x: x['work_id'])})
    if seen != expected:
        raise ContractError('assignment denominator differs')
    normalized.sort(key=lambda x: (x['case_id'], x['arm'], x['repeat']))
    manifest = {'schema':'qjig.evaluation-allocation.v1', 'design':design, 'design_sha256':expected_design_sha256,
                'case_hashes':case_hashes, 'stage_templates':stage_templates, 'assignments':normalized}
    encoded = _encode(manifest)
    return {'manifest':json.loads(encoded), 'sha256':hashlib.sha256(encoded.encode('utf-8')).hexdigest()}


def reserve_evaluation_plan(goal: GoalBudget, plan_id: str, plan: dict, *, expected_plan_sha256: str) -> dict:
    """Atomically persist a private allocation plan and reserve its declared slots."""
    if (not isinstance(goal, GoalBudget) or not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id)
            or not isinstance(plan, dict) or set(plan) != {'manifest', 'sha256'}
            or not isinstance(expected_plan_sha256, str) or not _SHA.fullmatch(expected_plan_sha256)):
        raise ContractError('invalid evaluation plan reservation')
    encoded = _encode(plan['manifest'])
    digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    if not isinstance(plan['sha256'], str) or not hmac.compare_digest(digest, plan['sha256']) or not hmac.compare_digest(digest, expected_plan_sha256):
        raise ContractError('evaluation plan digest differs')
    m = plan['manifest']
    if not isinstance(m, dict) or set(m) != {'schema','design','design_sha256','case_hashes','stage_templates','assignments'} or m['schema'] != 'qjig.evaluation-allocation.v1':
        raise ContractError('invalid evaluation plan manifest')
    rebuilt = make_evaluation_plan(m['design'], m['case_hashes'], m['stage_templates'], m['assignments'], expected_design_sha256=m['design_sha256'])
    if rebuilt != plan:
        raise ContractError('evaluation plan is not canonical')
    work = [slot for assignment in m['assignments'] for slot in assignment['work']]
    run_sha = goal.reserve_run_set('evaluation:' + plan_id, work, _evaluation_binding=(plan_id, encoded, digest))
    return {'plan_sha256':digest, 'run_set_sha256':run_sha, 'assignments':len(m['assignments']), 'work_items':len(work)}
