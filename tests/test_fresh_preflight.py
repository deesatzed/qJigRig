"""Synthetic resource bounds; never authenticates costs or makes hosted calls."""
from qjig.contracts import Budget
from qjig.goal_budget import GoalBudget
from qjig.plans import MAX_PREDICATES
from qjig.acquisition import MAX_ROUNDS
import pytest
from qjig.budgets import BudgetExceeded
from qjig.contracts import ContractError


def test_fresh_run_set_reserves_all_worst_case_slots(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    allocations = fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                                        planner_model=model, judge_model=model,
                                        planner_input=100, planner_output=50,
                                        judge_input=100, judge_output=50,
                                        planner_price={'prompt': 2, 'completion': 3},
                                        judge_price={'prompt': 2, 'completion': 3})
    assert len(allocations) == 1 + 2 * MAX_PREDICATES * MAX_ROUNDS
    assert len({x['work_id'] for x in allocations}) == len(allocations)
    assert [x['stage'] for x in allocations].count('planner') == 1
    assert [x['stage'] for x in allocations].count('judge_positive') == MAX_PREDICATES * MAX_ROUNDS
    assert [x['stage'] for x in allocations].count('judge_negative') == MAX_PREDICATES * MAX_ROUNDS
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        digest = goal.reserve_run_set('pilot-work', allocations)
        assert len(digest) == 64
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0] == len(allocations)
    short_limit = Budget(len(allocations) - 1, 10000, 1)
    with GoalBudget.open(tmp_path / 'short.sqlite', total=short_limit, per_request=short_limit, allocations={'pilot': short_limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve_run_set('too-small', allocations)
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0] == 0
        assert goal._con.execute('SELECT COUNT(*) FROM run_sets').fetchone()[0] == 0
    with pytest.raises(ContractError, match='ceiling'):
        fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                              planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                              judge_input=100, judge_output=50, planner_price=None, judge_price={'prompt': 2, 'completion': 3})


def test_frozen_slot_selection_survives_restart_and_rejects_mismatch(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    slots = fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                                  planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                                  judge_input=100, judge_output=50, planner_price={'prompt': 2, 'completion': 3},
                                  judge_price={'prompt': 2, 'completion': 3})
    path = tmp_path / 'goal.sqlite'
    limit = Budget(30, 10000, 1)
    args = dict(request_id='request-1', partition='pilot', stage='judge_positive', provider='stand-in',
                model='synthetic/model', tokens=150, cost_usd=0.0005)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        goal.reserve_run_set('pilot-set', slots)
        first = goal.select_required_work('pilot-set', **args)
        binding = next(slot['work_binding_sha256'] for slot in slots if slot['work_id'] == first)
        goal.reserve('attempt-1', required_id=first, work_binding_sha256=binding, **args)
        goal.record_usage('attempt-1', input_tokens=10, output_tokens=5, cost_usd=0.0001)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        second = goal.select_required_work('pilot-set', **args)
        assert second != first
        with pytest.raises(ContractError):
            goal.select_required_work('other-set', **args)
        with pytest.raises(ContractError):
            goal.select_required_work('pilot-set', **{**args, 'model': 'wrong'})
        with pytest.raises(ContractError):
            goal.select_required_work('pilot-set', **{**args, 'tokens': 151})


