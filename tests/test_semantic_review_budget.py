"""A later review shares the request budget while retaining the original run digest."""
import hashlib
import json

import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget, Request
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
