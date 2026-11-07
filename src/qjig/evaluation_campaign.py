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
        if config_row is not None:
            config_value,config_digest = config_row
            if hashlib.sha256(config_value.encode('utf-8')).hexdigest() != config_digest:
                raise ContractError('campaign configuration integrity differs')
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

    def freeze_config(self, config: dict, *, want: int, max_bytes: int, case_applicability: dict) -> str:
        """Persist declared stage settings and shared packet limits before claims."""
        from .direct_preflight import direct_run_allocations
        from .fresh_preflight import fresh_run_allocations
        if (type(want) is not int or not 1 <= want <= 100 or type(max_bytes) is not int or not 1 <= max_bytes <= 1024*1024
                or not isinstance(config,dict) or set(config) != {'direct','planner','judge','reviewer'}
                or any(not isinstance(v,dict) or set(v) != {'provider','model','input_tokens','output_tokens','max_price'}
                       for v in config.values())):
            raise ContractError('invalid campaign configuration')
        direct,planner,judge,reviewer=(config[k] for k in ('direct','planner','judge','reviewer'))
        if planner['provider'] != judge['provider']:
            raise ContractError('fresh planner and judge providers must match')
        payload={'schema':'qjig.campaign-config.v2','plan_sha256':self._digest,'want':want,'max_bytes':max_bytes,
                 'stages':config,'case_applicability':case_applicability}
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
                        planner_price=planner['max_price'],judge_price=judge['max_price'],reviewer=reviewer)
                elif arm in ('direct_full_evidence','direct_retrieval','retrieval_only'):
                    work=direct_run_allocations(request_id=rid,partition=partition,provider=direct['provider'],model=direct['model'],
                        input_tokens=direct['input_tokens'],output_tokens=direct['output_tokens'],max_price=direct['max_price'],
                        followups=0 if arm=='direct_full_evidence' else 1)
                else:
                    raise ContractError('unsupported campaign arm')
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
            expected=json.dumps({'schema':'qjig.campaign-config.v2','plan_sha256':self._digest,'want':want,
                                 'max_bytes':max_bytes,'stages':config,'case_applicability':frozen['case_applicability']},
                                sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
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
            if not isinstance(request_id,str) or request_id not in assignments or request_id in started:
                raise ContractError('assignment unavailable or already claimed')
            if started-scored:
                raise ContractError('campaign recovery required before another assignment')
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
               expected_reference_sha256: str, expected_journal_sha256: str | None = None) -> dict:
        manifest,assignments,started,scored = self._snapshot()
        if request_id not in assignments or request_id not in started or request_id in scored:
            raise ContractError('assignment is not an unfinished claim')
        assignment = assignments[request_id]
        if archive.context().get('request',{}).get('request_id') != request_id:
            raise ContractError('archive request differs from claim')
        config_row=self._goal._con.execute('SELECT value FROM evaluation_campaign_config WHERE plan_id=?',(self._plan_id,)).fetchone()
        if config_row is not None:
            frozen=json.loads(config_row[0]);context=archive.context();stages=frozen['stages'];arm=assignment['arm']
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
                for name in ('planner','judge','reviewer'):
                    actual=context.get(name);spec=stages[name]
                    if (not isinstance(actual,dict) or actual.get('provider') != spec['provider']
                            or actual.get('model') != spec['model']['id'] or actual.get('max_tokens') != spec['output_tokens']
                            or actual.get('max_price') != spec['max_price']):
                        raise ContractError('archive stage configuration differs')
            else:
                spec=stages['direct']
                if (context.get('provider') != spec['provider'] or context.get('model') != spec['model']['id']
                        or context.get('max_tokens') != spec['output_tokens'] or context.get('max_price') != spec['max_price']
                        or context.get('followups') != (0 if arm=='direct_full_evidence' else 1)):
                    raise ContractError('archive direct configuration differs')
        family = next(c['family'] for c in manifest['design']['cases'] if c['id']==assignment['case_id'])
        partition = next(f['partition'] for f in manifest['design']['families'] if f['id']==family)
        score = score_reserved_assignment(self._goal,archive,journal,reference,partition=partition,
            expected_plan_sha256=self._digest,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256)
        if (score['score']['case_id'],score['arm'],score['repeat']) != (assignment['case_id'],assignment['arm'],assignment['repeat']):
            raise ContractError('scored assignment differs from claim')
        if score['score'].get('reconciliation_required') is True:
            raise ContractError('campaign reconciliation required before completion')
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


