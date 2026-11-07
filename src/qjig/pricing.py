"""Conservative arithmetic over a supplied catalog snapshot; not an input tokenizer.

Callers must independently verify the complete input bound, current catalog provenance,
and absence of other billable features before using the result in an execution policy.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext

from .contracts import ContractError

_INPUT_RATES = {"prompt", "input_cache_read", "input_cache_write"}
_OUTPUT_RATES = {"completion"}
_CONDITIONS = {"utc_days", "utc_start", "utc_end", "min_prompt_tokens", "max_prompt_tokens"}


def _rate(value) -> Decimal:
    if not isinstance(value, str):
        raise ContractError("price must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ContractError("invalid price") from exc
    if not result.is_finite() or result < 0:
        raise ContractError("price must be finite and non-negative")
    return result


def upper_cost(model: dict, *, input_tokens: int, output_tokens: int) -> Decimal:
    """Bound token-based charges using maximum rates across all listed overrides.

    Multiple recognized cache/input categories are summed to avoid assuming whether
    they are additive. Unknown charge categories are refused, including fixed fees.
    """
    if type(input_tokens) is not int or type(output_tokens) is not int or input_tokens < 1 or output_tokens < 1:
        raise ContractError("token bounds must be positive integers")
    if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"]:
        raise ContractError("missing model identifier")
    context = model.get("context_length")
    provider = model.get("top_provider")
    maximum = provider.get("max_completion_tokens") if isinstance(provider, dict) else None
    if type(context) is not int or type(maximum) is not int or context < 1 or maximum < 1:
        raise ContractError("missing context or output limit")
    provider_context = provider.get("context_length", context)
    if type(provider_context) is not int or provider_context < 1:
        raise ContractError("invalid provider context limit")
    if input_tokens + output_tokens > min(context, provider_context) or output_tokens > maximum:
        raise ContractError("token bounds exceed model limits")
    pricing = model.get("pricing")
    if not isinstance(pricing, dict) or not {"prompt", "completion"}.issubset(pricing):
        raise ContractError("missing token pricing")
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list) or not all(isinstance(item, dict) for item in overrides):
        raise ContractError("invalid pricing overrides")
    rates = {}
    for index, item in enumerate([pricing, *overrides]):
        allowed = _INPUT_RATES | _OUTPUT_RATES | ({"overrides"} if index == 0 else _CONDITIONS)
        if set(item) - allowed:
            raise ContractError("unsupported pricing category")
        for name in (_INPUT_RATES | _OUTPUT_RATES) & item.keys():
            rates[name] = max(rates.get(name, Decimal(0)), _rate(item[name]))
    with localcontext() as ctx:
        ctx.rounding = ROUND_CEILING
        input_rate = sum((rates.get(name, Decimal(0)) for name in _INPUT_RATES), Decimal(0))
        return input_rate * input_tokens + rates["completion"] * output_tokens
