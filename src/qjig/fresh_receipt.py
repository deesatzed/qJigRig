"""Portable per-request archive and journal receipt, without provider authentication."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from decimal import Decimal

from .budgets import BudgetLedger, _valid_cost, _valid_tokens
from .contracts import ContractError, Request
from .journal import Journal, _SCHEMA
from .money import sum_costs
from .providers import ProviderRequest, _ceiling_token_cost
from .replay import verify_archive
from .run_archive import RunArchive


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def make_fresh_receipt(archive_bytes: bytes, events: list, request_id: str) -> dict:
    if not isinstance(archive_bytes, bytes) or not isinstance(events, list) or not isinstance(request_id, str):
        raise ContractError('archive, journal and request required')
    payload = {'schema':'qjig.fresh-receipt.v1', 'request_id':request_id,
               'archive_base64':base64.b64encode(archive_bytes).decode('ascii'),
               'journal':[asdict(event) for event in events]}
    receipt = {'payload':payload, 'sha256':hashlib.sha256(_canonical(payload)).hexdigest()}
    if verify_fresh_receipt(receipt)['status'] == 'invalid':
        raise ContractError('fresh receipt failed structural checks')
    return receipt


def verify_fresh_receipt(receipt: object, *, expected_digest: str | None = None) -> dict:
    """Check retained structure, not source/provider authenticity or goal-wide spend."""
    invalid = {'status':'invalid', 'resources':None, 'semantic_assurance':'not_assessed'}
    try:
        if not isinstance(receipt, dict) or set(receipt) != {'payload','sha256'}:
            raise ContractError('invalid receipt envelope')
        payload = receipt['payload']
        if not isinstance(payload, dict) or set(payload) != {'schema','request_id','archive_base64','journal'} or payload['schema'] != 'qjig.fresh-receipt.v1':
            raise ContractError('invalid receipt payload')
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        if receipt['sha256'] != digest or (expected_digest is not None and expected_digest != digest):
            raise ContractError('receipt digest mismatch')
        rid = payload['request_id']
        if not isinstance(rid,str) or not rid.strip() or not isinstance(payload['archive_base64'],str) or len(payload['archive_base64']) > 45_000_000:
            raise ContractError('invalid receipt data')
        raw = base64.b64decode(payload['archive_base64'], validate=True)
        if len(raw) > 32_000_000:
            raise ContractError('archive too large')
        with closing(sqlite3.connect(':memory:')) as con:
            con.deserialize(raw)
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            archive = RunArchive(con)
            report = verify_archive(archive)
            if report.status == 'invalid' or Request.from_dict(archive.context()['request']).request_id != rid:
                raise ContractError('invalid archived run')
            archived = archive.events()
        events = payload['journal']
        if not isinstance(events,list) or len(events)>10000:
            raise ContractError('invalid journal')
        fields = {'request_id','request_seq','call_id','kind','stage','provider','model','input_sha256','payload','recorded_at'}
        with closing(sqlite3.connect(':memory:')) as con:
            con.executescript(_SCHEMA)
            for index, event in enumerate(events,1):
                if (not isinstance(event,dict) or set(event)!=fields or event['request_id']!=rid
                    or type(event['request_seq']) is not int or event['request_seq']!=index
                    or any(not isinstance(event[k],str) or not event[k].strip() for k in ('call_id','stage','provider','model'))
                    or not isinstance(event['input_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',event['input_sha256'])
                    or not isinstance(event['payload'],dict) or type(event['recorded_at']) not in (int,float)
                    or not math.isfinite(event['recorded_at'])):
                    raise ContractError('invalid journal event')
                con.execute('INSERT INTO events(request_id,request_seq,call_id,kind,stage,provider,model,input_sha256,payload,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (rid,index,event['call_id'],event['kind'],event['stage'],event['provider'],event['model'],event['input_sha256'],
                     _canonical(event['payload']).decode('utf-8'),event['recorded_at']))
            journal = Journal(con,lambda:0)
            journal_events = journal.events(rid)
            intents = {event.call_id:event for event in journal_events if event.kind=='intent'}
            if len(intents) != sum(event.kind=='intent' for event in journal_events):
                raise ContractError('duplicate journal intent')
            terminals = {}
            for event in journal_events:
                if event.kind == 'intent':
                    if event.call_id != f'{rid}#{event.request_seq}':
                        raise ContractError('invalid intent identity')
                    continue
                intent = intents.get(event.call_id)
                if intent is None or intent.request_seq >= event.request_seq or (event.stage,event.provider,event.model,event.input_sha256) != (intent.stage,intent.provider,intent.model,intent.input_sha256):
                    raise ContractError('invalid terminal binding')
                terminals.setdefault(event.call_id, []).append(event)
            if any([event.kind for event in items] not in (['receipt'],['failure'],['uncertain'],['uncertain','reconciled'],['reconciled']) for items in terminals.values()):
                raise ContractError('invalid terminal sequence')
            incomplete = report.status == 'incomplete' or not intents
            for event in archived:
                if event['kind'] != 'request':
                    continue
                intent = intents.get(event['call_id'])
                if intent is None:
                    incomplete = True
                    continue
                data = event['data']
                if (intent.stage,intent.provider,intent.model,intent.input_sha256) != (data['stage'],data['provider'],data['model'],data['input_sha256']):
                    raise ContractError('journal request differs from archive')
                reservation = intent.payload
                inp, out, total = (reservation.get(key) for key in ('reserve_input_tokens','reserve_output_tokens','reserve_tokens'))
                cost = reservation.get('reserve_cost_usd')
                if (any(type(value) is not int or value < 0 for value in (inp,out,total)) or inp + out != total
                    or out != data['max_tokens'] or reservation.get('request_max_price') != data.get('max_price')
                    or type(cost) not in (int,float) or not math.isfinite(cost) or cost < 0):
                    raise ContractError('invalid or mismatched reservation')
                if data.get('max_price') is None:
                    incomplete = True
                else:
                    request = ProviderRequest(data['stage'], data['provider'], data['model'], data['prompt'],
                                              data['max_tokens'], max_price=data['max_price'], route=data.get('route'))
                    if Decimal(str(cost)) < _ceiling_token_cost(request, inp):
                        raise ContractError('reservation below declared routing ceiling')
            archived_calls = {event['call_id'] for event in archived if event['kind']=='request'}
            if set(intents) != archived_calls or journal.pending(rid):
                incomplete = True
            responses = {event['call_id']:event['data'] for event in archived if event['kind']=='response'}
            receipts = {call:items[0] for call,items in terminals.items() if items[0].kind=='receipt'}
            if set(responses) != set(receipts):
                incomplete = True
            for call in set(responses) & set(receipts):
                response, terminal = responses[call], receipts[call]
                if (terminal.payload.get('usage') != (response.get('usage') or {})
                        or terminal.payload.get('raw_sha256') != response.get('body_sha256')
                        or terminal.payload.get('http_status') != response.get('http_status')):
                    raise ContractError('journal receipt differs from archived response')
                usage = terminal.payload.get('usage', {})
                inp, out, cost = (usage.get(key) for key in ('prompt_tokens','completion_tokens','cost_usd'))
                if not _valid_tokens(inp) or not _valid_tokens(out) or not _valid_cost(cost):
                    incomplete = True
                else:
                    reserved = intents[call].payload
                    if (inp > reserved['reserve_input_tokens'] or out > reserved['reserve_output_tokens']
                            or cost > reserved['reserve_cost_usd']):
                        raise ContractError('reported usage exceeds reservation')
            ledger = BudgetLedger(None,journal,rid)
            if intents and set(intents)==archived_calls:
                attempts = ledger._calls()
                usages = [next((event.payload.get('usage', {}) for event in rest if event.kind == 'receipt'), {})
                          for _, rest in attempts]
                inputs = [value.get('prompt_tokens') for value in usages]
                outputs = [value.get('completion_tokens') for value in usages]
                reserved_cost = float(sum_costs(intent.payload['reserve_cost_usd'] for intent, _ in attempts))
                if not math.isfinite(reserved_cost):
                    raise ContractError('reserved cost exceeds supported precision')
                resources = {'calls':len(attempts), 'reserved_tokens':sum(intent.payload['reserve_tokens'] for intent, _ in attempts),
                             'reserved_cost_usd':reserved_cost,
                             'committed_tokens':ledger.committed_tokens(),
                             'actual_input_tokens':sum(inputs) if all(_valid_tokens(value) for value in inputs) else None,
                             'actual_output_tokens':sum(outputs) if all(_valid_tokens(value) for value in outputs) else None,
                             'cost_status':ledger.cost_status(), 'known_cost_usd':ledger.known_cost_usd()}
            else:
                resources = {'calls':None, 'reserved_tokens':None, 'reserved_cost_usd':None, 'committed_tokens':None,
                             'actual_input_tokens':None, 'actual_output_tokens':None,
                             'cost_status':'unknown','known_cost_usd':None}
            if resources['cost_status'] != 'known':
                incomplete = True
        return {'status':'incomplete' if incomplete else 'unanchored' if expected_digest is None else 'structurally_verified',
                'digest':digest,'resources':resources,'semantic_assurance':'not_assessed',
                'provider_authenticity':'not_established','goal_budget_assurance':'not_assessed'}
    except (ContractError, KeyError, TypeError, ValueError, AttributeError, OverflowError, sqlite3.Error, binascii.Error):
        return invalid