def test_fresh_slot_rejects_changed_configuration_even_when_cheaper(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.providers import ProviderRequest
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    cap = {'prompt': 2, 'completion': 3}
    slots = fresh_run_allocations(request_id='r', partition='pilot', provider='stand-in',
                                  planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                                  judge_input=100, judge_output=50, planner_price=cap, judge_price=cap)
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        goal.reserve_run_set('frozen', slots)
        request = ProviderRequest('planner', 'stand-in', model['id'], 'question', 50, max_price=cap)
        assert fresh_slot_reservation(goal, 'frozen', request_id='r', partition='pilot', request=request,
                                      model=model, input_tokens=100, input_bound_provenance='fixture').required_id
        cheaper = ProviderRequest('planner', 'stand-in', model['id'], 'question', 50,
                                  max_price={'prompt': 1, 'completion': 1})
        with pytest.raises(ContractError):
            fresh_slot_reservation(goal, 'frozen', request_id='r', partition='pilot', request=cheaper,
                                   model=model, input_tokens=100, input_bound_provenance='fixture')
        changed_model = {**model, 'pricing': {'prompt': '0.0000005', 'completion': '0.000001'}}
        with pytest.raises(ContractError):
            fresh_slot_reservation(goal, 'frozen', request_id='r', partition='pilot', request=request,
                                   model=changed_model, input_tokens=100, input_bound_provenance='fixture')


def test_bound_fresh_slot_cannot_be_consumed_without_configuration(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    slots = fresh_run_allocations(request_id='r', partition='pilot', provider='stand-in',
                                  planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                                  judge_input=100, judge_output=50, planner_price={'prompt': 2, 'completion': 3},
                                  judge_price={'prompt': 2, 'completion': 3})
    planner = next(slot for slot in slots if slot['stage'] == 'planner')
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        goal.reserve_run_set('frozen', slots)
        with pytest.raises(ContractError):
            goal.reserve('attempt', 'r', 'pilot', tokens=planner['tokens'], cost_usd=planner['cost_usd'],
                         stage='planner', provider='stand-in', model=model['id'], required_id=planner['work_id'])
        assert goal.totals().max_calls == 0


def test_typed_call_rejects_rebound_request_before_dispatch(tmp_path):
    from dataclasses import replace
    from qjig.budgets import BudgetLedger
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.journal import Journal
    from qjig.providers import ProviderRequest, StandInTransport, call_typed
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    cap = {'prompt': 2, 'completion': 3}
    slots = fresh_run_allocations(request_id='r', partition='pilot', provider='stand-in',
                                  planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                                  judge_input=100, judge_output=50, planner_price=cap, judge_price=cap)
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        goal.reserve_run_set('frozen', slots)
        original = ProviderRequest('planner', 'stand-in', model['id'], 'question', 50, max_price=cap)
        bound = fresh_slot_reservation(goal, 'frozen', request_id='r', partition='pilot', request=original,
                                       model=model, input_tokens=100, input_bound_provenance='fixture')
        changed = ProviderRequest('planner', 'stand-in', model['id'], 'question', 50,
                                  max_price={'prompt': 1, 'completion': 1})
        forged = replace(bound, request_sha256=changed.input_sha256())
        transport = StandInTransport([])
        with pytest.raises(ContractError, match='configuration'):
            call_typed(BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='pilot'),
                       transport, changed, {}, reservation=forged)
        assert journal.events('r') == [] and transport.calls_made == 0


def test_configured_review_has_separate_frozen_slot(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.providers import ProviderRequest
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    cap = {'prompt': 2, 'completion': 3}
    options = dict(request_id='r', partition='pilot', provider='stand-in', planner_model=model, judge_model=model,
                   planner_input=100, planner_output=50, judge_input=100, judge_output=50,
                   planner_price=cap, judge_price=cap)
    reviewer = {'provider': 'stand-in', 'model': model, 'input_tokens': 200, 'output_tokens': 60, 'max_price': cap}
    slots = fresh_run_allocations(**options, reviewer=reviewer)
    assert len(slots) == 2 + 2 * MAX_PREDICATES * MAX_ROUNDS
    review_slot = next(slot for slot in slots if slot['stage'] == 'plan_review')
    assert review_slot['tokens'] == 260
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        goal.reserve_run_set('frozen', slots)
        request = ProviderRequest('plan_review', 'stand-in', model['id'], 'review prompt', 60, max_price=cap)
        bound = fresh_slot_reservation(goal, 'frozen', request_id='r', partition='pilot', request=request,
                                       model=model, input_tokens=200, input_bound_provenance='synthetic')
        assert bound.required_id == review_slot['work_id']
    with pytest.raises(ContractError):
        fresh_run_allocations(**options, reviewer={**reviewer, 'max_price': None})


def test_direct_preflight_requires_all_possible_slots_before_dispatch(tmp_path):
    import hashlib
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.direct_preflight import direct_run_allocations, direct_slot_reservation
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    model = {'id': 'synthetic/model', 'context_length': 10000, 'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    cap = {'prompt': 2, 'completion': 3}
    slots = direct_run_allocations(request_id='r', partition='pilot', provider='stand-in', model=model,
                                   input_tokens=1000, output_tokens=100, max_price=cap, followups=1)
    assert [x['stage'] for x in slots] == ['direct_initial', 'direct_final']
    code, gold = b'Checks must pass.', b'private labels'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    def search():
        return DirectRetrieval(tmp_path, [item('code', code)], [item('label', gold)], want=1, max_bytes=3000, followups=1)
    limit = Budget(3, 10000, 1)
    for scenario in ('missing', 'complete', 'split'):
        suffix = scenario
        with GoalBudget.open(tmp_path / ('goal'+suffix+'.sqlite'), total=limit, per_request=limit, allocations={'pilot':limit}) as goal, \
                Journal.open(tmp_path / ('j'+suffix+'.sqlite')) as journal, RunArchive.open(tmp_path / ('archive'+suffix)) as archive:
            goal.reserve_run_set('set', slots if scenario == 'complete' else slots[:1])
            if scenario == 'split':
                goal.reserve_run_set('other-set', slots[1:])
            def factory(request):
                set_id = 'other-set' if scenario == 'split' and request.stage == 'direct_final' else 'set'
                return direct_slot_reservation(goal, set_id, request_id='r', partition='pilot', request=request,
                                               model=model, input_tokens=1000, input_bound_provenance='synthetic assertion')
            if scenario == 'complete':
                from qjig.providers import ProviderRequest
                cheaper = ProviderRequest('direct_initial', 'stand-in', model['id'], '', 100,
                                          max_price={'prompt': 1, 'completion': 1})
                with pytest.raises(ContractError):
                    direct_slot_reservation(goal, 'set', request_id='r', partition='pilot', request=cheaper,
                                            model=model, input_tokens=1000, input_bound_provenance='synthetic assertion')
            usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'cost_usd': 0.0001}
            first = RawResponse(200, json.dumps({'action':'search','query':'Checks','answer':None,'citations':[]}), usage)
            final = RawResponse(200, json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}), usage)
            transport = StandInTransport([first, final])
            result = run_direct(search(), Request('r','Checks?','reviewer','1','project'),
                                BudgetLedger(limit,journal,'r',goal_budget=goal,partition='pilot'), transport,
                                archive=archive, provider='stand-in', model=model['id'], max_tokens=100,
                                as_of='2026-11-07', entities=[], max_price=cap, reservation_factory=factory)
            from qjig.evaluation_replay import verify_direct_archive
            replay = verify_direct_archive(archive, journal)
            if scenario == 'complete':
                assert result['status'] == 'recorded_unvalidated' and transport.calls_made == 2
                assert goal.audit_journal(journal)['status'] == 'verified' and replay['status'] == 'unanchored'
            else:
                assert result['status'] == 'unavailable' and result['failure'] == 'preflight_unavailable'
                assert transport.calls_made == 0 and journal.events('r') == []
                assert replay['status'] == 'incomplete' and replay['classification'] == 'unknown_review'


