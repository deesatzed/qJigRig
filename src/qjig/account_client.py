"""Read-only account refresh; does not authorize provider model calls."""
from __future__ import annotations

import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

from .account_limits import account_spend_constraints
from .providers import _NoRedirect, load_env_value


class AccountRefreshError(Exception):
    """Account observations were unavailable or invalid."""


def _get(url: str, headers: dict, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError('account response too large')
        return response.status, body.decode('utf-8')



def _require_credential_match(env_path: Path, expected: str) -> None:
    """Reject credential changes without logging either value or a digest."""
    current=load_env_value(Path(env_path),'OPENROUTER_API_KEY')
    try:
        matches=(isinstance(expected,str) and bool(expected) and isinstance(current,str)
                 and hmac.compare_digest(current.encode('utf-8'),expected.encode('utf-8')))
    except UnicodeError:
        matches=False
    if not matches:
        raise AccountRefreshError('account credential changed or unavailable')


def fetch_account_snapshot(env_path: Path, *, get=_get, expected_credential: str | None = None) -> tuple[dict, dict]:
    """Read only the fields needed to initialize an account-bound goal policy.

    The returned observations are time-sensitive and do not authorize model calls.
    """
    key = load_env_value(Path(env_path), 'OPENROUTER_API_KEY')
    if not key:
        raise AccountRefreshError('account credential unavailable')
    if expected_credential is not None:
        try:
            if not hmac.compare_digest(key.encode('utf-8'),expected_credential.encode('utf-8')):
                raise AccountRefreshError('account credential changed or unavailable')
        except (AttributeError,UnicodeError):
            raise AccountRefreshError('account credential changed or unavailable') from None
    try:
        responses = []
        for endpoint in ('key', 'credits'):
            status, body = get('https://openrouter.ai/api/v1/' + endpoint,
                               {'Authorization': 'Bearer ' + key}, 15.0)
            if status != 200 or not isinstance(body, str) or len(body.encode('utf-8')) > 65536:
                raise ValueError('account response unavailable')
            responses.append(json.loads(body, parse_float=Decimal))
        # Validate the complete pair before persisting either observation.
        account_spend_constraints(*responses, goal_ceiling_usd=25)
        key_data, credits_data = (response['data'] for response in responses)
        return ({'data': {name: key_data[name] for name in ('limit_remaining', 'include_byok_in_limit', 'is_free_tier')}},
                {'data': {name: credits_data[name] for name in ('total_credits', 'total_usage')}})
    except Exception:
        # Never expose a provider body, URL exception, or credential in diagnostics.
        raise AccountRefreshError('account observations unavailable or invalid') from None


def refresh_account_constraints(goal, env_path: Path, *, get=_get, expected_credential: str | None = None) -> None:
    """Fetch after a quiescent baseline, then persist a restriction.

    Account data is a time-sensitive source claim. No hosted request is authorized,
    and separate BYOK billing and concurrent external spending remain unknown.
    """
    baseline = goal.account_refresh_baseline()
    snapshot = fetch_account_snapshot(env_path, get=get, **({'expected_credential':expected_credential} if expected_credential is not None else {}))
    if expected_credential is not None:
        _require_credential_match(env_path,expected_credential)
    goal.restrict_account_snapshot(baseline, snapshot)
