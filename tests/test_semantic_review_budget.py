"""A later review shares the request budget while retaining the original run digest."""
import hashlib
import json

import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget, ContractError, Request
from qjig.evaluation import DirectRetrieval
from qjig.evaluation_direct import run_direct
from qjig.evaluation_replay import verify_direct_archive
from qjig.journal import Journal
from qjig.providers import FieldSpec, ProviderRequest, RawResponse, StandInTransport, call_typed
from qjig.run_archive import RunArchive


def test_pinned_original_run_replays_after_review_consumes_same_request_budget(tmp_path):
    source = b'Tests pass.'
    (tmp_path/'code').write_bytes(source)
    sources=[{'path':'code','sha256':hashlib.sha256(source).hexdigest()}]
    secret = b'PRIVATE_REFERENCE'
    (tmp_path/'labels').write_bytes(secret)
    protected=[{'path':'labels','sha256':hashlib.sha256(secret).hexdigest()}]
    search=DirectRetrieval(tmp_path,sources,protected,want=1,max_bytes=3000,followups=0)
    answer=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}),
                       {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    with Journal.open(tmp_path/'journal.sqlite') as journal, RunArchive.open(tmp_path/'archive') as archive:
        request=Request('r','Do tests pass?','reviewer','1','project')
        ledger=BudgetLedger(Budget(2,1000,1),journal,'r')
        run_direct(search,request,ledger,StandInTransport([answer]),archive=archive,
                   provider='stand-in',model='model',max_tokens=100,as_of='2026-11-07',entities=[])
        digest=verify_direct_archive(archive,journal)['sha256']
        review=RawResponse(200,json.dumps({'assessment':'uncertain'}),
                           {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
        call_typed(ledger,StandInTransport([review]),ProviderRequest('semantic_review','stand-in','reviewer','review',100),
                   {'assessment':FieldSpec(str,('uncertain',))},context_binding={'reviewed_run_sha256':digest})
        report=verify_direct_archive(archive,journal,expected_digest=digest,original_run_only=True)
        assert report['status']=='structurally_verified' and report['sha256']==digest
        assert report['journal_scope']=='original_run_prefix'
        assert ledger.used_calls()==2
        with pytest.raises(BudgetExceeded):
            call_typed(ledger,StandInTransport([]),ProviderRequest('semantic_review','stand-in','reviewer','retry',100),
                       {'assessment':FieldSpec(str,('uncertain',))})
        assert verify_direct_archive(archive,journal,expected_digest='0'*64,original_run_only=True)['status']=='invalid'
        assert verify_direct_archive(archive,journal,original_run_only=True)['status']=='invalid'
        journal._append('r',None,'intent','semantic_review','stand-in','reviewer','0'*64,
                        {'context_binding':{'reviewed_run_sha256':'0'*64}})
        assert verify_direct_archive(archive,journal,expected_digest=digest,original_run_only=True)['status']=='invalid'


@pytest.mark.parametrize('malformed', [False, True])
def test_direct_semantic_review_excludes_private_reference_and_replays_original(tmp_path, malformed):
    from qjig.evaluation_semantic_review import review_direct_semantics
    source=b'Tests must pass.'
    private=b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(source)
    (tmp_path/'labels').write_bytes(private)
    item=lambda path,raw:{'path':path,'sha256':hashlib.sha256(raw).hexdigest()}
    search=DirectRetrieval(tmp_path,[item('code',source)],[item('labels',private)],want=1,max_bytes=3000,followups=0)
    entry=search._entries[0].entry_id
    answer=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'yes',
                       'citations':[{'entry_id':entry,'quote':'Tests must pass.'}]}),
                       {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    opinion=RawResponse(200,'not json' if malformed else json.dumps({'assessment':'supported','reason':'the source states the condition'}),
                        {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    with Journal.open(tmp_path/'journal.sqlite') as journal, RunArchive.open(tmp_path/'run') as archive, RunArchive.open(tmp_path/'review') as review_archive:
        request=Request('private-arm-id','Do tests pass?','reviewer','1','project')
        ledger=BudgetLedger(Budget(3,10000,1),journal,request.request_id)
        run_direct(search,request,ledger,StandInTransport([answer]),archive=archive,
                   provider='stand-in',model='model',max_tokens=100,as_of='2026-11-07',entities=[])
        digest=verify_direct_archive(archive,journal)['sha256']
        outcome=review_direct_semantics(archive,journal,ledger,StandInTransport([opinion]),review_archive=review_archive,
                                        expected_run_sha256=digest,provider='stand-in',model='reviewer',max_tokens=100)
        assert outcome['assessment']==('uncertain' if malformed else 'supported')
        assert outcome['assurance']=='synthetic_unvalidated'
        assert outcome['failure']==('malformed_output' if malformed else None)
        prompt=next(e['data']['prompt'] for e in review_archive.events() if e['kind']=='request')
        assert private.decode() not in prompt and request.request_id not in prompt
        assert 'Tests must pass.' in prompt and 'Do tests pass?' in prompt
        assert any(e['kind']=='review_record' for e in review_archive.events())
        from qjig.evaluation_semantic_review import verify_direct_semantic_review
        checked=verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=digest)
        assert checked['status']=='unanchored' and checked['assessment']==outcome['assessment']
        assert verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=digest,
                                             expected_review_sha256=checked['sha256'])['status']=='structurally_verified'
        assert verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=digest,
                                             expected_review_sha256='0'*64)['status']=='invalid'
        assert verify_direct_archive(archive,journal,expected_digest=digest,original_run_only=True)['status']=='structurally_verified'
        assert ledger.used_calls()==2
        review_archive._con.execute('DROP TRIGGER event_no_update')
        seq,encoded=review_archive._con.execute("SELECT seq,data FROM events WHERE kind='review_record'").fetchone()
        changed=json.loads(encoded); changed['assessment']='unsupported'
        review_archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),seq))
        assert verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=digest)['status']=='invalid'


def test_semantic_review_uses_its_frozen_goal_slot(tmp_path):
    from qjig.goal_budget import GoalBudget
    from qjig.semantic_preflight import semantic_review_allocation, semantic_review_reservation
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    request=ProviderRequest('semantic_review','stand-in','synthetic/model','review',100,max_price=spec['max_price'])
    slot=semantic_review_allocation(request_id='r',partition='holdout',spec=spec)
    limit=Budget(2,1000,1)
    usage={'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.0001}
    with GoalBudget.open(tmp_path/'goal.sqlite',total=limit,per_request=limit,allocations={'holdout':limit}) as goal, Journal.open(tmp_path/'journal.sqlite') as journal:
        goal.reserve_run_set('evaluation:test',[slot])
        ledger=BudgetLedger(limit,journal,'r',goal_budget=goal,partition='holdout')
        bound=semantic_review_reservation(goal,'evaluation:test',request_id='r',partition='holdout',request=request,spec=spec)
        response=RawResponse(200,json.dumps({'assessment':'uncertain'}),usage)
        call=call_typed(ledger,StandInTransport([response]),request,{'assessment':FieldSpec(str,('uncertain',))},reservation=bound)
        assert call.ok and goal.audit_journal(journal)['status']=='verified'
        with pytest.raises(ContractError, match="unconsumed"):
            semantic_review_reservation(goal,'evaluation:test',request_id='r',partition='holdout',request=request,spec=spec)
