"""Role-scoped clients for the loopback service; roles are context, not authority."""
from __future__ import annotations

import http.client
import json
import re

from .contracts import ContractError, Request
from .roles import RoleDefinition

_MAX_RESPONSE = 2_000_000


class ClientError(Exception):
    """The local service rejected a request or returned an invalid envelope."""


class RoleClient:
    """A distinct role context over one IPv4-loopback qJig service.

    No role authorizes access or certifies evidence. This client supports the
    existing deterministic API; it does not invoke the fresh hosted pipeline.
    """
    def __init__(self, port: int, role: RoleDefinition, *, timeout: float = 5):
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(role, RoleDefinition):
            raise ContractError('valid loopback port and role are required')
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise ContractError('invalid local service timeout')
        self.port, self.role, self.timeout = port, role, timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {}
        payload = None
        if body is not None:
            try:
                payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            except (TypeError, ValueError) as exc:
                raise ContractError('request is not JSON serializable') from exc
            headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}'}
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)
        try:
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            raw = response.read(_MAX_RESPONSE + 1)
            if len(raw) > _MAX_RESPONSE or response.status not in (200, 201):
                raise ClientError(f'local service returned status {response.status} or oversized response')
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ClientError('local service returned invalid JSON') from exc
            if not isinstance(value, dict):
                raise ClientError('local service returned invalid envelope')
            return value
        finally:
            connection.close()

    def import_source(self, source: dict) -> dict:
        if not isinstance(source, dict):
            raise ContractError('source must be an object')
        return self._request('POST', '/api/sources', source)

    def list_sources(self) -> list[dict]:
        result = self._request('GET', '/api/sources')
        if not isinstance(result.get('sources'), list):
            raise ClientError('local service returned invalid source list')
        return result['sources']

    def get_source(self, revision_id: str) -> dict:
        if not isinstance(revision_id, str) or not re.fullmatch(r'rev1:[0-9a-f]{64}', revision_id):
            raise ContractError('invalid revision identity')
        return self._request('GET', '/api/sources/' + revision_id)

    def add_interpretation(self, text: str, evidence: dict) -> dict:
        if not isinstance(text, str) or not text.strip() or not isinstance(evidence, dict):
            raise ContractError('interpretation text and evidence are required')
        return self._request('POST', '/api/interpretations', {'role_id': self.role.role_id,
                             'role_version': self.role.version, 'text': text, 'evidence': evidence})

    def list_interpretations(self) -> list[dict]:
        result = self._request('GET', '/api/interpretations')
        if not isinstance(result.get('interpretations'), list):
            raise ClientError('local service returned invalid interpretation list')
        return result['interpretations']

    def intervene(self, parent_revision_id: str, text_sha256: str, start: int, end: int, replacement: str) -> dict:
        return self._request('POST', '/api/interventions', {'parent_revision_id': parent_revision_id,
                             'text_sha256': text_sha256, 'start': start, 'end': end, 'replacement': replacement,
                             'role_id': self.role.role_id, 'role_version': self.role.version})

    def list_interventions(self) -> list[dict]:
        result = self._request('GET', '/api/interventions')
        if not isinstance(result.get('interventions'), list):
            raise ClientError('local service returned invalid intervention list')
        return result['interventions']

    def get_run(self, run_id: str) -> dict:
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ContractError('invalid run identity')
        return self._request('GET', '/api/runs/' + run_id)

    def list_runs(self) -> list[dict]:
        result = self._request('GET', '/api/runs')
        if not isinstance(result.get('runs'), list):
            raise ClientError('local service returned invalid run list')
        return result['runs']

    def ask(self, request_id: str, question: str, scope: str, policy: dict) -> dict:
        if any(not isinstance(value, str) or not value.strip() for value in (request_id, question, scope)) or not isinstance(policy, dict):
            raise ContractError('request identity, question, scope and policy are required')
        request = Request(request_id, question, self.role.role_id, self.role.version, scope)
        return self._request('POST', '/api/ask', {'request': request.to_dict(), 'policy': policy})
