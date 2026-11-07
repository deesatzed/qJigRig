"""Replayable no-call deferrals for incomplete full-source applicability."""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from .applicability import Applicability,ApplicabilityInputs,combine_applicability,scope_applicability
from .contracts import ContractError,Request
from .journal import Journal
from .run_archive import RunArchive

_SHA=re.compile(r'[0-9a-f]{64}\Z')


def _verdicts(inputs,scope,revisions):
    result={}
    for revision in revisions:
        member=inputs.collection.member(revision.revision_id)
        entity_date=inputs.verdict(revision.revision_id)
        scope_result=scope_applicability(scope,member.scope)
        result[revision.revision_id]={'entity_date':entity_date.value,'scope':scope_result.value,
                                      'combined':combine_applicability(entity_date,scope_result).value}
    return result


def record_applicability_deferral(archive,request,case_binding,assignment,inputs,revisions,*,want,max_bytes,stages):
    """Record the already checked inputs and their unestablished applicability."""
    if not isinstance(archive,RunArchive) or not isinstance(request,Request) or not isinstance(inputs,ApplicabilityInputs):
        raise ContractError('deferral inputs required')
    verdicts=_verdicts(inputs,request.scope,revisions)
    if not verdicts or all(v['combined']==Applicability.MATCH.value for v in verdicts.values()):
        raise ContractError('deferral requires an unestablished source')
    stage_context={name:{'provider':spec['provider'],'model':spec['model']['id'],
                         'max_tokens':spec['output_tokens'],'max_price':spec['max_price']}
                   for name,spec in stages.items() if name in ('planner','judge','reviewer')}
    archive.record_context({'schema':'qjig.applicability-deferral.v1','request':request.to_dict(),
        'case_binding':case_binding,'evaluation_assignment':assignment,'applicability_inputs':inputs.to_dict(),
        'source_revisions':sorted(r.revision_id for r in revisions),'verdicts':verdicts,
        'want':want,'max_bytes':max_bytes,**stage_context})
    for revision in revisions: archive.add_revision(revision)
    archive.record_run_result(request.request_id,{'schema':'qjig.applicability-deferral-result.v1',
        'request_id':request.request_id,'status':'deferred','reason':'source_applicability_unestablished'})


def verify_applicability_deferral(archive,journal,*,expected_digest=None):
    """Reconstruct the recorded no-call verdict; metadata is an attributed assertion."""
    from .evaluation_budget import validate_assignment_binding
    invalid={'status':'invalid','sha256':None}
    try:
        if not isinstance(archive,RunArchive) or not isinstance(journal,Journal): raise ContractError('archive and journal required')
        context=archive.context();events=archive.events()
        keys={'schema','request','case_binding','evaluation_assignment','applicability_inputs','source_revisions',
              'verdicts','want','max_bytes','planner','judge','reviewer'}
        if set(context)!=keys or context['schema']!='qjig.applicability-deferral.v1': raise ContractError('invalid deferral context')
        validate_assignment_binding(context['evaluation_assignment'])
        if context['evaluation_assignment']['arm']!='decomposition_only': raise ContractError('deferral arm differs')
        request=Request.from_dict(context['request']);inputs=ApplicabilityInputs.from_dict(context['applicability_inputs'])
        revisions=[archive.revision(i) for i in archive.revision_ids()]
        if (not revisions or archive.source_ids() or context['source_revisions']!=sorted(r.revision_id for r in revisions)
                or {m.revision_id for m in inputs.collection.members}!={r.revision_id for r in revisions}
                or type(context['want']) is not int or not 1<=context['want']<=100
                or type(context['max_bytes']) is not int or not 1<=context['max_bytes']<=1024*1024
                or context['verdicts']!=_verdicts(inputs,request.scope,revisions)
                or all(v['combined']=='match' for v in context['verdicts'].values())
                or journal.events(request.request_id)):
            raise ContractError('deferral verdict or journal differs')
        expected={'schema':'qjig.applicability-deferral-result.v1','request_id':request.request_id,
                  'status':'deferred','reason':'source_applicability_unestablished'}
        if len(events)!=1 or events[0]['kind']!='run_result' or events[0]['call_id']!=request.request_id or events[0]['data']!=expected:
            raise ContractError('deferral result differs')
        raw=json.dumps({'context':context,'events':events,'revisions':context['source_revisions'],'journal':[]},
                       sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        digest=hashlib.sha256(raw).hexdigest()
        if expected_digest is not None and (not isinstance(expected_digest,str) or not _SHA.fullmatch(expected_digest)
                                             or not hmac.compare_digest(digest,expected_digest)):
            raise ContractError('deferral digest differs')
        return {'status':'structurally_verified' if expected_digest else 'unanchored','sha256':digest}
    except (ContractError,KeyError,TypeError,ValueError,AttributeError,UnicodeError):
        return invalid


def score_applicability_deferral(archive,journal,reference,*,expected_run_sha256,expected_reference_sha256):
    """Keep the no-call outcome unknown; do not infer justification or source truth."""
    from .evaluation_scoring import reference_digest
    ref_hash=reference_digest(reference)
    if not isinstance(expected_reference_sha256,str) or not _SHA.fullmatch(expected_reference_sha256) or not hmac.compare_digest(ref_hash,expected_reference_sha256):
        raise ContractError('reference digest differs')
    replay=verify_applicability_deferral(archive,journal,expected_digest=expected_run_sha256)
    if replay['status']!='structurally_verified': raise ContractError('deferral is not structurally verified')
    context=archive.context();request=context['request'];inputs=ApplicabilityInputs.from_dict(context['applicability_inputs'])
    binding=context['case_binding']
    if (not isinstance(binding,dict) or binding.get('case_id')!=reference['case_id'] or binding.get('reference_sha256')!=ref_hash
            or any(request[k]!=reference[k] for k in ('question','role','role_version','scope'))
            or inputs.as_of!=reference['as_of'] or sorted(inputs.request_entities)!=reference['entities']
            or inputs.historical_as_known!=reference['historical_as_known']
            or context['source_revisions']!=reference['source_revisions']):
        raise ContractError('deferral reference differs')
    revisions={r:archive.revision(r) for r in context['source_revisions']}
    if any(e['quote'] not in revisions[e['revision_id']].decoded.text for e in reference['evidence']):
        raise ContractError('deferral reference evidence differs')
    return {'case_id':reference['case_id'],'run_sha256':expected_run_sha256,'reference_sha256':ref_hash,
            'reference_provenance':reference['provenance'],'classification':'unknown_review',
            'request_status':'deferred','request_answer':None,'conditional_answer':None,
            'conditional_comparison':'unknown_review','reference_expected_answer':reference['expected_answer'],
            'required_evidence_covered':None,'failure_verified':True,'reconciliation_required':False,
            'semantic_assurance':'not_assessed'}
