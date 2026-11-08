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


def applicability_digest(inputs) -> str:
    """Hash canonical recorded applicability inputs, not their authority or truth."""
    from .applicability import ApplicabilityInputs
    if not isinstance(inputs,ApplicabilityInputs):
        raise ContractError('recorded applicability inputs required')
    checked=ApplicabilityInputs.from_dict(inputs.to_dict())
    encoded=json.dumps(checked.to_dict(),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def check_archive_config(frozen: dict, context: dict, assignment: dict) -> None:
    """Check archive settings against frozen campaign settings, not their truth."""
    stages=frozen['stages'];arm=assignment['arm']
    if context.get('want') != frozen['want'] or context.get('max_bytes') != frozen['max_bytes']:
        raise ContractError('archive packet configuration differs')
    metadata = context.get('applicability_inputs') if arm in ('combined','decomposition_only') else context.get('catalog_applicability') if arm=='retrieval_only' else None
    if arm in ('combined','decomposition_only','retrieval_only') and metadata is None:
        raise ContractError('archive applicability binding missing')
    if metadata is not None:
        from .applicability import ApplicabilityInputs
        if applicability_digest(ApplicabilityInputs.from_dict(metadata)) != frozen['case_applicability'][assignment['case_id']]:
            raise ContractError('archive applicability binding differs')
    if arm in ('combined','decomposition_only'):
        if context.get('schema') != 'qjig.applicability-deferral.v1' and context.get('max_judge_pairs') != frozen.get('max_judge_pairs'):
            raise ContractError('archive judge quota differs')
        if (context.get('schema') != 'qjig.applicability-deferral.v1'
                and context.get('planner_prompt_version','legacy_v1') != frozen.get('planner_prompt_version','legacy_v1')):
            raise ContractError('archive planner prompt version differs')
        for name in ('planner','judge','reviewer'):
            actual=context.get(name);spec=stages[name]
            if (not isinstance(actual,dict) or actual.get('provider') != spec['provider']
                    or actual.get('model') != spec['model']['id'] or actual.get('max_tokens') != spec['output_tokens']
                    or actual.get('max_price') != spec['max_price'] or actual.get('route') != spec.get('route')):
                raise ContractError('archive stage configuration differs')
    else:
        spec=stages['direct']
        if (context.get('provider') != spec['provider'] or context.get('model') != spec['model']['id']
                or context.get('max_tokens') != spec['output_tokens'] or context.get('max_price') != spec['max_price']
                or context.get('route') != spec.get('route')
                or context.get('followups') != (0 if arm=='direct_full_evidence' else 1)):
            raise ContractError('archive direct configuration differs')


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
        goal._con.execute('CREATE TABLE IF NOT EXISTS evaluation_campaign_config (plan_id TEXT PRIMARY KEY, value TEXT NOT NULL, sha256 TEXT NOT NULL)')
        goal._con.execute("CREATE TRIGGER IF NOT EXISTS campaign_config_no_update BEFORE UPDATE ON evaluation_campaign_config BEGIN SELECT RAISE(ABORT, 'campaign config immutable'); END")
        goal._con.execute("CREATE TRIGGER IF NOT EXISTS campaign_config_no_delete BEFORE DELETE ON evaluation_campaign_config BEGIN SELECT RAISE(ABORT, 'campaign config immutable'); END")
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
        config_row = self._goal._con.execute('SELECT value,sha256 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
        config_digest = None
        config_schema = None
        if config_row is not None:
            config_value,config_digest = config_row
            if hashlib.sha256(config_value.encode('utf-8')).hexdigest() != config_digest:
                raise ContractError('campaign configuration integrity differs')
            config_schema = json.loads(config_value).get('schema')
        started, scored = set(), set()
        for request_id,kind,payload in rows:
            if request_id not in assignments:
                raise ContractError('unassigned campaign event')
            try:
                data = json.loads(payload)
            except (TypeError,ValueError) as exc:
                raise ContractError('invalid campaign event') from exc
            if kind == 'started':
                expected_claim = {'plan_sha256':digest, **({'config_sha256':config_digest} if config_digest is not None else {})}
                if request_id in started or started-scored or data != expected_claim:
                    raise ContractError('invalid campaign claim')
                started.add(request_id)
            elif kind == 'scored':
                if (request_id not in started or request_id in scored or not isinstance(data,dict)
                        or set(data) != ({'plan_sha256','run_sha256','reference_sha256','journal_sha256','score_sha256'} | ({'semantic_review_sha256'} if config_schema in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7') else set()) | ({'outcome_review_sha256'} if config_schema=='qjig.campaign-config.v7' else set()))
                        or data['plan_sha256'] != digest
                        or any(not isinstance(data[k],str) or len(data[k]) != 64 or any(c not in '0123456789abcdef' for c in data[k])
                               for k in (('run_sha256','reference_sha256','score_sha256','semantic_review_sha256','outcome_review_sha256') if config_schema=='qjig.campaign-config.v7' else ('run_sha256','reference_sha256','score_sha256','semantic_review_sha256') if config_schema in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7') else ('run_sha256','reference_sha256','score_sha256')))
                        or (data['journal_sha256'] is not None and
                            (not isinstance(data['journal_sha256'],str) or len(data['journal_sha256']) != 64
                             or any(c not in '0123456789abcdef' for c in data['journal_sha256'])))):
                    raise ContractError('invalid campaign score receipt')
                scored.add(request_id)
            else:
                raise ContractError('invalid campaign event kind')
        return manifest,assignments,started,scored

    def freeze_config(self, config: dict, *, want: int, max_bytes: int, case_applicability: dict, planner_prompt_version: str = 'legacy_v1', max_judge_pairs: int | None = None) -> str:
        """Persist declared stage settings and shared packet limits before claims."""
        from .direct_preflight import direct_run_allocations
        from .fresh_preflight import fresh_run_allocations
        if (type(want) is not int or not 1 <= want <= 100 or type(max_bytes) is not int or not 1 <= max_bytes <= 1024*1024
                or not isinstance(config,dict) or set(config) not in ({'direct','planner','judge','reviewer'},
                                                                      {'direct','planner','judge','reviewer','semantic_reviewer'},
                                                                      {'direct','planner','judge','reviewer','semantic_reviewer','outcome_reviewer'})
                or any(not isinstance(v,dict) or set(v) not in ({'provider','model','input_tokens','output_tokens','max_price'},
                                                               {'provider','model','input_tokens','output_tokens','max_price','route'})
                       for v in config.values())):
            raise ContractError('invalid campaign configuration')
        if 'outcome_reviewer' in config and max_judge_pairs is None:
            raise ContractError('outcome review requires bounded judge work')
        has_routes=any('route' in spec for spec in config.values())
        if has_routes and (max_judge_pairs is None or 'semantic_reviewer' not in config
                           or any(not spec.get('route') or spec['provider']!='openrouter' for spec in config.values())):
            raise ContractError('all bounded campaign stages require an explicit hosted route')
        if max_judge_pairs is not None:
            from .plans import MAX_PREDICATES
            from .acquisition import MAX_ROUNDS
            if (type(max_judge_pairs) is not int or not 1 <= max_judge_pairs <= MAX_PREDICATES * MAX_ROUNDS
                    or 'semantic_reviewer' not in config):
                raise ContractError('invalid campaign judge quota')
        if planner_prompt_version not in ('legacy_v1', 'exception_applicability_v2'):
            raise ContractError('unsupported planner prompt version')
        direct,planner,judge,reviewer=(config[k] for k in ('direct','planner','judge','reviewer'))
        if planner['provider'] != judge['provider']:
            raise ContractError('fresh planner and judge providers must match')
        payload={'schema':'qjig.campaign-config.v2','plan_sha256':self._digest,'want':want,'max_bytes':max_bytes,
                 'stages':config,'case_applicability':case_applicability}
        if 'semantic_reviewer' in config:
            payload['schema']='qjig.campaign-config.v7' if 'outcome_reviewer' in config else 'qjig.campaign-config.v6' if has_routes else 'qjig.campaign-config.v5' if max_judge_pairs is not None else 'qjig.campaign-config.v4'
            if max_judge_pairs is not None:
                payload['max_judge_pairs']=max_judge_pairs
            payload['planner_prompt_version']=planner_prompt_version
        elif planner_prompt_version != 'legacy_v1':
            payload['schema']='qjig.campaign-config.v3'
            payload['planner_prompt_version']=planner_prompt_version
        try:
            encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
            digest=hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        except (TypeError,ValueError,UnicodeError) as exc:
            raise ContractError('campaign configuration is not finite JSON') from exc
        con=self._goal._con
        con.execute('BEGIN IMMEDIATE')
        try:
            manifest,assignments,started,_=self._snapshot()
            case_ids={c['id'] for c in manifest['design']['cases']}
            if (not isinstance(case_applicability,dict) or set(case_applicability)!=case_ids
                    or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v)
                           for v in case_applicability.values())):
                raise ContractError('complete case applicability bindings required')
            row=con.execute('SELECT value,sha256 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
            if row is not None:
                if row != (encoded,digest):
                    raise ContractError('campaign configuration differs from frozen value')
                con.execute('COMMIT')
                return digest
            if started:
                raise ContractError('campaign configuration must precede claims')
            for assignment in assignments.values():
                arm,rid=assignment['arm'],assignment['request_id']
                partition=assignment['work'][0]['partition']
                if arm in ('combined','decomposition_only'):
                    work=fresh_run_allocations(request_id=rid,partition=partition,provider=planner['provider'],
                        planner_model=planner['model'],judge_model=judge['model'],planner_input=planner['input_tokens'],
                        planner_output=planner['output_tokens'],judge_input=judge['input_tokens'],judge_output=judge['output_tokens'],
                        planner_price=planner['max_price'],judge_price=judge['max_price'],reviewer=reviewer,max_judge_pairs=max_judge_pairs,
                        planner_route=planner.get('route'),judge_route=judge.get('route'))
                elif arm in ('direct_full_evidence','direct_retrieval','retrieval_only'):
                    work=direct_run_allocations(request_id=rid,partition=partition,provider=direct['provider'],model=direct['model'],
                        input_tokens=direct['input_tokens'],output_tokens=direct['output_tokens'],max_price=direct['max_price'],
                        followups=0 if arm=='direct_full_evidence' else 1,route=direct.get('route'))
                else:
                    raise ContractError('unsupported campaign arm')
                if 'semantic_reviewer' in config:
                    from .semantic_preflight import semantic_review_allocation
                    work.append(semantic_review_allocation(request_id=rid,partition=partition,spec=config['semantic_reviewer']))
                if 'outcome_reviewer' in config:
                    from .outcome_preflight import outcome_review_allocation
                    work.append(outcome_review_allocation(request_id=rid,partition=partition,spec=config['outcome_reviewer']))
                if sorted(work,key=lambda x:x['work_id']) != assignment['work']:
                    raise ContractError('campaign configuration differs from reserved work')
            con.execute('INSERT INTO evaluation_campaign_config VALUES(?,?,?)',(self._plan_id,encoded,digest))
            con.execute('COMMIT')
            return digest
        except BaseException:
            con.execute('ROLLBACK')
            raise

    def require_config(self, config: dict, *, want: int, max_bytes: int, expected_config_sha256: str) -> None:
        """Check an externally anchored frozen configuration without modifying it."""
        if not isinstance(expected_config_sha256,str) or len(expected_config_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_config_sha256):
            raise ContractError('campaign configuration anchor required')
        row=self._goal._con.execute('SELECT value,sha256 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
        if row is None:
            raise ContractError('campaign configuration unavailable')
        encoded,digest=row
        if (hashlib.sha256(encoded.encode('utf-8')).hexdigest()!=digest or not hmac.compare_digest(digest,expected_config_sha256)):
            raise ContractError('campaign configuration anchor differs')
        try:
            frozen=json.loads(encoded)
            payload={'schema':'qjig.campaign-config.v2','plan_sha256':self._digest,'want':want,
                     'max_bytes':max_bytes,'stages':config,'case_applicability':frozen['case_applicability']}
            if frozen.get('schema') == 'qjig.campaign-config.v3' and frozen.get('planner_prompt_version') == 'exception_applicability_v2':
                payload.update(schema='qjig.campaign-config.v3', planner_prompt_version='exception_applicability_v2')
            elif (frozen.get('schema') == 'qjig.campaign-config.v4'
                  and frozen.get('planner_prompt_version') in ('legacy_v1','exception_applicability_v2')
                  and isinstance(config,dict) and 'semantic_reviewer' in config):
                payload.update(schema='qjig.campaign-config.v4', planner_prompt_version=frozen['planner_prompt_version'])
            elif (frozen.get('schema') == 'qjig.campaign-config.v5'
                  and frozen.get('planner_prompt_version') in ('legacy_v1','exception_applicability_v2')
                  and type(frozen.get('max_judge_pairs')) is int and 1 <= frozen['max_judge_pairs'] <= 12
                  and isinstance(config,dict) and 'semantic_reviewer' in config):
                payload.update(schema='qjig.campaign-config.v5', planner_prompt_version=frozen['planner_prompt_version'],
                               max_judge_pairs=frozen['max_judge_pairs'])
            elif (frozen.get('schema') == 'qjig.campaign-config.v6'
                  and frozen.get('planner_prompt_version') in ('legacy_v1','exception_applicability_v2')
                  and type(frozen.get('max_judge_pairs')) is int and 1 <= frozen['max_judge_pairs'] <= 12
                  and isinstance(config,dict) and 'semantic_reviewer' in config
                  and all(isinstance(spec,dict) and spec.get('route') and spec.get('provider')=='openrouter' for spec in config.values())):
                payload.update(schema='qjig.campaign-config.v6', planner_prompt_version=frozen['planner_prompt_version'],
                               max_judge_pairs=frozen['max_judge_pairs'])
            elif (frozen.get('schema') == 'qjig.campaign-config.v7'
                  and frozen.get('planner_prompt_version') in ('legacy_v1','exception_applicability_v2')
                  and type(frozen.get('max_judge_pairs')) is int and 1 <= frozen['max_judge_pairs'] <= 12
                  and isinstance(config,dict) and set(config)=={'direct','planner','judge','reviewer','semantic_reviewer','outcome_reviewer'}):
                payload.update(schema='qjig.campaign-config.v7', planner_prompt_version=frozen['planner_prompt_version'],
                               max_judge_pairs=frozen['max_judge_pairs'])
            expected=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        except (KeyError,TypeError,ValueError,UnicodeError) as exc:
            raise ContractError('campaign configuration is not finite JSON') from exc
        if encoded != expected:
            raise ContractError('campaign configuration differs')
        return frozen

    def status(self) -> dict:
        manifest,assignments,started,scored = self._snapshot()
        return {'plan_sha256':self._digest,'assigned':len(assignments),'scored':len(scored),
                'in_progress':sorted(started-scored),'unstarted':len(assignments)-len(started)}

    def claim(self, request_id: str) -> dict:
        con = self._goal._con
        con.execute('BEGIN IMMEDIATE')
        try:
            manifest,assignments,started,scored = self._snapshot()
            if any('outcome_review' in template for template in manifest['stage_templates'].values()) and con.execute('SELECT 1 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone() is None:
                raise ContractError('outcome campaign configuration required')
            if not isinstance(request_id,str) or request_id not in assignments or request_id in started:
                raise ContractError('assignment unavailable or already claimed')
            if started-scored:
                raise ContractError('campaign recovery required before another assignment')
            if ('semantic_review' in manifest['stage_templates'][assignments[request_id]['arm']]
                    and con.execute('SELECT 1 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone() is None):
                raise ContractError('semantic review campaign configuration required')
            if con.execute('SELECT 1 FROM required_work WHERE request_id=? AND attempt_id IS NOT NULL LIMIT 1',(request_id,)).fetchone():
                raise ContractError('assignment already has consumed work')
            assignment = assignments[request_id]
            config_row=con.execute('SELECT sha256 FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
            payload={'plan_sha256':self._digest, **({'config_sha256':config_row[0]} if config_row else {})}
            con.execute('INSERT INTO evaluation_campaign_events(plan_id,request_id,kind,payload) VALUES(?,?,?,?)',
                        (self._plan_id,request_id,'started',json.dumps(payload,sort_keys=True)))
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
               expected_reference_sha256: str, expected_journal_sha256: str | None = None,
               semantic_review_archive=None, expected_review_sha256: str | None = None,
               outcome_review_archive=None, expected_outcome_review_sha256: str | None = None) -> dict:
        manifest,assignments,started,scored = self._snapshot()
        if request_id not in assignments or request_id not in started or request_id in scored:
            raise ContractError('assignment is not an unfinished claim')
        assignment = assignments[request_id]
        if archive.context().get('request',{}).get('request_id') != request_id:
            raise ContractError('archive request differs from claim')
        config_row=self._goal._con.execute('SELECT value FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
        frozen = json.loads(config_row[0]) if config_row is not None else None
        if frozen is not None:
            check_archive_config(frozen, archive.context(), assignment)
        family = next(c['family'] for c in manifest['design']['cases'] if c['id']==assignment['case_id'])
        partition = next(f['partition'] for f in manifest['design']['families'] if f['id']==family)
        scoring_options=dict(partition=partition,expected_plan_sha256=self._digest,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256)
        if frozen is not None and frozen.get('schema')=='qjig.campaign-config.v7':
            from .evaluation_scoring import score_outcome_reviewed_assignment
            score=score_outcome_reviewed_assignment(self._goal,archive,journal,reference,semantic_review_archive,outcome_review_archive,
                expected_review_sha256=expected_review_sha256,reviewer_spec=frozen['stages']['semantic_reviewer'],
                expected_outcome_review_sha256=expected_outcome_review_sha256,outcome_reviewer_spec=frozen['stages']['outcome_reviewer'],**scoring_options)
        elif frozen is not None and frozen.get('schema') in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6'):
            if outcome_review_archive is not None or expected_outcome_review_sha256 is not None:
                raise ContractError('outcome review requires v7 campaign')
            from .evaluation_scoring import score_reviewed_reserved_assignment
            score = score_reviewed_reserved_assignment(self._goal,archive,journal,reference,semantic_review_archive,
                expected_review_sha256=expected_review_sha256,reviewer_spec=frozen['stages']['semantic_reviewer'],**scoring_options)
        else:
            if semantic_review_archive is not None or expected_review_sha256 is not None or outcome_review_archive is not None or expected_outcome_review_sha256 is not None:
                raise ContractError('semantic review requires a v4 campaign')
            score = score_reserved_assignment(self._goal,archive,journal,reference,**scoring_options)
        if (score['score']['case_id'],score['arm'],score['repeat']) != (assignment['case_id'],assignment['arm'],assignment['repeat']):
            raise ContractError('scored assignment differs from claim')
        if score['score'].get('reconciliation_required') is True:
            raise ContractError('campaign reconciliation required before completion')
        encoded = json.dumps(score,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        score_hash = hashlib.sha256(encoded).hexdigest()
        payload = {'plan_sha256':self._digest,'run_sha256':expected_run_sha256,'reference_sha256':expected_reference_sha256,
                   'journal_sha256':expected_journal_sha256,'score_sha256':score_hash}
        if frozen is not None and frozen.get('schema') in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7'):
            payload['semantic_review_sha256']=expected_review_sha256
        if frozen is not None and frozen.get('schema')=='qjig.campaign-config.v7':
            payload['outcome_review_sha256']=expected_outcome_review_sha256
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


def run_campaign_assignment(campaign: EvaluationCampaign, request_id: str, root, design: dict,
                            lock: dict, reference: dict, protected: list[dict], *,
                            applicability_inputs, transport, archive, journal, config: dict,
                            want: int, max_bytes: int, expected_config_sha256: str, semantic_review_archive=None, outcome_review_archive=None) -> dict:
    """Run and score one claimed factorial assignment; never retry an interrupted claim.

    Input/price bounds, evidence configuration and external anchors are caller
    assertions. Hosted transport remains subject to its existing refusal gate.
    """
    from .applicability import ApplicabilityInputs
    from .budgets import BudgetLedger
    from .direct_preflight import direct_run_allocations, direct_slot_reservation
    from .evaluation_cases import prepare_evaluation_case
    from .evaluation_direct import run_locked_direct
    from .evaluation_fresh import run_locked_fresh
    from .evaluation_replay import verify_direct_archive
    from .evaluation_scoring import fresh_journal_digest, reference_digest
    from .fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from .journal import Journal
    from .replay import verify_archive
    from .run_archive import RunArchive
    if (not isinstance(campaign,EvaluationCampaign) or not isinstance(archive,RunArchive)
            or not isinstance(journal,Journal) or not isinstance(applicability_inputs,ApplicabilityInputs)
            or type(want) is not int or not 1 <= want <= 100 or type(max_bytes) is not int or not 1 <= max_bytes <= 1024*1024):
        raise ContractError('invalid campaign run inputs')
    frozen_config=campaign.require_config(config,want=want,max_bytes=max_bytes,expected_config_sha256=expected_config_sha256)
    outcome_enabled=frozen_config['schema']=='qjig.campaign-config.v7'
    semantic = frozen_config['schema'] in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7')
    quota = frozen_config.get('max_judge_pairs')
    if semantic and (not isinstance(semantic_review_archive,RunArchive) or semantic_review_archive is archive
                     or semantic_review_archive.events() or semantic_review_archive.revision_ids() or semantic_review_archive.source_ids()
                     or semantic_review_archive._con.execute('SELECT COUNT(*) FROM run_context').fetchone()[0]):
        raise ContractError('new semantic review archive required')
    if not semantic and semantic_review_archive is not None:
        raise ContractError('semantic review archive requires v4 campaign')
    if outcome_enabled and (not isinstance(outcome_review_archive,RunArchive) or outcome_review_archive in (archive,semantic_review_archive)
            or outcome_review_archive.events() or outcome_review_archive.revision_ids() or outcome_review_archive.source_ids()
            or outcome_review_archive._con.execute('SELECT COUNT(*) FROM run_context').fetchone()[0]):
        raise ContractError('new outcome review archive required')
    if not outcome_enabled and outcome_review_archive is not None:
        raise ContractError('outcome review archive requires v7 campaign')
    manifest,assignments,started,_ = campaign._snapshot()
    if not isinstance(request_id,str) or request_id not in assignments or request_id in started:
        raise ContractError('campaign assignment unavailable')
    assignment=assignments[request_id];arm=assignment['arm'];case_id=assignment['case_id']
    if frozen_config['case_applicability'].get(case_id) != applicability_digest(applicability_inputs):
        raise ContractError('campaign case applicability binding differs')
    if design != manifest['design'] or not isinstance(lock,dict) or lock.get('case_id') != case_id:
        raise ContractError('campaign case or design differs')
    prepared=prepare_evaluation_case(root,design,lock,reference,protected,
        expected_design_sha256=manifest['design_sha256'],expected_case_sha256=manifest['case_hashes'][case_id])
    if (applicability_inputs.as_of != prepared.as_of or applicability_inputs.request_entities != frozenset(prepared.entities)
            or applicability_inputs.historical_as_known != prepared.historical_as_known):
        raise ContractError('campaign applicability differs')
    from .sources import SourceRevision,decode_source
    revisions=[SourceRevision.create(source.path,'evaluation_allowlist',decode_source(source.raw,encoding='utf-8'))
               for source in prepared.sources]
    if {revision.revision_id for revision in revisions} != {member.revision_id for member in applicability_inputs.collection.members}:
        raise ContractError('campaign applicability source set differs')
    applicability_deferral = False
    if arm in ('direct_full_evidence','decomposition_only'):
        from .evaluation import _full_source_entries,_full_source_packet
        _full_source_packet(_full_source_entries(revisions),max_bytes)
        if arm == 'decomposition_only':
            from .applicability import Applicability,combine_applicability,scope_applicability
            applicability_deferral = any(combine_applicability(applicability_inputs.verdict(revision.revision_id),
                scope_applicability(prepared.scope,applicability_inputs.collection.member(revision.revision_id).scope))
                is not Applicability.MATCH for revision in revisions)
    if (not isinstance(config,dict) or set(config) != ({'direct','planner','judge','reviewer','semantic_reviewer','outcome_reviewer'} if outcome_enabled else {'direct','planner','judge','reviewer','semantic_reviewer'} if semantic else {'direct','planner','judge','reviewer'})
            or any(not isinstance(spec,dict) or set(spec) != ({'provider','model','input_tokens','output_tokens','max_price','route'} if 'route' in spec else {'provider','model','input_tokens','output_tokens','max_price'})
                   for spec in config.values())):
        raise ContractError('invalid campaign stage configuration')
    direct,planner,judge,reviewer=(config[k] for k in ('direct','planner','judge','reviewer'))
    partition=assignment['work'][0]['partition']
    if arm in ('combined','decomposition_only'):
        if planner['provider'] != judge['provider']:
            raise ContractError('fresh planner and judge providers must match')
        expected=fresh_run_allocations(request_id=request_id,partition=partition,provider=planner['provider'],
            planner_model=planner['model'],judge_model=judge['model'],planner_input=planner['input_tokens'],
            planner_output=planner['output_tokens'],judge_input=judge['input_tokens'],judge_output=judge['output_tokens'],
            planner_price=planner['max_price'],judge_price=judge['max_price'],reviewer=reviewer,max_judge_pairs=quota,
            planner_route=planner.get('route'),judge_route=judge.get('route'))
    elif arm in ('direct_full_evidence','direct_retrieval','retrieval_only'):
        expected=direct_run_allocations(request_id=request_id,partition=partition,provider=direct['provider'],model=direct['model'],
            input_tokens=direct['input_tokens'],output_tokens=direct['output_tokens'],max_price=direct['max_price'],
            followups=0 if arm=='direct_full_evidence' else 1,route=direct.get('route'))
    else:
        raise ContractError('unsupported campaign arm')
    if semantic:
        from .semantic_preflight import semantic_review_allocation
        expected.append(semantic_review_allocation(request_id=request_id,partition=partition,spec=config['semantic_reviewer']))
    if outcome_enabled:
        from .outcome_preflight import outcome_review_allocation
        expected.append(outcome_review_allocation(request_id=request_id,partition=partition,spec=config['outcome_reviewer']))
    if sorted(expected,key=lambda x:x['work_id']) != assignment['work']:
        raise ContractError('campaign configuration differs from reserved work')
    if (archive._con.execute('SELECT COUNT(*) FROM run_context').fetchone()[0] or archive.events()
            or archive.revision_ids() or archive.source_ids() or journal.events(request_id)):
        raise ContractError('campaign requires a new archive and unused request')
    if campaign._goal.audit_journal(journal)['status'] != 'verified':
        raise ContractError('campaign goal and journal accounting differ')
    claim=campaign.claim(request_id)
    ledger=BudgetLedger(campaign._goal._per_request,journal,request_id,goal_budget=campaign._goal,partition=partition)
    binding={'plan_id':campaign._plan_id,'plan_sha256':campaign._digest,'arm':arm,'repeat':claim['repeat']}
    set_id='evaluation:'+campaign._plan_id
    if applicability_deferral:
        from .contracts import Request
        from .evaluation_deferral import record_applicability_deferral,verify_applicability_deferral
        request=Request(request_id,prepared.question,prepared.role,prepared.role_version,prepared.scope)
        case_binding={'case_id':case_id,'design_sha256':manifest['design_sha256'],
                      'case_sha256':claim['case_sha256'],'reference_sha256':reference_digest(reference)}
        record_applicability_deferral(archive,request,case_binding,binding,applicability_inputs,revisions,
                                      want=want,max_bytes=max_bytes,stages=config)
        replay=verify_applicability_deferral(archive,journal)
        if replay['status']!='unanchored':
            raise ContractError('campaign applicability deferral is not replayable')
        run_hash,journal_hash=replay['sha256'],None
    elif arm in ('combined','decomposition_only'):
        def factory(req):
            spec = planner if req.stage=='planner' else reviewer if req.stage=='plan_review' else judge
            return fresh_slot_reservation(campaign._goal,set_id,request_id=request_id,partition=partition,
                request=req,model=spec['model'],input_tokens=spec['input_tokens'],input_bound_provenance='declared campaign bound',
                **({'max_judge_pairs':quota,'journal':journal} if quota is not None else {}))
        run_locked_fresh(root,design,lock,reference,protected,expected_design_sha256=manifest['design_sha256'],
            expected_case_sha256=claim['case_sha256'],applicability_inputs=applicability_inputs,ledger=ledger,transport=transport,
            archive=archive,planner=(planner['provider'],planner['model']['id']),judge=(judge['provider'],judge['model']['id']),
            reviewer=(reviewer['provider'],reviewer['model']['id']),planner_max_tokens=planner['output_tokens'],
            judge_max_tokens=judge['output_tokens'],reviewer_max_tokens=reviewer['output_tokens'],
            planner_max_price=planner['max_price'],judge_max_price=judge['max_price'],reviewer_max_price=reviewer['max_price'],
            reservation_factory=factory,review_reservation_factory=factory,want=want,max_bytes=max_bytes,
            assignment_binding=binding,evidence_mode='full' if arm=='decomposition_only' else 'catalog',
            planner_prompt_version=frozen_config.get('planner_prompt_version','legacy_v1'),max_judge_pairs=quota,
            planner_route=planner.get('route'),judge_route=judge.get('route'),reviewer_route=reviewer.get('route'))
        replay=verify_archive(archive)
        if replay.status not in ('unanchored','incomplete') or replay.digest is None:
            raise ContractError('campaign fresh archive is not replayable')
        run_hash,journal_hash=replay.digest,fresh_journal_digest(journal,request_id)
    else:
        def factory(req):
            return direct_slot_reservation(campaign._goal,set_id,request_id=request_id,partition=partition,
                request=req,model=direct['model'],input_tokens=direct['input_tokens'],input_bound_provenance='declared campaign bound')
        mode={'direct_full_evidence':'full','direct_retrieval':'retrieved','retrieval_only':'catalog'}[arm]
        run_locked_direct(root,design,lock,reference,protected,expected_design_sha256=manifest['design_sha256'],
            expected_case_sha256=claim['case_sha256'],ledger=ledger,transport=transport,archive=archive,
            provider=direct['provider'],model=direct['model']['id'],max_tokens=direct['output_tokens'],
            want=want,max_bytes=max_bytes,followups=0 if mode=='full' else 1,evidence_mode=mode,
            applicability_inputs=applicability_inputs,reservation_factory=factory,max_price=direct['max_price'],assignment_binding=binding,route=direct.get('route'))
        replay=verify_direct_archive(archive,journal)
        if replay['status'] not in ('unanchored','incomplete') or replay['sha256'] is None:
            raise ContractError('campaign direct archive is not replayable')
        run_hash,journal_hash=replay['sha256'],None
    review_hash = None
    original_incomplete = not applicability_deferral and (replay.status == 'incomplete' if arm in ('combined','decomposition_only') else replay['status'] == 'incomplete')
    if semantic:
        from .evaluation_semantic_review import (review_direct_semantics,review_fresh_semantics,
                                                  verify_direct_semantic_review,verify_fresh_semantic_review)
        from .semantic_preflight import semantic_review_reservation
        spec=config['semantic_reviewer']
        def review_factory(req):
            return semantic_review_reservation(campaign._goal,set_id,request_id=request_id,partition=partition,request=req,spec=spec)
        opts=dict(review_archive=semantic_review_archive,expected_run_sha256=run_hash,provider=spec['provider'],
                  model=spec['model']['id'],max_tokens=spec['output_tokens'],max_price=spec['max_price'],reservation_factory=review_factory,route=spec.get('route'))
        if original_incomplete:
            from .evaluation_scoring import unavailable_failure_review
            checked=unavailable_failure_review(campaign._goal,archive,journal,reference,semantic_review_archive,
                partition=partition,expected_plan_sha256=campaign._digest,expected_run_sha256=run_hash,
                expected_reference_sha256=reference_digest(reference),expected_journal_sha256=journal_hash,
                reviewer_spec=spec,record=True)['review']
        elif arm in ('combined','decomposition_only') and not applicability_deferral:
            review_fresh_semantics(archive,journal,ledger,transport,reference=reference,expected_reference_sha256=reference_digest(reference),
                                   expected_journal_sha256=journal_hash,**opts)
            checked=verify_fresh_semantic_review(archive,journal,semantic_review_archive,reference=reference,
                expected_reference_sha256=reference_digest(reference),expected_run_sha256=run_hash,expected_journal_sha256=journal_hash)
        elif not applicability_deferral:
            review_direct_semantics(archive,journal,ledger,transport,**opts)
            checked=verify_direct_semantic_review(archive,journal,semantic_review_archive,expected_run_sha256=run_hash)
        else:
            from .evaluation_semantic_review import record_unavailable_applicability_review
            checked=record_unavailable_applicability_review(archive,journal,semantic_review_archive,
                expected_run_sha256=run_hash,expected_reference_sha256=reference_digest(reference),reviewer_spec=spec,partition=partition)
        if checked.get('status') != 'unanchored':
            raise ContractError('semantic review unavailable or invalid; recovery required')
        review_hash=checked['sha256']
    outcome_hash=None
    if outcome_enabled:
        from .evaluation_scoring import unavailable_outcome_review
        outcome_spec=config['outcome_reviewer']
        if original_incomplete or applicability_deferral:
            checked_outcome=unavailable_outcome_review(campaign._goal,archive,journal,reference,semantic_review_archive,outcome_review_archive,
                partition=partition,expected_plan_sha256=campaign._digest,expected_run_sha256=run_hash,
                expected_reference_sha256=reference_digest(reference),expected_journal_sha256=journal_hash,
                expected_review_sha256=review_hash,reviewer_spec=config['semantic_reviewer'],outcome_reviewer_spec=outcome_spec,record=True)['outcome_review']
        else:
            from .evaluation_outcome_review import (review_direct_outcome,review_fresh_outcome,
                                                     verify_direct_outcome_review,verify_fresh_outcome_review)
            from .outcome_preflight import outcome_review_reservation
            def outcome_factory(req):
                return outcome_review_reservation(campaign._goal,set_id,request_id=request_id,partition=partition,request=req,spec=outcome_spec)
            outcome_opts=dict(review_archive=outcome_review_archive,expected_run_sha256=run_hash,provider=outcome_spec['provider'],
                model=outcome_spec['model']['id'],max_tokens=outcome_spec['output_tokens'],max_price=outcome_spec['max_price'],
                route=outcome_spec.get('route'),reservation_factory=outcome_factory)
            if arm in ('combined','decomposition_only'):
                review_fresh_outcome(archive,journal,ledger,transport,reference=reference,expected_reference_sha256=reference_digest(reference),
                    expected_journal_sha256=journal_hash,**outcome_opts)
                checked_outcome=verify_fresh_outcome_review(archive,journal,outcome_review_archive,reference=reference,
                    expected_reference_sha256=reference_digest(reference),expected_run_sha256=run_hash,expected_journal_sha256=journal_hash)
            else:
                review_direct_outcome(archive,journal,ledger,transport,**outcome_opts)
                checked_outcome=verify_direct_outcome_review(archive,journal,outcome_review_archive,expected_run_sha256=run_hash)
        if checked_outcome.get('status')!='unanchored':
            raise ContractError('outcome review unavailable or invalid; recovery required')
        outcome_hash=checked_outcome['sha256']
    receipt=campaign.finish(request_id,archive,journal,reference,expected_run_sha256=run_hash,
        expected_reference_sha256=reference_digest(reference),expected_journal_sha256=journal_hash,
        **({'semantic_review_archive':semantic_review_archive,'expected_review_sha256':review_hash} if semantic else {}),
        **({'outcome_review_archive':outcome_review_archive,'expected_outcome_review_sha256':outcome_hash} if outcome_enabled else {}))
    return {**receipt,'run_sha256':run_hash,'journal_sha256':journal_hash,**({'semantic_review_sha256':review_hash} if semantic else {}),
            **({'outcome_review_sha256':outcome_hash} if outcome_enabled else {})}


def run_campaign_batch(campaign: EvaluationCampaign, root, design: dict, cases: dict, *, journal,
                       archive_root, config: dict, want: int, max_bytes: int, expected_config_sha256: str,
                       transport_factory, max_assignments: int) -> dict:
    """Run a bounded ordered batch after checking every case and prior receipt.

    A batch is not a completed experiment unless the persisted denominator is
    fully scored. Bounds, anchors, metadata and the transport factory are caller
    assertions; hosted transport retains its separate refusal gate.
    """
    import re
    from pathlib import Path
    from .applicability import ApplicabilityInputs
    from .evaluation import _full_source_entries,_full_source_packet
    from .evaluation_cases import prepare_evaluation_case
    from .evaluation_scoring import reference_digest
    from .journal import Journal
    from .run_archive import RunArchive
    from .sources import SourceRevision,decode_source
    if (not isinstance(campaign,EvaluationCampaign) or not isinstance(journal,Journal) or not isinstance(cases,dict)
            or not callable(transport_factory) or type(max_assignments) is not int or not 1 <= max_assignments <= 100):
        raise ContractError('invalid campaign batch inputs')
    frozen=campaign.require_config(config,want=want,max_bytes=max_bytes,expected_config_sha256=expected_config_sha256)
    outcome_enabled=frozen['schema']=='qjig.campaign-config.v7'
    semantic = frozen['schema'] in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7')
    manifest,assignments,started,scored=campaign._snapshot()
    if design != manifest['design'] or set(cases) != {case['id'] for case in design['cases']}:
        raise ContractError('campaign batch case set differs')
    if started-scored:
        raise ContractError('campaign recovery required before batch')
    prepared_by_case={}
    for ident,data in cases.items():
        if not isinstance(data,dict) or set(data) != {'lock','reference','protected','applicability_inputs'}:
            raise ContractError('invalid campaign case inputs')
        inputs=data['applicability_inputs']
        if not isinstance(inputs,ApplicabilityInputs) or applicability_digest(inputs) != frozen['case_applicability'][ident]:
            raise ContractError('campaign case applicability binding differs')
        prepared=prepare_evaluation_case(root,design,data['lock'],data['reference'],data['protected'],
            expected_design_sha256=manifest['design_sha256'],expected_case_sha256=manifest['case_hashes'][ident])
        revisions=[SourceRevision.create(source.path,'evaluation_allowlist',decode_source(source.raw,encoding='utf-8'))
                   for source in prepared.sources]
        if (inputs.as_of != prepared.as_of or inputs.request_entities != frozenset(prepared.entities)
                or inputs.historical_as_known != prepared.historical_as_known
                or {r.revision_id for r in revisions} != {m.revision_id for m in inputs.collection.members}):
            raise ContractError('campaign case applicability context differs')
        _full_source_packet(_full_source_entries(revisions),max_bytes)
        prepared_by_case[ident]=data
    archive_base=Path(archive_root)
    if archive_base.is_symlink():
        raise ContractError('campaign archive root must not be a symlink')
    # Reconstruct each prior score from its pinned archive and journal before resuming.
    for rid in sorted(scored):
        if not re.fullmatch(r'qj-[0-9a-f]{64}',rid):
            raise ContractError('campaign request identity is not path safe')
        path=archive_base/rid
        if path.is_symlink() or not path.is_dir() or not (path/'run.sqlite').is_file() or (path/'run.sqlite').is_symlink():
            raise ContractError('scored campaign archive unavailable')
        row=campaign._goal._con.execute("SELECT payload FROM evaluation_campaign_events WHERE plan_id=? AND request_id=? AND kind='scored'",
                                       (campaign._plan_id,rid)).fetchone()
        if row is None:
            raise ContractError('scored campaign receipt unavailable')
        receipt=json.loads(row[0]);assignment=assignments[rid];data=prepared_by_case[assignment['case_id']]
        if reference_digest(data['reference']) != receipt['reference_sha256']:
            raise ContractError('campaign reference differs from receipt')
        with RunArchive.open(path) as archive:
            check_archive_config(frozen,archive.context(),assignment)
            options=dict(partition=assignment['work'][0]['partition'],expected_plan_sha256=campaign._digest,
                         expected_run_sha256=receipt['run_sha256'],expected_reference_sha256=receipt['reference_sha256'],
                         expected_journal_sha256=receipt['journal_sha256'])
            if semantic:
                from .evaluation_scoring import score_reviewed_reserved_assignment
                review_path=path/'semantic-review'
                if (review_path.is_symlink() or not review_path.is_dir() or (review_path/'run.sqlite').is_symlink()
                        or not (review_path/'run.sqlite').is_file()):
                    raise ContractError('scored semantic review archive unavailable')
                with RunArchive.open(review_path) as review_archive:
                    if outcome_enabled:
                        from .evaluation_scoring import score_outcome_reviewed_assignment
                        outcome_path=path/'outcome-review'
                        if (outcome_path.is_symlink() or not outcome_path.is_dir() or (outcome_path/'run.sqlite').is_symlink()
                                or not (outcome_path/'run.sqlite').is_file()):
                            raise ContractError('scored outcome review archive unavailable')
                        with RunArchive.open(outcome_path) as outcome_archive:
                            score=score_outcome_reviewed_assignment(campaign._goal,archive,journal,data['reference'],review_archive,outcome_archive,
                                expected_review_sha256=receipt['semantic_review_sha256'],reviewer_spec=frozen['stages']['semantic_reviewer'],
                                expected_outcome_review_sha256=receipt['outcome_review_sha256'],outcome_reviewer_spec=frozen['stages']['outcome_reviewer'],**options)
                    else:
                        score=score_reviewed_reserved_assignment(campaign._goal,archive,journal,data['reference'],review_archive,
                            expected_review_sha256=receipt['semantic_review_sha256'],reviewer_spec=frozen['stages']['semantic_reviewer'],**options)
            else:
                score=score_reserved_assignment(campaign._goal,archive,journal,data['reference'],**options)
        encoded=json.dumps(score,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
        if hashlib.sha256(encoded).hexdigest()!=receipt['score_sha256']:
            raise ContractError('campaign scored receipt differs')
    if campaign._goal.audit_journal(journal)['status'] != 'verified':
        raise ContractError('campaign goal and journal accounting differ')
    families={family['id']:family['partition'] for family in design['families']}
    partitions={case['id']:families[case['family']] for case in design['cases']}
    order={'development':0,'pilot':1,'holdout':2}
    pending=sorted((a for rid,a in assignments.items() if rid not in started),
                   key=lambda a:(order[partitions[a['case_id']]],a['case_id'],a['arm'],a['repeat']))
    for assignment in pending:
        if not re.fullmatch(r'qj-[0-9a-f]{64}',assignment['request_id']):
            raise ContractError('campaign request identity is not path safe')
    archive_base.mkdir(mode=0o700,parents=True,exist_ok=True)
    executed=0
    for assignment in pending[:max_assignments]:
        rid=assignment['request_id'];data=prepared_by_case[assignment['case_id']]
        from contextlib import ExitStack
        with ExitStack() as stack:
            path=archive_base/rid
            if path.is_symlink() or (path/'run.sqlite').is_symlink():
                raise ContractError('campaign archive path must not be a symlink')
            archive=stack.enter_context(RunArchive.open(path))
            review_archive=None
            if semantic:
                review_path=path/'semantic-review'
                if review_path.is_symlink() or (review_path/'run.sqlite').is_symlink():
                    raise ContractError('semantic review path must not be a symlink')
                review_archive=stack.enter_context(RunArchive.open(review_path))
            outcome_archive=None
            if outcome_enabled:
                outcome_path=path/'outcome-review'
                if outcome_path.is_symlink() or (outcome_path/'run.sqlite').is_symlink():
                    raise ContractError('outcome review path must not be a symlink')
                outcome_archive=stack.enter_context(RunArchive.open(outcome_path))
            run_campaign_assignment(campaign,rid,root,design,data['lock'],data['reference'],data['protected'],
                applicability_inputs=data['applicability_inputs'],transport=transport_factory(dict(assignment)),
                archive=archive,journal=journal,config=config,want=want,max_bytes=max_bytes,
                expected_config_sha256=expected_config_sha256,semantic_review_archive=review_archive,outcome_review_archive=outcome_archive)
        executed+=1
    status=campaign.status()
    return {'executed':executed,'assigned':status['assigned'],'scored':status['scored'],
            'remaining':status['assigned']-status['scored'],'in_progress':status['in_progress']}
