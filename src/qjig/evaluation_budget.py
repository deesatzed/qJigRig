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


def verify_evaluation_assignment(goal: GoalBudget, binding: dict, *, case_id: str, case_sha256: str,
                                 design_sha256: str, request_id: str, partition: str) -> str:
    """Check a private assignment against the persisted complete plan and held slots."""
    if not isinstance(goal, GoalBudget):
        raise ContractError('goal ledger required')
    validate_assignment_binding(binding)
    row = goal._con.execute('SELECT set_id,manifest,sha256 FROM evaluation_plans WHERE plan_id=?', (binding['plan_id'],)).fetchone()
    if row is None:
        raise ContractError('evaluation plan unavailable')
    set_id, encoded, digest = row
    if (set_id != 'evaluation:' + binding['plan_id'] or not hmac.compare_digest(digest, binding['plan_sha256'])
            or hashlib.sha256(encoded.encode('utf-8')).hexdigest() != digest):
        raise ContractError('evaluation plan binding differs')
    try:
        manifest = json.loads(encoded)
        plan = make_evaluation_plan(manifest['design'], manifest['case_hashes'], manifest['stage_templates'],
                                    manifest['assignments'], expected_design_sha256=manifest['design_sha256'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError('evaluation plan invalid') from exc
    if plan['sha256'] != digest or plan['manifest'] != manifest or manifest['design_sha256'] != design_sha256:
        raise ContractError('evaluation design differs')
    if manifest['case_hashes'].get(case_id) != case_sha256:
        raise ContractError('evaluation case differs')
    matches = [a for a in manifest['assignments'] if (a['case_id'], a['arm'], a['repeat']) ==
               (case_id, binding['arm'], binding['repeat'])]
    if len(matches) != 1 or matches[0]['request_id'] != request_id or any(w['partition'] != partition for w in matches[0]['work']):
        raise ContractError('evaluation assignment differs')
    frozen = goal._con.execute('SELECT manifest,sha256 FROM run_sets WHERE set_id=?', (set_id,)).fetchone()
    if frozen is None:
        raise ContractError('evaluation run set unavailable')
    goal._verify_run_set(set_id, *frozen)
    return set_id


def validate_assignment_binding(binding: dict) -> None:
    keys = {'plan_id', 'plan_sha256', 'arm', 'repeat'}
    if (not isinstance(binding, dict) or set(binding) != keys
            or not isinstance(binding['plan_id'], str) or not _PLAN_ID.fullmatch(binding['plan_id'])
            or not isinstance(binding['plan_sha256'], str) or not _SHA.fullmatch(binding['plan_sha256'])
            or not isinstance(binding['arm'], str) or not binding['arm'].strip()
            or type(binding['repeat']) is not int or binding['repeat'] < 1):
        raise ContractError('evaluation assignment binding required')


def build_factorial_allocation(design: dict, case_hashes: dict, config: dict, *,
                               expected_design_sha256: str, assignment_secret: bytes) -> dict:
    """Enumerate all declared five-arm physical slots from explicit bounds.

    The secret keeps private assignment mappings out of provider-visible IDs.
    Models, prices and complete input bounds remain caller assertions; this does
    not establish a safe hosted preflight or reserve smoke/acceptance work.
    """
    from .direct_preflight import direct_run_allocations
    from .fresh_preflight import fresh_run_allocations
    validate_evaluation_design(design,expected_digest=expected_design_sha256)
    arms = {'direct_full_evidence','direct_retrieval','retrieval_only','decomposition_only','combined'}
    if set(design['arms']) != arms:
        raise ContractError('factorial allocation requires the five specified arms')
    if not isinstance(assignment_secret,bytes) or not 32 <= len(assignment_secret) <= 4096:
        raise ContractError('private assignment secret required')
    if not isinstance(config,dict) or set(config) != {'direct','planner','judge','reviewer'}:
        raise ContractError('complete factorial model configuration required')
    for spec in config.values():
        if not isinstance(spec,dict) or set(spec) != {'provider','model','input_tokens','output_tokens','max_price'}:
            raise ContractError('invalid factorial stage configuration')
    direct, planner, judge, reviewer = (config[k] for k in ('direct','planner','judge','reviewer'))
    if planner['provider'] != judge['provider']:
        raise ContractError('fresh planner and judge providers must match')
    families = {f['id']:f['partition'] for f in design['families']}
    assignments, templates = [], {}
    for case in design['cases']:
        partition = families[case['family']]
        for arm in sorted(arms):
            for repeat in range(1,design['repeats'][partition]+1):
                identity = _encode([expected_design_sha256,case['id'],arm,repeat]).encode('utf-8')
                request_id = 'qj-' + hmac.new(assignment_secret,identity,hashlib.sha256).hexdigest()
                if arm in ('combined','decomposition_only'):
                    work = fresh_run_allocations(request_id=request_id,partition=partition,provider=planner['provider'],
                        planner_model=planner['model'],judge_model=judge['model'],
                        planner_input=planner['input_tokens'],planner_output=planner['output_tokens'],
                        judge_input=judge['input_tokens'],judge_output=judge['output_tokens'],
                        planner_price=planner['max_price'],judge_price=judge['max_price'],reviewer=reviewer)
                else:
                    work = direct_run_allocations(request_id=request_id,partition=partition,provider=direct['provider'],
                        model=direct['model'],input_tokens=direct['input_tokens'],output_tokens=direct['output_tokens'],
                        max_price=direct['max_price'],followups=0 if arm=='direct_full_evidence' else 1)
                counts = dict(Counter(slot['stage'] for slot in work))
                if arm in templates and templates[arm] != counts:
                    raise ContractError('factorial stage template changed')
                templates[arm] = counts
                assignments.append({'case_id':case['id'],'arm':arm,'repeat':repeat,'request_id':request_id,'work':work})
    return make_evaluation_plan(design,case_hashes,templates,assignments,expected_design_sha256=expected_design_sha256)
