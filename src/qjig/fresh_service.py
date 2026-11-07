"""Configured local workbench adapter for the actual fresh-planning pipeline.

The caller must configure a persistent goal ledger and stage bounds. Bounds are
assertions, not hosted-call authorization; OpenRouter's separate gate remains in
force. Raw run archives and journals must stay in a private ignored directory.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from contextlib import closing
from pathlib import Path

from .acquisition import run_fresh
from .applicability import ApplicabilityInputs, Collection
from .budgets import BudgetExceeded, BudgetLedger
from .cli import _member_from_row
from .contracts import Budget, ContractError, Request
from .fresh_preflight import fresh_run_allocations, fresh_slot_reservation
from .goal_budget import GoalBudget
from .indexing import load_live_entries
from .journal import Journal
from .logic import evaluate
from .providers import OpenRouterTransport, StandInTransport
from .run_archive import RunArchive
from .store import Catalog


def _judgment_view(judgment):
    def side_view(side):
        return {'support': side.support.value, 'reason': side.reason, 'failure': side.failure,
                'call_id': side.call_id, 'quote': side.quote if side.quote_ref is not None else None,
                'quote_ref': asdict(side.quote_ref) if side.quote_ref is not None else None}
    return {'positive': side_view(judgment.positive), 'negative': side_view(judgment.negative),
            'caveats': list(judgment.caveats)}


class FreshWorkbench:
    """Trusted local configuration, never created from browser-supplied paths or credentials."""

    def __init__(self, state_dir: Path, *, goal_factory, transport_factory, partition: str,
                 planner: dict, judge: dict, reviewer: dict, budget: Budget):
        if (not callable(goal_factory) or not callable(transport_factory) or not isinstance(budget, Budget)
                or not isinstance(partition, str) or not partition.strip()):
            raise ContractError('fresh workbench configuration required')
        try:
            specs = json.loads(json.dumps([planner, judge, reviewer], allow_nan=False))
        except (TypeError, ValueError):
            raise ContractError('fresh stage configuration must be finite JSON') from None
        keys = {'provider', 'model', 'input_tokens', 'output_tokens', 'max_price'}
        if any(not isinstance(spec, dict) or set(spec) != keys for spec in specs) or specs[0]['provider'] != specs[1]['provider']:
            raise ContractError('invalid fresh stage configuration')
        self.state_dir = Path(state_dir)
        if self.state_dir.is_symlink():
            raise ContractError('fresh state directory must not be a symlink')
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.goal_factory, self.transport_factory = goal_factory, transport_factory
        self.partition, self.planner, self.judge, self.reviewer, self.budget = partition, *specs, budget

    def replay(self, run_id: str) -> dict:
        """Inspect an existing archive without creating files or calling a model."""
        from .replay import verify_archive
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ContractError('invalid fresh run identity')
        runs = self.state_dir / 'runs'
        directory = runs / run_id
        database = directory / 'run.sqlite'
        if runs.is_symlink() or directory.is_symlink() or database.is_symlink() or not database.is_file():
            raise FileNotFoundError('fresh run unavailable')
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('BEGIN')
            archive = RunArchive(connection)
            judgments, plan = {}, {}
            report = verify_archive(archive, judgments_out=judgments, plan_out=plan)
            if report.status == 'invalid':
                raise ContractError('fresh run failed structural replay')
            context, events = archive.context(), archive.events()
            request = Request.from_dict(context['request'])
            if hashlib.sha256(request.request_id.encode('utf-8')).hexdigest() != run_id:
                raise ContractError('fresh run identity mismatch')
            results = [event['data'] for event in events if event['kind'] == 'run_result']
            traces = [{**event['data'], 'judgment': _judgment_view(judgments[event['data']['sequence']])
                       if event['data']['sequence'] in judgments else None}
                      for event in events if event['kind'] == 'trace']
            reviews = [event['data'] for event in events if event['kind'] == 'review_record']
            review = None
            if len(reviews) == 1:
                record = reviews[0]
                payload = record['payload']
                review = {'review_id': record['sha256'], 'assurance': payload['assurance'],
                          'assessment': payload['result'].get('assessment'), 'reason': payload['result'].get('reason')}
            reconciliation, resources = self._journal_status(request.request_id, events)
            return {'run_id': run_id, 'request': request.to_dict(),
                    'plan': plan or None,
                    'result': results[0] if len(results) == 1 else None,
                    'traces': traces, 'review': review, 'verification': asdict(report),
                    'reconciliation': reconciliation, 'resources': resources,
                    'source_freshness': 'not_assessed'}

    def _journal_status(self, request_id: str, archive_events: list[dict]) -> tuple[dict, dict]:
        """Read journal accounting; absence or disagreement is unknown, not clear."""
        path = self.state_dir / 'journal.sqlite'
        unknown = ({'status': 'unknown', 'unresolved': []}, {'status': 'unknown'})
        if path.is_symlink() or not path.is_file():
            return unknown
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
                connection.execute('BEGIN')
                if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                    return unknown
                journal = Journal(connection, lambda: 0)
                events = journal.events(request_id)
                intents = {event.call_id for event in events if event.kind == 'intent'}
                archived = {event['call_id'] for event in archive_events if event['kind'] == 'request'}
                if not intents or not archived <= intents:
                    return unknown
                pending = journal.pending(request_id)
                ledger = BudgetLedger(None, journal, request_id)
                reconciliation = {'status': 'required' if pending else 'clear',
                                  'unresolved': [{'call_id': event.call_id, 'stage': event.stage} for event in pending]}
                resources = {'status': 'recorded_unverified', 'calls': ledger.used_calls(),
                             'committed_tokens': ledger.committed_tokens(), 'cost_status': ledger.cost_status(),
                             'known_cost_usd': ledger.known_cost_usd()}
                return reconciliation, resources
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            return unknown

    def export(self, run_id: str) -> bytes:
        """Copy and structurally check a consistent SQLite snapshot, without inference."""
        from .replay import verify_archive
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ContractError('invalid fresh run identity')
        runs = self.state_dir / 'runs'
        directory = runs / run_id
        database = directory / 'run.sqlite'
        if runs.is_symlink() or directory.is_symlink() or database.is_symlink() or not database.is_file():
            raise FileNotFoundError('fresh run unavailable')
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(':memory:')) as snapshot:
                source.backup(snapshot)
                archive = RunArchive(snapshot)
                report = verify_archive(archive)
                if report.status == 'invalid':
                    raise ContractError('fresh run failed structural replay')
                request = Request.from_dict(archive.context()['request'])
                if hashlib.sha256(request.request_id.encode('utf-8')).hexdigest() != run_id:
                    raise ContractError('fresh run identity mismatch')
                return snapshot.serialize()

    def receipt(self, run_id: str) -> dict:
        """Capture one request's archive and journal; the stores are not atomic together."""
        from .fresh_receipt import make_fresh_receipt
        archive_bytes = self.export(run_id)
        replay = self.replay(run_id)
        path = self.state_dir / 'journal.sqlite'
        if path.is_symlink() or not path.is_file():
            raise ContractError('journal unavailable')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
            con.execute('BEGIN')
            if con.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ContractError('journal unavailable')
            events = Journal(con, lambda: 0).events(replay['request']['request_id'])
        return make_fresh_receipt(archive_bytes, events, replay['request']['request_id'])

    def check_cases(self, run_id: str, cases: object) -> dict:
        """Evaluate explicit hypothetical assignments against a saved graph, without inference."""
        from .assurance import Counterexample, check_counterexamples
        from .logic import Observation, Outcome
        from .plans import parse_plan
        if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
            raise ContractError('one to twenty hypothetical cases required')
        saved = self.replay(run_id)
        view = saved['plan']
        if view is None:
            raise ContractError('structurally replayable plan required')
        plan = parse_plan({'origin': view['origin'], 'expression': view['expression'],
                           'predicates': [{'id': predicate['id'], 'question': predicate['question'],
                                           'depends_on': list(predicate['depends_on']),
                                           **({'exact_operator': predicate['exact_operator']}
                                              if predicate['exact_operator'] is not None else {})}
                                          for predicate in view['predicates']]})
        parsed = []
        for case in cases:
            if (not isinstance(case, dict) or set(case) != {'case_id', 'assignments', 'expected'}
                    or not isinstance(case['case_id'], str) or not case['case_id'].strip() or len(case['case_id']) > 128
                    or not isinstance(case['assignments'], dict) or not isinstance(case['expected'], str)):
                raise ContractError('invalid hypothetical case')
            try:
                assignments = {key: Observation(Outcome(value), 'authored_hypothetical')
                               for key, value in case['assignments'].items()}
                expected = Outcome(case['expected'])
            except (TypeError, ValueError):
                raise ContractError('invalid hypothetical outcome') from None
            parsed.append(Counterexample(case['case_id'], assignments, expected, 'authored_hypothetical'))
        results = check_counterexamples(plan, parsed)
        return {'run_id': run_id, 'archive_digest': saved['verification']['digest'],
                'attribution': 'authored_hypothetical', 'independent': False,
                'results': [{'case_id': item.case_id, 'expected': item.expected.value, 'actual': item.actual.value,
                             'classification': item.classification} for item in results]}

    def list_runs(self) -> list[dict]:
        runs = self.state_dir / 'runs'
        if runs.is_symlink():
            raise ContractError('unsafe fresh runs directory')
        if not runs.exists():
            return []
        results = []
        for directory in sorted(runs.iterdir()):
            if not re.fullmatch(r'[0-9a-f]{64}', directory.name):
                continue
            try:
                run = self.replay(directory.name)
                results.append({'run_id': directory.name, 'question': run['request']['question'],
                                'replay_status': run['verification']['status']})
            except (ContractError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, OSError):
                results.append({'run_id': directory.name, 'question': None, 'replay_status': 'unavailable_or_invalid'})
        return results

    def run(self, catalog_path: Path, body: object) -> dict:
        if not isinstance(body, dict) or set(body) != {'request', 'as_of', 'entities'} or not isinstance(body['request'], dict):
            raise ContractError('fresh request, date and entities required')
        request = Request.from_dict(body['request'])
        if request.budget is not None or any(not getattr(request, key).strip() for key in request._FIELDS):
            raise ContractError('fresh request must use configured budget and nonempty fields')
        entities = body['entities']
        if not isinstance(entities, list) or any(not isinstance(item, str) or not item.strip() for item in entities):
            raise ContractError('invalid request entities')
        run_id = hashlib.sha256(request.request_id.encode('utf-8')).hexdigest()
        runs = self.state_dir / 'runs'
        if runs.is_symlink() or (runs / run_id).exists() or (runs / run_id).is_symlink():
            raise ContractError('fresh run identity already used or unsafe')
        runs.mkdir(mode=0o700, exist_ok=True)
        planner, judge, reviewer = self.planner, self.judge, self.reviewer
        slots = fresh_run_allocations(request_id=request.request_id, partition=self.partition, provider=planner['provider'],
            planner_model=planner['model'], judge_model=judge['model'], planner_input=planner['input_tokens'],
            planner_output=planner['output_tokens'], judge_input=judge['input_tokens'], judge_output=judge['output_tokens'],
            planner_price=planner['max_price'], judge_price=judge['max_price'], reviewer=reviewer)
        transport = self.transport_factory()
        if not isinstance(transport, (StandInTransport, OpenRouterTransport)):
            raise ContractError('unsupported fresh transport')
        if isinstance(transport, OpenRouterTransport):
            raise BudgetExceeded('preflight_unavailable', 'configured assertions do not establish hosted-call bounds')
        if (self.state_dir / 'journal.sqlite').is_symlink():
            raise ContractError('unsafe journal path')
        goal = self.goal_factory()
        if not isinstance(goal, GoalBudget):
            raise ContractError('persistent goal budget required')
        set_id = 'workbench:' + run_id
        with goal, Journal.open(self.state_dir / 'journal.sqlite') as journal, Catalog.open(catalog_path) as catalog:
            if journal.events(request.request_id):
                raise ContractError('fresh request identity already used')
            before = catalog.source_state()
            entries = load_live_entries(catalog)
            members = tuple(_member_from_row(row) for row in catalog.metadata_rows())
            inputs = ApplicabilityInputs(Collection(members), frozenset(entities), body['as_of'], False)
            goal.reserve_run_set(set_id, slots)
            with RunArchive.open(runs / run_id) as archive:
                def reserve(provider_request):
                    spec = planner if provider_request.stage == 'planner' else reviewer if provider_request.stage == 'plan_review' else judge
                    return fresh_slot_reservation(goal, set_id, request_id=request.request_id, partition=self.partition,
                        request=provider_request, model=spec['model'], input_tokens=spec['input_tokens'],
                        input_bound_provenance='configured assertion; not provider verified')
                ledger = BudgetLedger(self.budget, journal, request.request_id, goal_budget=goal, partition=self.partition)
                run = run_fresh(request=request, catalog=catalog, entries=entries, ledger=ledger, transport=transport,
                    planner=(planner['provider'], planner['model']['id']), judge=(judge['provider'], judge['model']['id']),
                    reviewer=(reviewer['provider'], reviewer['model']['id']), planner_max_tokens=planner['output_tokens'],
                    judge_max_tokens=judge['output_tokens'], reviewer_max_tokens=reviewer['output_tokens'],
                    planner_max_price=planner['max_price'], judge_max_price=judge['max_price'], reviewer_max_price=reviewer['max_price'],
                    reservation_factory=reserve, review_reservation_factory=reserve, require_complete_reservations=True,
                    archive=archive, applicability_inputs=inputs, revision_applicability=inputs.verdict)
                after = catalog.source_state()
                records = []
                if run.state is not None:
                    last_trace = {trace.predicate_id: index for index, trace in enumerate(run.state.trace)}
                    for index, trace in enumerate(run.state.trace):
                        judgment = run.judgments.get(trace.predicate_id) if last_trace[trace.predicate_id] == index else None
                        records.append({'predicate_id': trace.predicate_id, 'outcome': trace.observation.outcome.value,
                                        'reason': trace.observation.reason,
                                        'judgment': _judgment_view(judgment) if judgment else None,
                                        'evidence': [{'revision_id': item.revision_id, 'start': item.start, 'end': item.end,
                                                      'text': item.text, 'truncated': item.truncated} for item in trace.evidence],
                                        'exclusions': [asdict(item) for item in trace.exclusions],
                                        'channels': asdict(trace.channels) if trace.channels is not None else None})
                conditional = evaluate(run.state.plan.expression, run.state.observations).outcome.value if run.state else None
                review_record = run.review.record if run.review else None
                review_payload = review_record['payload'] if review_record is not None else None
                review_result = review_payload['result'] if review_payload is not None else {}
                review = {'status': run.review.status if run.review else 'unavailable',
                          'failure': run.review.failure if run.review else run.plan_failure,
                          'assurance': review_payload['assurance'] if review_payload else 'not_assessed',
                          'assessment': review_result.get('assessment'), 'reason': review_result.get('reason'),
                          'review_id': review_record['sha256'] if review_record else None}
                return {'kind': 'fresh', 'status': 'deferred', 'answer': None, 'conditional_outcome': conditional,
                        'plan': asdict(run.state.plan) if run.state is not None else None,
                        'reasons': list(run.reasons) + (['catalog_changed_during_run'] if before != after else []),
                        'blocking_obligations': list(run.summary.stop.blocking_obligations) if run.summary else None,
                        'plan_failure': run.plan_failure, 'records': records, 'review': review,
                        'run_id': run_id, 'source_state_before': before, 'source_state_after': after,
                        'provider_assurance': 'synthetic' if isinstance(transport, StandInTransport) else 'hosted_unverified'}