def test_explicit_judge_quota_reserves_both_sides_and_reports_exhaustion_without_call(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.journal import Journal
    from qjig.providers import FieldSpec, ProviderRequest, RawResponse, StandInTransport, call_typed
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3}
    args=dict(request_id='r',partition='pilot',provider='stand-in',planner_model=model,judge_model=model,
              planner_input=100,planner_output=50,judge_input=100,judge_output=50,planner_price=cap,judge_price=cap)
    work=fresh_run_allocations(**args,max_judge_pairs=2)
    assert len(work)==5 and sum(s['stage']=='judge_positive' for s in work)==2
    assert sum(s['stage']=='judge_negative' for s in work)==2
    for invalid in (0,13,True):
        with pytest.raises(ContractError):fresh_run_allocations(**args,max_judge_pairs=invalid)
    budget=Budget(10,10000,1);request=ProviderRequest('judge_positive','stand-in',model['id'],'claim',50,max_price=cap)
    response=RawResponse(200,json.dumps({'ok':True}),{'prompt_tokens':4,'completion_tokens':2,'cost_usd':0.0001})
    with GoalBudget.open(tmp_path/'goal.sqlite',total=budget,per_request=budget,allocations={'pilot':budget}) as goal, Journal.open(tmp_path/'journal.sqlite') as journal:
        goal.reserve_run_set('limited',work)
        ledger=BudgetLedger(budget,journal,'r',goal_budget=goal,partition='pilot')
        transport=StandInTransport([response,response])
        def reserve(req):return fresh_slot_reservation(goal,'limited',request_id='r',partition='pilot',request=req,
            model=model,input_tokens=100,input_bound_provenance='fixture',max_judge_pairs=2,journal=journal)
        for _ in range(2):assert call_typed(ledger,transport,request,{'ok':FieldSpec(bool)},reservation=reserve(request)).ok
        with pytest.raises(BudgetExceeded):reserve(request)
        with pytest.raises(ContractError):
            fresh_slot_reservation(goal,'limited',request_id='r',partition='pilot',request=request,
                model=model,input_tokens=100,input_bound_provenance='fixture',max_judge_pairs=1,journal=journal)
        assert transport.calls_made==2 and len(journal.events('r'))==4 and goal.audit_journal(journal)['status']=='verified'
        changed=ProviderRequest('judge_positive','stand-in',model['id'],'claim',49,max_price=cap)
        with pytest.raises(ContractError):reserve(changed)


