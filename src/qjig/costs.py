"""Summarize recorded physical attempts; this does not verify provider usage."""
from __future__ import annotations

import math
from decimal import Decimal

from .budgets import _valid_cost, _valid_tokens
from .contracts import ContractError


def summarize_resources(journal) -> dict:
    """Aggregate one complete, quiescent journal, retaining unknown fields.

    Latency is observed intent-to-terminal elapsed time, not provider inference
    time. An unfinished call makes the aggregate latency unknown. No inference,
    validation of provider-reported amounts, or cross-store reconciliation occurs.
    """
    attempts = {}
    for event in journal.all_events():
        key = (event.request_id, event.call_id)
        if event.kind == 'intent':
            if key in attempts:
                raise ContractError('duplicate journal intent')
            attempts[key] = [event, []]
        else:
            if key not in attempts:
                raise ContractError('journal terminal without prior intent')
            intent, terminals = attempts[key]
            if (event.stage, event.provider, event.model, event.input_sha256) != (intent.stage, intent.provider, intent.model, intent.input_sha256):
                raise ContractError('journal terminal identity mismatch')
            terminals.append(event)
    grouped = {}
    all_records = []
    for intent, terminals in attempts.values():
        if len(terminals) > 1 and [e.kind for e in terminals] != ['uncertain', 'reconciled']:
            raise ContractError('duplicate journal terminal')
        terminal = terminals[0] if terminals else None
        if terminal and terminal.kind == 'reconciled':
            raise ContractError('reconciliation without uncertain outcome')
        usage = terminal.payload.get('usage') if terminal and terminal.kind == 'receipt' and isinstance(terminal.payload, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        a, b, c = usage.get('prompt_tokens'), usage.get('completion_tokens'), usage.get('cost_usd')
        a, b, c = a if _valid_tokens(a) else None, b if _valid_tokens(b) else None, c if _valid_cost(c) else None
        duration = None
        if terminal:
            start, end = intent.recorded_at, terminal.recorded_at
            if type(start) not in (int, float) or type(end) not in (int, float) or not math.isfinite(start) or not math.isfinite(end) or end < start:
                raise ContractError('invalid journal timestamps')
            duration = end - start
        record = (a, b, c, duration)
        all_records.append(record)
        grouped.setdefault(intent.stage, []).append(record)

    def aggregate(records):
        known_input = sum(r[0] for r in records if r[0] is not None)
        known_output = sum(r[1] for r in records if r[1] is not None)
        known_cost = sum((Decimal(str(r[2])) for r in records if r[2] is not None), Decimal(0))
        return {'calls': len(records),
                'input_tokens': known_input if all(r[0] is not None for r in records) else None,
                'output_tokens': known_output if all(r[1] is not None for r in records) else None,
                'cost_usd': float(known_cost) if all(r[2] is not None for r in records) else None,
                'known_input_tokens': known_input, 'known_output_tokens': known_output,
                'known_cost_usd': float(known_cost),
                'unknown_usage_calls': sum(any(x is None for x in r[:3]) for r in records),
                'latency_seconds': sum(r[3] for r in records) if all(r[3] is not None for r in records) else None}
    return {'total': aggregate(all_records), 'stages': {name: aggregate(grouped[name]) for name in sorted(grouped)}}
