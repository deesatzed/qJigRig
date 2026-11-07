"""Conservative interpretation of caller-supplied OpenRouter account metadata.

This is not a network client, token bound, provider authorization, or proof
that an account snapshot remains current. No credentials or identifiers are
needed or retained.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from .contracts import ContractError


def _money(value, *, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) not in (int,float,Decimal):
        raise ContractError('monetary value must be numeric')
    try:
        result=Decimal(str(value))
    except (InvalidOperation,ValueError) as exc:
        raise ContractError('invalid monetary value') from exc
    if not result.is_finite() or result < 0:
        raise ContractError('monetary value must be finite and nonnegative')
    parts=result.as_tuple()
    if len(parts.digits)>128 or abs(parts.exponent)>128:
        raise ContractError('monetary value exceeds supported precision')
    return result


def account_spend_constraints(key_response: dict, credits_response: dict, *, goal_ceiling_usd) -> dict:
    """Return the lowest observed OpenRouter credit cap and explicit BYOK uncertainty.

    A finite key limit is treated as an additional upper limit. A null limit is
    unbounded by that key, not a claim of unlimited account credit. Even when the
    provider says BYOK counts against the key, enforcement is a source claim.
    """
    goal=_money(goal_ceiling_usd)
    if goal <= 0 or goal > Decimal(25):
        raise ContractError('goal ceiling must be positive and at most 25 USD')
    if (not isinstance(key_response,dict) or not isinstance(key_response.get('data'),dict)
            or not isinstance(credits_response,dict) or not isinstance(credits_response.get('data'),dict)):
        raise ContractError('key and credit snapshots required')
    key,credits=key_response['data'],credits_response['data']
    if (not {'limit_remaining','include_byok_in_limit','is_free_tier'} <= set(key)
            or not {'total_credits','total_usage'} <= set(credits)
            or type(key['include_byok_in_limit']) is not bool or type(key['is_free_tier']) is not bool):
        raise ContractError('account snapshot is incomplete')
    remaining=_money(key['limit_remaining'],allow_none=True)
    credit=_money(credits['total_credits']);used=_money(credits['total_usage'])
    with localcontext() as ctx:
        ctx.prec=512
        ctx.rounding=ROUND_FLOOR
        available=max(Decimal(0),credit-used)
    ceiling=min(goal,available,remaining) if remaining is not None else min(goal,available)
    byok=('provider_claimed_key_limit' if key['include_byok_in_limit'] and remaining is not None else 'unknown')
    return {'openrouter_credit_ceiling_usd':ceiling,'key_limit_remaining_usd':remaining,
            'credit_remaining_usd':available,'is_free_tier':key['is_free_tier'],
            'byok_spend_assurance':byok,'source_assurance':'caller_supplied_snapshot',
            'hosted_authorized':False}
