"""Isolated worker for bounded rechecking of authored evaluator observations.

The parent invokes this module in a subprocess with a wall-clock timeout. Input
is untrusted JSON; no model-generated code is executed. Output is deliberately
small and contains no source text.
"""
from __future__ import annotations

import json
import sys

from .applicability import Applicability, date_applicability, entity_applicability, scope_applicability
from .cli import _evaluator, _member_from_row
from .packets import EvidencePacket, PacketItem
from .spans import Span


def check(payload: dict) -> dict:
    policy, result, sources = payload['policy'], payload['result'], payload['sources']
    members = {ident: _member_from_row(tuple(source['metadata'])) for ident, source in sources.items()}
    entities = frozenset(policy.get('entities', ()))
    historical = bool(policy.get('historical_as_known', False))
    checked = 0
    for record in result['records']:
        if record['observation']['outcome'] not in ('true', 'false'):
            continue
        need = policy['needs'][record['predicate_id']]
        evaluator = need.get('evaluator')
        round_number = record['round']
        if type(round_number) is not int or round_number not in (1, 2):
            raise ValueError('invalid round')
        if round_number == 2:
            need = need['followup']
            evaluator = need.get('evaluator') or evaluator
        items = []
        for e in record['evidence']:
            member = members[e['revision_id']]
            if (scope_applicability(result['request']['scope'], member.scope) is not Applicability.MATCH
                    or entity_applicability(member, entities).value is not Applicability.MATCH
                    or date_applicability(member, policy['as_of'], historical_as_known=historical).overall is not Applicability.MATCH
                    or e['truncated']):
                raise ValueError('inapplicable evidence')
            span = Span(e['revision_id'], e['text_sha256'], e['start'], e['end'], e['text'])
            items.append(PacketItem(e['entry_id'], span))
        if not items:
            raise ValueError('conclusive observation lacks evidence')
        packet = EvidencePacket(tuple(items), (), (), 0, 0)
        observed = _evaluator(evaluator, members, policy.get('facts', {}), entities, policy['as_of'], historical)(packet, None)
        if {'outcome': observed.outcome.value, 'reason': observed.reason} != record['observation']:
            raise ValueError('evaluator mismatch')
        checked += 1
    return {'status': 'ok', 'checked': checked}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(check(payload), separators=(',', ':')))
    except Exception:
        print('{"status":"invalid"}')


if __name__ == '__main__':
    main()
