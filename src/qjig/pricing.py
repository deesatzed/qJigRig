"""Conservative arithmetic over a supplied catalog snapshot; not an input tokenizer.

Callers must independently verify the complete input bound, current catalog provenance,
and absence of other billable features before using the result in an execution policy.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

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


def _discount_fraction(pricing: dict) -> Decimal:
    value = pricing.get('discount', 0)
    if type(value) not in (int, float):
        raise ContractError('unsupported pricing discount')
    fraction = Decimal(str(value))
    if not fraction.is_finite() or not Decimal(0) <= fraction < Decimal(1):
        raise ContractError('unsupported pricing discount')
    return fraction


def _undiscounted_rate(value, fraction: Decimal) -> Decimal:
    # OpenRouter documents a fractional discount applied to every priced SKU.
    # Inverting the reported rate is conservative whether that rate is already
    # discounted or is a base price; it is not a guarantee of future pricing.
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_CEILING
        return _rate(value) / (Decimal(1) - fraction)


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
    discount = _discount_fraction(pricing)
    for index, item in enumerate([pricing, *overrides]):
        allowed = _INPUT_RATES | _OUTPUT_RATES | ({"overrides", "discount"} if index == 0 else _CONDITIONS)
        if set(item) - allowed:
            raise ContractError("unsupported pricing category")
        for name in (_INPUT_RATES | _OUTPUT_RATES) & item.keys():
            rates[name] = max(rates.get(name, Decimal(0)), _undiscounted_rate(item[name], discount))
    with localcontext() as ctx:
        ctx.rounding = ROUND_CEILING
        input_rate = sum((rates.get(name, Decimal(0)) for name in _INPUT_RATES), Decimal(0))
        return input_rate * input_tokens + rates["completion"] * output_tokens


_APPROVED_ENDPOINT_MODELS = frozenset({
    'deepseek/deepseek-v4.1-flash-1017', 'tencent/hy4',
    'meta/muse-spark-open', 'openai/gpt-6.1-terra',
})


def parse_endpoint_snapshot(payload: dict, *, expected_model: str) -> dict:
    """Check endpoint identity while retaining pricing fields for later validation."""
    try:
        data = payload['data']
        endpoints = data['endpoints']
        if (not isinstance(expected_model, str) or not expected_model
                or data['id'] != expected_model or not isinstance(endpoints, list) or not endpoints):
            raise ValueError('model or endpoints differ')
        for endpoint in endpoints:
            if (not isinstance(endpoint, dict) or endpoint.get('model_id') != expected_model
                    or not isinstance(endpoint.get('provider_name'), str) or not endpoint['provider_name']
                    or type(endpoint.get('context_length')) is not int or endpoint['context_length'] < 1
                    or type(endpoint.get('max_completion_tokens')) is not int or endpoint['max_completion_tokens'] < 1
                    or not isinstance(endpoint.get('pricing'), dict)
                    or not {'prompt', 'completion'} <= endpoint['pricing'].keys()):
                raise ValueError('endpoint fields invalid')
        # Deep-copy without reducing unknown pricing categories or permitting NaN.
        return json.loads(json.dumps({'model': expected_model, 'endpoints': endpoints},
                                    ensure_ascii=False, allow_nan=False))
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('invalid endpoint snapshot') from exc


class _NoEndpointRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get_endpoint_catalog(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(_NoEndpointRedirect).open(req, timeout=timeout) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('endpoint response too large')
            return response.status, body.decode('utf-8')
    except urllib.error.HTTPError as exc:
        return exc.code, ''


def fetch_endpoint_snapshot(model: str, *, get=_get_endpoint_catalog) -> dict:
    """Read a public allowlisted model catalog; this does not authorize dispatch."""
    if not isinstance(model, str) or model not in _APPROVED_ENDPOINT_MODELS:
        raise ContractError('model is not approved for endpoint lookup')
    try:
        status, body = get('https://openrouter.ai/api/v1/models/' + model + '/endpoints', 15.0)
        if status != 200 or not isinstance(body, str) or len(body.encode('utf-8')) > 2_000_000:
            raise ValueError('endpoint lookup failed')
        parsed = parse_endpoint_snapshot(json.loads(body), expected_model=model)
        return {**parsed, 'observed_at': datetime.now(timezone.utc).isoformat(),
                'source': 'openrouter_public_endpoint_catalog'}
    except (OSError, ValueError, TypeError, UnicodeError, urllib.error.URLError) as exc:
        raise ContractError('endpoint lookup unavailable or invalid') from exc


def model_from_endpoint_snapshot(snapshot: dict, *, now: datetime, max_age_seconds: int) -> dict:
    """Build a conservative all-listed-endpoint model from a fresh snapshot.

    This checks a provider assertion, not routing enforcement, completeness of
    provider metadata, future prices, account billing or hosted authorization.
    """
    if (not isinstance(snapshot, dict) or snapshot.get('source') != 'openrouter_public_endpoint_catalog'
            or not isinstance(now, datetime) or now.tzinfo is None
            or type(max_age_seconds) is not int or max_age_seconds < 1):
        raise ContractError('invalid endpoint snapshot provenance')
    try:
        observed = datetime.fromisoformat(snapshot['observed_at'])
        if observed.tzinfo is None:
            raise ValueError('timestamp has no timezone')
        age = (now - observed).total_seconds()
        if age < 0 or age > max_age_seconds:
            raise ValueError('snapshot is stale or from the future')
        checked = parse_endpoint_snapshot({'data': {'id': snapshot['model'], 'endpoints': snapshot['endpoints']}},
                                          expected_model=snapshot['model'])
        maxima = {}
        for endpoint in checked['endpoints']:
            model = {'id':checked['model'], 'context_length':endpoint['context_length'],
                     'top_provider':{'max_completion_tokens':endpoint['max_completion_tokens']},
                     'pricing':endpoint['pricing']}
            # Validate all categories, discounts and overrides without assuming
            # that a route excluded by today's prices will stay excluded later.
            upper_cost(model, input_tokens=1, output_tokens=1)
            pricing = endpoint['pricing']
            discount = _discount_fraction(pricing)
            for item in [pricing, *pricing.get('overrides', [])]:
                for key in (_INPUT_RATES | _OUTPUT_RATES) & item.keys():
                    maxima[key] = max(maxima.get(key, Decimal(0)), _undiscounted_rate(item[key], discount))
        return {'id':checked['model'],
                'context_length':min(e['context_length'] for e in checked['endpoints']),
                'top_provider':{'max_completion_tokens':min(e['max_completion_tokens'] for e in checked['endpoints'])},
                'pricing':{key:str(value) for key,value in maxima.items()},
                'endpoint_snapshot': snapshot}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ContractError('endpoint snapshot cannot bound current routes') from exc