def test_judge_quota_does_not_hide_an_unreconciled_attempt(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.journal import Journal, ReconciliationRequired
    from qjig.providers import ProviderRequest
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3};budget=Budget(5,10000,1)
    slots=fresh_run_allocations(request_id='r',partition='pilot',provider='stand-in',planner_model=model,judge_model=model,
        planner_input=100,planner_output=50,judge_input=100,judge_output=50,planner_price=cap,judge_price=cap,max_judge_pairs=1)
    request=ProviderRequest('judge_positive','stand-in',model['id'],'claim',50,max_price=cap)
    with GoalBudget.open(tmp_path/'goal.sqlite',total=budget,per_request=budget,allocations={'pilot':budget}) as goal, Journal.open(tmp_path/'journal.sqlite') as journal:
        goal.reserve_run_set('limited',slots)
        with pytest.raises(ContractError,match='original journal'):
            fresh_slot_reservation(goal,'limited',request_id='r',partition='pilot',request=request,model=model,
                                   input_tokens=100,input_bound_provenance='fixture',max_judge_pairs=1)
        bound=fresh_slot_reservation(goal,'limited',request_id='r',partition='pilot',request=request,model=model,
                                     input_tokens=100,input_bound_provenance='fixture',max_judge_pairs=1,journal=journal)
        goal.reserve('uncertain','r','pilot',tokens=150,cost_usd=bound.cost_usd,required_id=bound.required_id,
                     stage=request.stage,provider=request.provider,model=request.model,work_binding_sha256=bound.work_binding_sha256)
        with pytest.raises(ReconciliationRequired):
            fresh_slot_reservation(goal,'limited',request_id='r',partition='pilot',request=request,model=model,
                                   input_tokens=100,input_bound_provenance='fixture',max_judge_pairs=1,journal=journal)
