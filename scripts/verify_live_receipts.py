#!/usr/bin/env python3
"""Inspect a retained campaign without provider calls or writable database access."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

# The repository command also works without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qjig.applicability import ApplicabilityInputs
from qjig.contracts import Budget, ContractError
from qjig.evaluation_campaign import EvaluationCampaign
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from qjig.live_receipts import inspect_campaign_receipts


def _open_readonly(path):
    file = Path(path)
    if file.is_symlink() or not file.is_file():
        raise ContractError('retained database unavailable')
    return sqlite3.connect(file.resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)


def inspect_manifest(path, expected_sha256=None):
    raw=Path(path).read_bytes()
    if len(raw)>16*1024*1024:
        raise ContractError('manifest exceeds size limit')
    digest=hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and (len(expected_sha256)!=64 or not hmac.compare_digest(digest,expected_sha256)):
        raise ContractError('manifest anchor differs')
    data=json.loads(raw)
    keys={'schema','goal_db','journal_db','archive_root','plan_id','plan_sha256','config_sha256','references',
          'run_sha256','reference_sha256','journal_sha256','review_sha256','case_root','case_inputs'}
    if not isinstance(data,dict) or set(data)!=keys or data['schema']!='qjig.live-manifest.v1':
        raise ContractError('invalid live manifest')
    with closing(_open_readonly(data['goal_db'])) as goal_con, closing(_open_readonly(data['journal_db'])) as journal_con:
        row=goal_con.execute('SELECT value FROM policy WHERE id=1').fetchone()
        if row is None or journal_con.execute('PRAGMA user_version').fetchone()[0]!=1:
            raise ContractError('retained policy or journal unavailable')
        policy=json.loads(row[0])
        goal=GoalBudget(goal_con,Budget.from_dict(policy['total']),Budget.from_dict(policy['per_request']),
                        {name:Budget.from_dict(value) for name,value in policy['allocations'].items()},
                        'account_snapshot' in policy)
        campaign=EvaluationCampaign(goal,data['plan_id'],expected_plan_sha256=data['plan_sha256'])
        journal=Journal(journal_con,time.time)
        cases=data['case_inputs']
        if cases is not None:
            if not isinstance(cases,dict):
                raise ContractError('invalid case inputs')
            cases={key:{**value,'applicability_inputs':ApplicabilityInputs.from_dict(value['applicability_inputs'])}
                   for key,value in cases.items()}
        report=inspect_campaign_receipts(campaign,journal,Path(data['archive_root']),references=data['references'],
            expected_config_sha256=data['config_sha256'],expected_run_sha256=data['run_sha256'],
            expected_reference_sha256=data['reference_sha256'],expected_journal_sha256=data['journal_sha256'],
            expected_review_sha256=data['review_sha256'],case_root=Path(data['case_root']) if data['case_root'] else None,
            case_inputs=cases)
    report['manifest_sha256']=digest
    if expected_sha256 is None:
        report['issues']=sorted(set(report['issues']+['manifest_anchor_unavailable']))
        if report['status']=='structurally_complete': report['status']='incomplete'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--sha256',help='independently retained SHA-256 of exact manifest bytes')
    args=parser.parse_args()
    try:
        result=inspect_manifest(args.manifest,args.sha256)
    except (OSError,sqlite3.Error,ContractError,ValueError,TypeError,KeyError,IndexError,AttributeError):
        result={'status':'invalid','issues':['manifest_or_retained_evidence_invalid']}
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['status']=='structurally_complete' else 1


if __name__=='__main__':
    raise SystemExit(main())
