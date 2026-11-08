"""Exercise the local draft's entire assignment set with synthetic responses.

Run from the repository root with PYTHONPATH=src. This never contacts a model,
uses synthetic prices and token bounds, and writes only to an ignored local run.
It is not a provider evaluation or an experiment freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from qjig.applicability import ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
from qjig.contracts import Budget
from qjig.evaluation import validate_evaluation_design
from qjig.evaluation_budget import build_factorial_allocation, reserve_evaluation_plan
from qjig.evaluation_campaign import EvaluationCampaign, applicability_digest, run_campaign_batch
from qjig.evaluation_cases import case_lock_digest
from qjig.evaluation_scoring import reference_digest, fresh_journal_digest
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from qjig.providers import RawResponse, StandInTransport
from qjig.replay import verify_archive
from qjig.evaluation_replay import verify_direct_archive
from qjig.run_archive import RunArchive
from qjig.sources import SourceRevision, decode_source

DRAFT = Path('.local/evaluation-draft-20261107')


def stage_configuration(spec, *, semantic):
    names=('direct','planner','judge','reviewer','semantic_reviewer') if semantic else ('direct','planner','judge','reviewer')
    return {name:dict(spec) for name in names}


def main():
    parser=argparse.ArgumentParser(description='Run only synthetic draft responses; no provider calls.')
    parser.add_argument('--resume',type=Path,help='Existing synthetic verification directory to resume')
    parser.add_argument('--semantic',action='store_true',help='Reserve and execute semantic-review slots')
    parser.add_argument('--judge-pairs',type=int,help='Explicit bounded judge pairs per fresh assignment')
    args=parser.parse_args()
    if args.judge_pairs is not None and (not args.semantic or not 1 <= args.judge_pairs <= 12):
        parser.error('--judge-pairs requires --semantic and a value from 1 to 12')
    design=json.loads((DRAFT/'design.json').read_text())
    locks=json.loads((DRAFT/'private/case_locks.json').read_text())
    refs=json.loads((DRAFT/'private/references.json').read_text())
    design_hash=validate_evaluation_design(design)
    protected=[{'path':str(path.relative_to(DRAFT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted((DRAFT/'private').iterdir()) if path.is_file() and not path.is_symlink()]
    cases,case_hashes,metadata={}, {}, {}
    for ident,record in locks.items():
        lock,ref=record['lock'],refs[ident]['reference']
        if case_lock_digest(lock)!=record['sha256'] or reference_digest(ref)!=refs[ident]['sha256']:
            raise ValueError('draft case or reference anchor differs')
        members=[]
        for source in lock['sources']:
            raw=(DRAFT/source['path']).read_bytes()
            revision=SourceRevision.create(source['path'],'evaluation_allowlist',decode_source(raw,encoding='utf-8'))
            members.append(MemberMetadata(revision.revision_id,lock['scope'],Interval('0001-01-01',OPEN),
                                          entity_keys=frozenset(lock['entities']),observed_at='0001-01-01'))
        inputs=ApplicabilityInputs(Collection(tuple(members)),frozenset(lock['entities']),lock['as_of'],lock['historical_as_known'])
        cases[ident]={'lock':lock,'reference':ref,'protected':protected,'applicability_inputs':inputs}
        case_hashes[ident]=record['sha256'];metadata[ident]=applicability_digest(inputs)
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':{'prompt':2,'completion':3}}
    config=stage_configuration(spec,semantic=args.semantic)
    plan=build_factorial_allocation(design,case_hashes,config,expected_design_sha256=design_hash,
                                    assignment_secret=b'synthetic-campaign-fixture-secret-only',max_judge_pairs=args.judge_pairs)
    parent=Path('.local/verification');parent.mkdir(parents=True,exist_ok=True)
    if args.resume is not None:
        directory=args.resume
        if directory.is_symlink() or not directory.is_dir() or not (directory/'goal.sqlite').is_file() or not (directory/'journal.sqlite').is_file():
            raise ValueError('existing synthetic verification directory required')
    else:
        directory=Path(tempfile.mkdtemp(prefix='full-factorial-synthetic-',dir=parent))
    total=Budget(1500,300000,20) if args.semantic else Budget(1300,260000,20);per=Budget(30,6000,1)
    allocations=({'development':Budget(450,90000,5),'pilot':Budget(350,70000,5),'holdout':Budget(700,140000,10)} if args.semantic else
                 {'development':Budget(400,80000,5),'pilot':Budget(300,60000,5),'holdout':Budget(600,120000,10)})
    counts=Counter()
    class SyntheticTransport(StandInTransport):
        def __init__(self):
            super().__init__([])
        def send(self,request):
            self.calls_made += 1
            counts[request.stage]+=1
            if request.stage.startswith('direct_'):
                result={'action':'answer','query':None,'answer':'unknown','citations':[]}
            elif request.stage=='planner':
                result={'predicates':[{'id':'p','question':'Does the source establish the requested condition?'}],
                        'expression':{'ref':'p'}}
            elif request.stage in ('judge_positive','judge_negative'):
                result={'supported':False,'quote':'','reason':'synthetic fixture'}
            elif request.stage in ('plan_review','semantic_review'):
                result={'assessment':'uncertain','reason':'synthetic fixture'}
            else:
                raise ValueError('unexpected synthetic stage')
            return RawResponse(200,json.dumps(result),{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001})
    with GoalBudget.open(directory/'goal.sqlite',total=total,per_request=per,allocations=allocations) as goal, \
         Journal.open(directory/'journal.sqlite') as journal:
        reservation=reserve_evaluation_plan(goal,'draft-synthetic',plan,expected_plan_sha256=plan['sha256'])
        campaign=EvaluationCampaign(goal,'draft-synthetic',expected_plan_sha256=plan['sha256'])
        config_hash=campaign.freeze_config(config,want=3,max_bytes=6000,case_applicability=metadata,max_judge_pairs=args.judge_pairs)
        pending=campaign.status()['in_progress']
        if pending:
            rid=pending[0];assignment=next(a for a in plan['manifest']['assignments'] if a['request_id']==rid)
            archive_path=directory/'archives'/rid
            if archive_path.is_symlink() or not (archive_path/'run.sqlite').is_file():
                raise RuntimeError('interrupted synthetic archive unavailable; no retry attempted')
            with RunArchive.open(archive_path) as archive:
                context=archive.context()
                if context['schema']=='qjig.fresh-context.v1':
                    replay=verify_archive(archive);run_hash=replay.digest;journal_hash=fresh_journal_digest(journal,rid)
                else:
                    replay=verify_direct_archive(archive,journal);run_hash=replay['sha256'];journal_hash=None
                if run_hash is None:
                    raise RuntimeError('interrupted synthetic archive cannot be replayed; no retry attempted')
                ref=cases[assignment['case_id']]['reference']
                if args.semantic:
                    from qjig.evaluation_scoring import unavailable_failure_review
                    review_path=archive_path/'semantic-review'
                    if review_path.is_symlink() or not (review_path/'run.sqlite').is_file():
                        raise RuntimeError('interrupted semantic review archive unavailable; no retry attempted')
                    with RunArchive.open(review_path) as review_archive:
                        review=unavailable_failure_review(goal,archive,journal,ref,review_archive,
                            partition=assignment['work'][0]['partition'],expected_plan_sha256=plan['sha256'],
                            expected_run_sha256=run_hash,expected_reference_sha256=reference_digest(ref),
                            expected_journal_sha256=journal_hash,reviewer_spec=config['semantic_reviewer'],record=True)['review']
                        campaign.finish(rid,archive,journal,ref,expected_run_sha256=run_hash,
                            expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash,
                            semantic_review_archive=review_archive,expected_review_sha256=review['sha256'])
                else:
                    campaign.finish(rid,archive,journal,ref,expected_run_sha256=run_hash,
                                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash)
            print(json.dumps({'recovered_existing_assignment':True,'provider_calls':0}),flush=True)
        while True:
            result=run_campaign_batch(campaign,DRAFT,design,cases,journal=journal,archive_root=directory/'archives',
                config=config,want=3,max_bytes=6000,expected_config_sha256=config_hash,
                transport_factory=lambda assignment:SyntheticTransport(),max_assignments=10)
            print(json.dumps({'scored':result['scored'],'assigned':result['assigned'],'remaining':result['remaining']}),flush=True)
            if not result['remaining']:
                break
            if result['executed']==0:
                raise RuntimeError('synthetic campaign made no progress')
        if goal.audit_journal(journal)['status']!='verified':
            raise RuntimeError('synthetic goal and journal accounting differ')
        print(json.dumps({'status':'synthetic_complete','directory':str(directory),'assignments':reservation['assignments'],
                          'reserved_slots':reservation['work_items'],'judge_pairs_per_fresh_assignment':args.judge_pairs,'synthetic_calls_by_stage':dict(Counter(e.stage for e in journal.all_events() if e.kind=='intent')),
                          'semantic_assurance':'not_assessed','provider_calls':0}),flush=True)


if __name__=='__main__':
    main()
