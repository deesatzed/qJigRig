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
            archive = RunArchive(connection)
            report = verify_archive(archive)
            if report.status == 'invalid':
                raise ContractError('fresh run failed structural replay')
            context, events = archive.context(), archive.events()
            request = Request.from_dict(context['request'])
            if hashlib.sha256(request.request_id.encode('utf-8')).hexdigest() != run_id:
                raise ContractError('fresh run identity mismatch')
            results = [event['data'] for event in events if event['kind'] == 'run_result']
            traces = [event['data'] for event in events if event['kind'] == 'trace']
            return {'run_id': run_id, 'request': request.to_dict(),
                    'result': results[0] if len(results) == 1 else None,
                    'traces': traces, 'verification': asdict(report),
                    'source_freshness': 'not_assessed'}

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
                    for trace in run.state.trace:
                        records.append({'predicate_id': trace.predicate_id, 'outcome': trace.observation.outcome.value,
                                        'reason': trace.observation.reason,
                                        'evidence': [{'revision_id': item.revision_id, 'start': item.start, 'end': item.end,
                                                      'text': item.text, 'truncated': item.truncated} for item in trace.evidence],
                                        'exclusions': [{'reason': item.reason} for item in trace.exclusions]})
                conditional = evaluate(run.state.plan.expression, run.state.observations).outcome.value if run.state else None
                review = {'status': run.review.status, 'failure': run.review.failure,
                          'assurance': 'synthetic_unvalidated' if isinstance(transport, StandInTransport) else 'ai_unvalidated'} if run.review else {'status': 'unavailable', 'failure': run.plan_failure, 'assurance': 'not_assessed'}
                return {'kind': 'fresh', 'status': 'deferred', 'answer': None, 'conditional_outcome': conditional,
                        'reasons': list(run.reasons) + (['catalog_changed_during_run'] if before != after else []),
                        'plan_failure': run.plan_failure, 'records': records, 'review': review,
                        'run_id': run_id, 'source_state_before': before, 'source_state_after': after,
                        'provider_assurance': 'synthetic' if isinstance(transport, StandInTransport) else 'hosted_unverified'}
