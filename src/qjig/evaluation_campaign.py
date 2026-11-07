"""Durable, conservative execution state for one reserved evaluation plan.

This coordinates assignment receipts, not provider authorization or a general
scheduler. A claimed assignment is never automatically released or retried.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from .contracts import ContractError
from .evaluation_budget import make_evaluation_plan, validate_assignment_binding
from .evaluation_scoring import score_reserved_assignment
from .goal_budget import GoalBudget


class EvaluationCampaign:
    def __init__(self, goal: GoalBudget, plan_id: str, *, expected_plan_sha256: str):
        if not isinstance(goal, GoalBudget):
            raise ContractError('goal ledger required')
        validate_assignment_binding({'plan_id':plan_id,'plan_sha256':expected_plan_sha256,'arm':'combined','repeat':1})
        self._goal, self._plan_id, self._digest = goal, plan_id, expected_plan_sha256
        goal._con.execute('''CREATE TABLE IF NOT EXISTS evaluation_campaign_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL, request_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('started','scored')), payload TEXT NOT NULL,
            UNIQUE(plan_id,request_id,kind))''')
        goal._con.execute("CREATE TRIGGER IF NOT EXISTS campaign_events_no_update BEFORE UPDATE ON evaluation_campaign_events BEGIN SELECT RAISE(ABORT, 'campaign events immutable'); END")
        goal._con.execute("CREATE TRIGGER IF NOT EXISTS campaign_events_no_delete BEFORE DELETE ON evaluation_campaign_events BEGIN SELECT RAISE(ABORT, 'campaign events immutable'); END")
        self._snapshot()

    def _snapshot(self):
        row = self._goal._con.execute('SELECT set_id,manifest,sha256 FROM evaluation_plans WHERE plan_id=?',(self._plan_id,)).fetchone()
        if row is None:
            raise ContractError('evaluation plan unavailable')
        set_id, encoded, digest = row
        if (set_id != 'evaluation:'+self._plan_id or not hmac.compare_digest(digest,self._digest)
                or hashlib.sha256(encoded.encode('utf-8')).hexdigest() != digest):
            raise ContractError('evaluation plan anchor differs')
        try:
            manifest = json.loads(encoded)
            rebuilt = make_evaluation_plan(manifest['design'],manifest['case_hashes'],manifest['stage_templates'],
                                           manifest['assignments'],expected_design_sha256=manifest['design_sha256'])
        except (KeyError,TypeError,ValueError) as exc:
            raise ContractError('evaluation plan invalid') from exc
        if rebuilt['sha256'] != digest or rebuilt['manifest'] != manifest:
            raise ContractError('evaluation plan is not canonical')
        frozen = self._goal._con.execute('SELECT manifest,sha256 FROM run_sets WHERE set_id=?',(set_id,)).fetchone()
        if frozen is None:
            raise ContractError('evaluation run set unavailable')
        self._goal._verify_run_set(set_id,*frozen)
        assignments = {a['request_id']:a for a in manifest['assignments']}
        rows = self._goal._con.execute('SELECT request_id,kind,payload FROM evaluation_campaign_events WHERE plan_id=? ORDER BY seq',(self._plan_id,)).fetchall()
        started, scored = set(), set()
        for request_id,kind,payload in rows:
            if request_id not in assignments:
                raise ContractError('unassigned campaign event')
            try:
                data = json.loads(payload)
            except (TypeError,ValueError) as exc:
                raise ContractError('invalid campaign event') from exc
            if kind == 'started':
                if request_id in started or started-scored or data != {'plan_sha256':digest}:
                    raise ContractError('invalid campaign claim')
                started.add(request_id)
            elif kind == 'scored':
                if (request_id not in started or request_id in scored or not isinstance(data,dict)
                        or set(data) != {'plan_sha256','run_sha256','reference_sha256','journal_sha256','score_sha256'}
                        or data['plan_sha256'] != digest
                        or any(not isinstance(data[k],str) or len(data[k]) != 64 or any(c not in '0123456789abcdef' for c in data[k])
                               for k in ('run_sha256','reference_sha256','score_sha256'))
                        or (data['journal_sha256'] is not None and
                            (not isinstance(data['journal_sha256'],str) or len(data['journal_sha256']) != 64
                             or any(c not in '0123456789abcdef' for c in data['journal_sha256'])))):
                    raise ContractError('invalid campaign score receipt')
                scored.add(request_id)
            else:
                raise ContractError('invalid campaign event kind')
        return manifest,assignments,started,scored

    def status(self) -> dict:
        manifest,assignments,started,scored = self._snapshot()
        return {'plan_sha256':self._digest,'assigned':len(assignments),'scored':len(scored),
                'in_progress':sorted(started-scored),'unstarted':len(assignments)-len(started)}

    def claim(self, request_id: str) -> dict:
        con = self._goal._con
        con.execute('BEGIN IMMEDIATE')
        try:
            manifest,assignments,started,scored = self._snapshot()
            if not isinstance(request_id,str) or request_id not in assignments or request_id in started:
                raise ContractError('assignment unavailable or already claimed')
            if started-scored:
                raise ContractError('campaign recovery required before another assignment')
            if con.execute('SELECT 1 FROM required_work WHERE request_id=? AND attempt_id IS NOT NULL LIMIT 1',(request_id,)).fetchone():
                raise ContractError('assignment already has consumed work')
            assignment = assignments[request_id]
            con.execute('INSERT INTO evaluation_campaign_events(plan_id,request_id,kind,payload) VALUES(?,?,?,?)',
                        (self._plan_id,request_id,'started',json.dumps({'plan_sha256':self._digest},sort_keys=True)))
            con.execute('COMMIT')
        except BaseException:
            con.execute('ROLLBACK')
            raise
        family = next(c['family'] for c in manifest['design']['cases'] if c['id']==assignment['case_id'])
        partition = next(f['partition'] for f in manifest['design']['families'] if f['id']==family)
        return {'request_id':request_id,'case_id':assignment['case_id'],'case_sha256':manifest['case_hashes'][assignment['case_id']],
                'arm':assignment['arm'],'repeat':assignment['repeat'],'partition':partition,
                'plan_id':self._plan_id,'plan_sha256':self._digest,'design_sha256':manifest['design_sha256']}

    def finish(self, request_id: str, archive, journal, reference: dict, *, expected_run_sha256: str,
               expected_reference_sha256: str, expected_journal_sha256: str | None = None) -> dict:
        manifest,assignments,started,scored = self._snapshot()
        if request_id not in assignments or request_id not in started or request_id in scored:
            raise ContractError('assignment is not an unfinished claim')
        assignment = assignments[request_id]
        if archive.context().get('request',{}).get('request_id') != request_id:
            raise ContractError('archive request differs from claim')
        family = next(c['family'] for c in manifest['design']['cases'] if c['id']==assignment['case_id'])
        partition = next(f['partition'] for f in manifest['design']['families'] if f['id']==family)
        score = score_reserved_assignment(self._goal,archive,journal,reference,partition=partition,
            expected_plan_sha256=self._digest,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256)
        if (score['score']['case_id'],score['arm'],score['repeat']) != (assignment['case_id'],assignment['arm'],assignment['repeat']):
            raise ContractError('scored assignment differs from claim')
        encoded = json.dumps(score,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        score_hash = hashlib.sha256(encoded).hexdigest()
        payload = {'plan_sha256':self._digest,'run_sha256':expected_run_sha256,'reference_sha256':expected_reference_sha256,
                   'journal_sha256':expected_journal_sha256,'score_sha256':score_hash}
        con = self._goal._con
        con.execute('BEGIN IMMEDIATE')
        try:
            _,_,started,scored = self._snapshot()
            if request_id not in started or request_id in scored:
                raise ContractError('assignment claim changed')
            con.execute('INSERT INTO evaluation_campaign_events(plan_id,request_id,kind,payload) VALUES(?,?,?,?)',
                        (self._plan_id,request_id,'scored',json.dumps(payload,sort_keys=True,separators=(',',':'))))
            con.execute('COMMIT')
        except BaseException:
            con.execute('ROLLBACK')
            raise
        return {'status':'scored','request_id':request_id,'score_sha256':score_hash}
