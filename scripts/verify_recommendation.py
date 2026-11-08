#!/usr/bin/env python3
"""Reconstruct a recommendation from a hashed local manifest without provider calls."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qjig.applicability import ApplicabilityInputs
from qjig.contracts import Budget, ContractError
from qjig.evaluation_campaign import EvaluationCampaign
from qjig.evaluation_recommendation import build_verified_recommendation
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from verify_live_receipts import _open_readonly


def inspect_recommendation(path: Path, expected_sha256: str) -> dict:
    if not isinstance(expected_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):
        raise ContractError('manifest anchor required')
    raw=Path(path).read_bytes()
    if len(raw)>16*1024*1024:
        raise ContractError('manifest exceeds size limit')
    digest=hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest,expected_sha256):
        raise ContractError('manifest anchor differs')
    data=json.loads(raw)
    keys={'schema','goal_db','journal_db','archive_root','plan_id','plan_sha256','config_sha256','references',
          'run_sha256','reference_sha256','journal_sha256','review_sha256','outcome_review_sha256','case_root','case_inputs'}
    if not isinstance(data,dict) or set(data)!=keys or data.get('schema')!='qjig.live-manifest.v2':
        raise ContractError('reviewed manifest required')
    with closing(_open_readonly(data['goal_db'])) as goal_con, closing(_open_readonly(data['journal_db'])) as journal_con:
        row=goal_con.execute('SELECT value FROM policy WHERE id=1').fetchone()
        if row is None or journal_con.execute('PRAGMA user_version').fetchone()[0]!=1:
            raise ContractError('retained policy or journal unavailable')
        policy=json.loads(row[0])
        goal=GoalBudget(goal_con,Budget.from_dict(policy['total']),Budget.from_dict(policy['per_request']),
                        {name:Budget.from_dict(value) for name,value in policy['allocations'].items()},
                        'account_snapshot' in policy)
        campaign=EvaluationCampaign(goal,data['plan_id'],expected_plan_sha256=data['plan_sha256'])
        manifest=campaign._snapshot()[0]
        cases=data['case_inputs']
        if cases is not None:
            if not isinstance(cases,dict):
                raise ContractError('invalid case inputs')
            cases={key:{**value,'applicability_inputs':ApplicabilityInputs.from_dict(value['applicability_inputs'])}
                   for key,value in cases.items()}
        result=build_verified_recommendation(campaign,Journal(journal_con,time.time),Path(data['archive_root']),
            design=manifest['design'],references=data['references'],expected_design_sha256=manifest['design_sha256'],
            expected_config_sha256=data['config_sha256'],expected_run_sha256=data['run_sha256'],
            expected_reference_sha256=data['reference_sha256'],expected_journal_sha256=data['journal_sha256'],
            expected_review_sha256=data['review_sha256'],expected_outcome_review_sha256=data['outcome_review_sha256'],
            case_root=Path(data['case_root']) if data['case_root'] else None,case_inputs=cases)
    result['manifest_sha256']=digest
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--sha256',required=True,help='independently retained SHA-256 of the exact manifest bytes')
    args=parser.parse_args()
    try:
        result=inspect_recommendation(Path(args.manifest),args.sha256)
    except (OSError,sqlite3.Error,ContractError,ValueError,TypeError,KeyError,IndexError,AttributeError):
        result={'status':'invalid','issues':['manifest_or_retained_evidence_invalid'],'recommendation':None}
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['status'] in ('evaluated','inconclusive') else 1


if __name__=='__main__':
    raise SystemExit(main())