def run_campaign_assignment(campaign: EvaluationCampaign, request_id: str, root, design: dict,
                            lock: dict, reference: dict, protected: list[dict], *,
                            applicability_inputs, transport, archive, journal, config: dict,
                            want: int, max_bytes: int, expected_config_sha256: str) -> dict:
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
    if arm in ('direct_full_evidence','decomposition_only'):
        from .evaluation import _full_source_entries,_full_source_packet
        _full_source_packet(_full_source_entries(revisions),max_bytes)
        if arm == 'decomposition_only':
            from .applicability import Applicability,combine_applicability,scope_applicability
            if any(combine_applicability(applicability_inputs.verdict(revision.revision_id),
                    scope_applicability(prepared.scope,applicability_inputs.collection.member(revision.revision_id).scope))
                    is not Applicability.MATCH for revision in revisions):
                raise ContractError('campaign full source applicability differs')
    if (not isinstance(config,dict) or set(config) != {'direct','planner','judge','reviewer'}
            or any(not isinstance(spec,dict) or set(spec) != {'provider','model','input_tokens','output_tokens','max_price'}
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
            planner_price=planner['max_price'],judge_price=judge['max_price'],reviewer=reviewer)
    elif arm in ('direct_full_evidence','direct_retrieval','retrieval_only'):
        expected=direct_run_allocations(request_id=request_id,partition=partition,provider=direct['provider'],model=direct['model'],
            input_tokens=direct['input_tokens'],output_tokens=direct['output_tokens'],max_price=direct['max_price'],
            followups=0 if arm=='direct_full_evidence' else 1)
    else:
        raise ContractError('unsupported campaign arm')
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
    if arm in ('combined','decomposition_only'):
        def factory(req):
            spec = planner if req.stage=='planner' else reviewer if req.stage=='plan_review' else judge
            return fresh_slot_reservation(campaign._goal,set_id,request_id=request_id,partition=partition,
                request=req,model=spec['model'],input_tokens=spec['input_tokens'],input_bound_provenance='declared campaign bound')
        run_locked_fresh(root,design,lock,reference,protected,expected_design_sha256=manifest['design_sha256'],
            expected_case_sha256=claim['case_sha256'],applicability_inputs=applicability_inputs,ledger=ledger,transport=transport,
            archive=archive,planner=(planner['provider'],planner['model']['id']),judge=(judge['provider'],judge['model']['id']),
            reviewer=(reviewer['provider'],reviewer['model']['id']),planner_max_tokens=planner['output_tokens'],
            judge_max_tokens=judge['output_tokens'],reviewer_max_tokens=reviewer['output_tokens'],
            planner_max_price=planner['max_price'],judge_max_price=judge['max_price'],reviewer_max_price=reviewer['max_price'],
            reservation_factory=factory,review_reservation_factory=factory,want=want,max_bytes=max_bytes,
            assignment_binding=binding,evidence_mode='full' if arm=='decomposition_only' else 'catalog')
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
            applicability_inputs=applicability_inputs,reservation_factory=factory,max_price=direct['max_price'],assignment_binding=binding)
        replay=verify_direct_archive(archive,journal)
        if replay['status'] not in ('unanchored','incomplete') or replay['sha256'] is None:
            raise ContractError('campaign direct archive is not replayable')
        run_hash,journal_hash=replay['sha256'],None
    receipt=campaign.finish(request_id,archive,journal,reference,expected_run_sha256=run_hash,
        expected_reference_sha256=reference_digest(reference),expected_journal_sha256=journal_hash)
    return {**receipt,'run_sha256':run_hash,'journal_sha256':journal_hash}
