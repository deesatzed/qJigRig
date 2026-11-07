"""Offline evaluation input boundaries; no provider or corpus-quality claims.

The caller must supply the complete protected-artifact manifest. Exact byte and
file-identity checks cannot detect paraphrased, encoded or undeclared labels.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath

from .contracts import ContractError

_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 256
_SHA = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class EvaluationSource:
    path: str
    raw: bytes
    sha256: str


def _manifest(items, name):
    if not isinstance(items, list) or not items or len(items) > _MAX_FILES:
        raise ContractError(f'{name} manifest must be nonempty and bounded')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ContractError('invalid evaluation artifact')
        path, digest = item['path'], item['sha256']
        if (not isinstance(path, str) or not path or '\\' in path or '\x00' in path or
                PurePosixPath(path).is_absolute() or str(PurePosixPath(path)) != path or
                not PurePosixPath(path).parts or
                any(part in ('.', '..') for part in PurePosixPath(path).parts) or
                not isinstance(digest, str) or not _SHA.fullmatch(digest) or path in seen):
            raise ContractError('invalid evaluation artifact identity')
        seen.add(path)
    return seen


def _read_pinned(root_fd, item):
    """Open relative components without following symlinks; return bytes and inode."""
    parts = PurePosixPath(item['path']).parts
    directory_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE_BYTES:
                raise ContractError('evaluation artifact is not a bounded regular file')
            chunks, remaining = [], _MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b''.join(chunks)
            if len(raw) > _MAX_FILE_BYTES or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), item['sha256']):
                raise ContractError('evaluation artifact hash or size differs')
            return raw, (info.st_dev, info.st_ino)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def load_isolated_sources(root, sources: list[dict], protected: list[dict]) -> tuple[EvaluationSource, ...]:
    """Return all allowlisted source bytes only after checking every declared artifact.

    The protected manifest is an assertion of completeness, not proof no labels
    appear in other forms. The result must be the only source input to the
    evaluation pipeline; this helper does not police other catalog entrypoints.
    """
    source_paths = _manifest(sources, 'source')
    protected_paths = _manifest(protected, 'protected')
    if source_paths & protected_paths:
        raise ContractError('source and protected paths overlap')
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY') or os.open not in os.supports_dir_fd:
        raise ContractError('safe relative file opening is unavailable')
    try:
        root_fd = os.open(os.fspath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            hidden = [_read_pinned(root_fd, item) for item in protected]
            if any(not raw for raw, _ in hidden) or len({inode for _, inode in hidden}) != len(hidden):
                raise ContractError('protected artifacts must be distinct and nonempty')
            loaded = [(_read_pinned(root_fd, item), item) for item in sources]
            private_inodes = {inode for _, inode in hidden}
            if len({pair[0][1] for pair in loaded}) != len(loaded):
                raise ContractError('source artifacts must be distinct')
            result = []
            for (raw, inode), item in loaded:
                if inode in private_inodes or any(secret in raw for secret, _ in hidden):
                    raise ContractError('protected artifact appears in source')
                result.append(EvaluationSource(item['path'], raw, item['sha256']))
            return tuple(result)
        finally:
            os.close(root_fd)
    except (OSError, ValueError, TypeError) as exc:
        raise ContractError('evaluation artifact could not be read safely') from exc


def validate_evaluation_design(design: dict, *, expected_digest: str | None = None) -> str:
    """Check declared design structure, returning its canonical SHA-256 digest.

    Relatedness, evidence adequacy and provenance are caller assertions; this
    does not establish independence, protect provider inputs, or freeze data.
    """
    import json
    import math

    partitions = {'development', 'pilot', 'holdout'}
    categories = {'supported_yes', 'supported_no', 'genuine_unknown', 'wrong_entity',
                  'wrong_date', 'conflicting_versions', 'enabling_exception',
                  'restricting_exception', 'missing_decisive', 'changed_decisive', 'irrelevant_change'}
    required = {
        'arms': {'direct_full_evidence', 'direct_retrieval', 'retrieval_only', 'decomposition_only', 'combined'},
        'separate_results': {'authored_reuse', 'escalation'},
        'metrics': {'outcome_support', 'decisive_evidence_validity', 'source_coverage', 'resource_completeness',
                    'latency', 'calls', 'input_tokens', 'output_tokens', 'cost', 'variation'},
        'outcomes': {'timeout', 'malformed', 'unsupported', 'justified_deferral', 'unjustified_deferral', 'unknown_review'},
    }
    def fail():
        raise ContractError('invalid evaluation design')
    def string(value):
        return isinstance(value, str) and bool(value.strip())
    def strings(value):
        return isinstance(value, list) and bool(value) and all(string(x) for x in value) and len(set(value)) == len(value)
    if not isinstance(design, dict) or set(design) != {'families', 'related_families', 'cases', 'arms',
            'separate_results', 'repeats', 'metrics', 'outcomes', 'criteria', 'evaluation_provenance'}:
        fail()
    if not string(design['evaluation_provenance']):
        fail()
    for key, values in required.items():
        if not strings(design[key]) or not values <= set(design[key]):
            fail()
    repeats = design['repeats']
    if not isinstance(repeats, dict) or set(repeats) != partitions or any(
            type(repeats[p]) is not int or repeats[p] < (2 if p == 'holdout' else 1) for p in partitions):
        fail()
    criteria = design['criteria']
    if not isinstance(criteria, dict) or set(criteria) != {'retain', 'revise', 'remove'}:
        fail()
    for rule in criteria.values():
        if (not isinstance(rule, dict) or set(rule) != {'metric', 'operator', 'threshold'} or
                rule['metric'] not in design['metrics'] or rule['operator'] not in ('<', '<=', '>', '>=', '==') or
                type(rule['threshold']) not in (int, float) or not math.isfinite(rule['threshold'])):
            fail()
    families, hashes = {}, {}
    if not isinstance(design['families'], list):
        fail()
    for family in design['families']:
        if (not isinstance(family, dict) or set(family) != {'id', 'partition', 'source_hashes'} or
                not string(family['id']) or family['id'] in families or not string(family['partition']) or family['partition'] not in partitions or
                not strings(family['source_hashes']) or any(not _SHA.fullmatch(x) for x in family['source_hashes'])):
            fail()
        families[family['id']] = family['partition']
        for digest in family['source_hashes']:
            if digest in hashes and hashes[digest] != family['partition']:
                fail()
            hashes[digest] = family['partition']
    if any(list(families.values()).count(p) < 2 for p in partitions):
        fail()
    if not isinstance(design['related_families'], list):
        fail()
    for pair in design['related_families']:
        if (not isinstance(pair, list) or len(pair) != 2 or not all(string(x) and x in families for x in pair)
                or pair[0] == pair[1] or families[pair[0]] != families[pair[1]]):
            fail()
    cases = {}
    if not isinstance(design['cases'], list):
        fail()
    covered = set()
    for case in design['cases']:
        if (not isinstance(case, dict) or set(case) != {'id', 'family', 'categories', 'evidence_requirements', 'parent'}
                or not string(case['id']) or case['id'] in cases or not string(case['family'])
                or case['family'] not in families or not strings(case['categories'])
                or not set(case['categories']) <= categories or not strings(case['evidence_requirements'])
                or (case['parent'] is not None and not string(case['parent']))):
            fail()
        covered.update(case['categories'])
        cases[case['id']] = case
    if covered != categories:
        fail()
    paired = set()
    for case in cases.values():
        parent = case['parent']
        if parent is not None:
            if parent not in cases or cases[parent]['family'] != case['family']:
                fail()
            paired.add(families[case['family']])
            visited = {case['id']}
            while parent is not None:
                if parent not in cases or parent in visited:
                    fail()
                visited.add(parent)
                parent = cases[parent]['parent']
        if {'missing_decisive', 'changed_decisive', 'irrelevant_change'} & set(case['categories']) and case['parent'] is None:
            fail()
    if not {'pilot', 'holdout'} <= paired:
        fail()
    try:
        canonical = json.dumps(design, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('invalid evaluation design') from exc
    digest = hashlib.sha256(canonical).hexdigest()
    if expected_digest is not None and (not isinstance(expected_digest, str) or not _SHA.fullmatch(expected_digest) or not hmac.compare_digest(digest, expected_digest)):
        raise ContractError('evaluation design digest differs')
    return digest
