"""Request-outcome review is blinded, separately budgeted, and replayable."""
import hashlib
import json
import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.evaluation import DirectRetrieval
from qjig.evaluation_direct import run_direct
from qjig.evaluation_replay import verify_direct_archive
from qjig.journal import Journal
from qjig.providers import RawResponse, StandInTransport
from qjig.run_archive import RunArchive


@pytest.mark.parametrize('malformed',[False,True])
@pytest.mark.parametrize('routed',[False,True])
def test_direct_outcome_review_is_blind_budgeted_and_replayable(tmp_path,malformed,routed):
    from qjig.evaluation_outcome_review import review_direct_outcome, verify_direct_outcome_review
    source=b'Tests must pass.';private=b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(source);(tmp_path/'labels').write_bytes(private)
    item=lambda path,raw:{'path':path,'sha256':hashlib.sha256(raw).hexdigest()}
    search=DirectRetrieval(tmp_path,[item('code',source)],[item('labels',private)],want=1,max_bytes=3000,followups=0)
    answer=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'yes',
        'citations':[{'entry_id':search._entries[0].entry_id,'quote':'Tests must pass.'}]}),
        {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    opinion=RawResponse(200,'bad json' if malformed else json.dumps({'assessment':'yes','reason':'stated by source'}),
                        {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    with Journal.open(tmp_path/'journal.sqlite') as journal, RunArchive.open(tmp_path/'original') as archive, RunArchive.open(tmp_path/'review') as review:
        request=Request('PRIVATE_ARM_MAPPING','Do tests pass?','reviewer','1','project')
        ledger=BudgetLedger(Budget(2,10000,1),journal,request.request_id)
        run_direct(search,request,ledger,StandInTransport([answer]),archive=archive,
                   provider='stand-in',model='model',max_tokens=100,as_of='2026-11-07',entities=[])
        digest=verify_direct_archive(archive,journal)['sha256']
        class RoutedStandIn(StandInTransport):
            def send(self,request):
                from qjig.providers import openrouter_wire_payload_v5
                response=super().send(request)
                metadata={'wire_payload_format':'openrouter.chat.v5',
                          'wire_payload_sha256':hashlib.sha256(openrouter_wire_payload_v5(request).encode()).hexdigest()}
                return RawResponse(response.http_status,response.body,response.usage,metadata=metadata)
        options={'provider':'openrouter','route':'provider-a/fp4','max_price':{'prompt':2,'completion':3}} if routed else {'provider':'stand-in'}
        transport=RoutedStandIn([opinion]) if routed else StandInTransport([opinion])
        result=review_direct_outcome(archive,journal,ledger,transport,review_archive=review,
             expected_run_sha256=digest,model='reviewer',max_tokens=100,**options)
        assert review.context().get('route')==options.get('route')
        assert result['assessment']==('uncertain' if malformed else 'yes')
        assert result['assurance']=='synthetic_unvalidated' and ledger.used_calls()==2
        prompt=next(e['data']['prompt'] for e in review.events() if e['kind']=='request')
        assert private.decode() not in prompt and request.request_id not in prompt
        assert 'Do tests pass?' in prompt and 'Tests must pass.' in prompt
        checked=verify_direct_outcome_review(archive,journal,review,expected_run_sha256=digest)
        assert checked['status']=='unanchored' and checked['assessment']==result['assessment']
        assert verify_direct_outcome_review(archive,journal,review,expected_run_sha256=digest,
                 expected_review_sha256=checked['sha256'])['status']=='structurally_verified'
        assert verify_direct_archive(archive,journal,expected_digest=digest,original_run_only=True)['status']=='structurally_verified'
        review._con.execute('DROP TRIGGER event_no_update')
        seq,encoded=review._con.execute("SELECT seq,data FROM events WHERE kind='review_record'").fetchone()
        changed=json.loads(encoded);changed['assessment']='no'
        review._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),seq))
        assert verify_direct_outcome_review(archive,journal,review,expected_run_sha256=digest)['status']=='invalid'
