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
                rule['metric'] not in design['metrics'] or rule['operator'] not in ('<', '<=', '>', '>=', '==', 'range')):
            fail()
        threshold = rule['threshold']
        values = threshold if rule['operator'] == 'range' and isinstance(threshold, list) and len(threshold) == 2 else [threshold]
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or (rule['operator'] == 'range' and (len(values) != 2 or values[0] >= values[1]))):
            fail()
    families, hashes, groups = {}, {}, {}
    def find(key):
        while groups[key] != key:
            groups[key] = groups[groups[key]]
            key = groups[key]
        return key
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            groups[b] = a
    if not isinstance(design['families'], list):
        fail()
    for family in design['families']:
        if (not isinstance(family, dict) or set(family) != {'id', 'partition', 'source_hashes'} or
                not string(family['id']) or family['id'] in families or not string(family['partition']) or family['partition'] not in partitions or
                not strings(family['source_hashes']) or any(not _SHA.fullmatch(x) for x in family['source_hashes'])):
            fail()
        families[family['id']] = family['partition']
        groups[family['id']] = family['id']
        for digest in family['source_hashes']:
            if digest in hashes:
                previous_partition, previous_family = hashes[digest]
                if previous_partition != family['partition']:
                    fail()
                union(family['id'], previous_family)
            else:
                hashes[digest] = (family['partition'], family['id'])
    if any(list(families.values()).count(p) < 2 for p in partitions):
        fail()
    if not isinstance(design['related_families'], list):
        fail()
    for pair in design['related_families']:
        if (not isinstance(pair, list) or len(pair) != 2 or not all(string(x) and x in families for x in pair)
                or pair[0] == pair[1] or families[pair[0]] != families[pair[1]]):
            fail()
        union(pair[0], pair[1])
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
    for partition in partitions:
        case_groups = {find(case['family']) for case in cases.values() if families[case['family']] == partition}
        if len(case_groups) < 2:
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



def _criteria_match(rule, value):
    from decimal import Decimal
    op, threshold = rule['operator'], rule['threshold']
    if op == 'range':
        return Decimal(str(threshold[0])) <= value < Decimal(str(threshold[1]))
    bound = Decimal(str(threshold))
    return {'<': value < bound, '<=': value <= bound, '>': value > bound,
            '>=': value >= bound, '==': value == bound}[op]


def validate_decision_criteria(design: dict, *, expected_design_sha256: str) -> None:
    """Verify exact, disjoint and exhaustive outcome-support rules over [0, 1].

    This validates a policy, not a frozen experiment or the quality of its metric.
    """
    from decimal import Decimal, localcontext
    if not isinstance(expected_design_sha256, str) or not _SHA.fullmatch(expected_design_sha256):
        raise ContractError('decision design anchor required')
    validate_evaluation_design(design, expected_digest=expected_design_sha256)
    rules = design['criteria']
    if any(rule['metric'] != 'outcome_support' for rule in rules.values()):
        raise ContractError('decision rules require a common outcome support metric')
    cuts = {Decimal(0), Decimal(1)}
    for rule in rules.values():
        values = rule['threshold'] if rule['operator'] == 'range' else [rule['threshold']]
        for value in values:
            bound = Decimal(str(value))
            if not Decimal(0) <= bound <= Decimal(1):
                raise ContractError('decision threshold outside metric domain')
            cuts.add(bound)
    ordered = sorted(cuts)
    with localcontext() as ctx:
        ctx.prec = 800  # preserve distinct intervals even at finite-float extremes
        probes = ordered + [(left + right) / 2 for left, right in zip(ordered, ordered[1:])]
    matches = [{name for name, rule in rules.items() if _criteria_match(rule, probe)} for probe in probes]
    if any(len(match) != 1 for match in matches) or set().union(*matches) != set(rules):
        raise ContractError('decision criteria overlap, leave a gap or make a decision unreachable')


def decide_from_criteria(design: dict, value, *, expected_design_sha256: str,
                         assignments_complete: bool, resources_complete: bool) -> str:
    """Apply predeclared criteria to an asserted proportion and completeness flags."""
    import math
    from decimal import Decimal
    validate_decision_criteria(design, expected_design_sha256=expected_design_sha256)
    if type(assignments_complete) is not bool or type(resources_complete) is not bool:
        raise ContractError('explicit completeness flags required')
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
        raise ContractError('invalid outcome support proportion')
    if value is None or not assignments_complete or not resources_complete:
        return 'inconclusive'
    return next(name for name, rule in design['criteria'].items() if _criteria_match(rule, Decimal(str(value))))


def summarize_evaluation_assignments(design: dict, results: list[dict], *, expected_digest: str) -> dict:
    """Account for a frozen design's assignments without scoring or inferring outcomes.

    Result status, provenance and resources are recorded assertions; receipts,
    label isolation and semantic correctness must be verified separately.
    """
    import math
    if not isinstance(expected_digest, str) or not _SHA.fullmatch(expected_digest):
        raise ContractError('frozen design digest required')
    validate_evaluation_design(design, expected_digest=expected_digest)
    families = {family['id']: family['partition'] for family in design['families']}
    count = sum(design['repeats'][families[case['family']]] for case in design['cases']) * len(design['arms'])
    if count > 100_000:
        raise ContractError('evaluation assignment set exceeds limit')
    assigned = {(case['id'], arm, repeat)
                for case in design['cases'] for arm in design['arms']
                for repeat in range(1, design['repeats'][families[case['family']]] + 1)}
    if not isinstance(results, list):
        raise ContractError('results must be a list')
    statuses = {'completed', 'timeout', 'malformed', 'unsupported', 'justified_deferral',
                'unjustified_deferral', 'unknown_review', 'provider_failure', 'retrieval_failure', 'conflict', 'unknown'}
    fields = ('calls', 'input_tokens', 'output_tokens', 'cost_usd', 'latency_ms')
    totals = {name: [] for name in fields}
    counts, seen = {}, set()
    for result in results:
        if not isinstance(result, dict) or set(result) != {'case_id', 'arm', 'repeat', 'status', 'provenance', 'resources'}:
            raise ContractError('invalid assignment result')
        case, arm, repeat = result['case_id'], result['arm'], result['repeat']
        if not isinstance(case, str) or not isinstance(arm, str) or type(repeat) is not int:
            raise ContractError('invalid assignment identity')
        key = (case, arm, repeat)
        if key not in assigned or key in seen:
            raise ContractError('duplicate or unassigned result')
        seen.add(key)
        if (not isinstance(result['status'], str) or result['status'] not in statuses or
                not isinstance(result['provenance'], str) or not result['provenance'].strip()):
            raise ContractError('invalid result status or provenance')
        resource = result['resources']
        if not isinstance(resource, dict) or set(resource) != set(fields):
            raise ContractError('invalid resource record')
        for name in fields:
            value = resource[name]
            if value is not None:
                if name in ('calls', 'input_tokens', 'output_tokens'):
                    if type(value) is not int or value < 0:
                        raise ContractError('invalid resource value')
                elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ContractError('invalid resource value')
            totals[name].append(value)
        counts[result['status']] = counts.get(result['status'], 0) + 1
    missing = sorted(assigned - seen)
    complete = not missing
    resources, all_known = {}, complete
    for name, values in totals.items():
        unknown = sum(v is None for v in values)
        try:
            known = (sum(v for v in values if v is not None) if name in ('calls', 'input_tokens', 'output_tokens')
                     else math.fsum(v for v in values if v is not None))
        except OverflowError as exc:
            raise ContractError('resource total overflow') from exc
        if isinstance(known, float) and not math.isfinite(known):
            raise ContractError('resource total overflow')
        resources['known_' + name] = known
        resources['unknown_' + name + '_records'] = unknown
        resources[name] = known if complete and not unknown else None
        all_known = all_known and not unknown
    return {'design_sha256': expected_digest, 'assigned': len(assigned), 'recorded': len(seen),
            'missing': [{'case_id': case, 'arm': arm, 'repeat': repeat} for case, arm, repeat in missing],
            'assignments_complete': complete, 'resources_complete': all_known,
            'status_counts': dict(sorted(counts.items())), 'resources': resources}


class DirectRetrieval:
    """One initial lexical search and bounded followup over declared source files.

    Isolation inherits the loader's limits: protected-manifest completeness and
    transformed labels are not established. This is retrieval, not an answer or
    a model baseline; callers must provide the same frozen access and budgets.
    """
    def __init__(self, root, sources: list[dict], protected: list[dict], *,
                 want: int, max_bytes: int, followups: int, expanded: bool = False):
        from .indexing import index_entries
        from .sources import SourceRevision, decode_source
        if (type(want) is not int or not 1 <= want <= 100 or type(max_bytes) is not int
                or not 1 <= max_bytes <= _MAX_FILE_BYTES or type(followups) is not int
                or not 0 <= followups <= 1 or type(expanded) is not bool):
            raise ContractError('invalid direct retrieval bounds')
        loaded = load_isolated_sources(root, sources, protected)
        entries = []
        revisions = []
        for source in loaded:
            revision = SourceRevision.create(source.path, 'evaluation_allowlist', decode_source(source.raw, encoding='utf-8'))
            entries.extend(index_entries(revision))
            revisions.append(revision)
        self._revisions = tuple(revisions)
        self._entries = entries
        self._want = want
        self._max_bytes = max_bytes
        self._max_rounds = 1 + followups
        self._expanded = expanded
        self._trace = []

    @property
    def trace(self) -> tuple[dict, ...]:
        return tuple(dict(row) for row in self._trace)

    def search(self, query: str) -> dict:
        from .packets import build_packet
        from .retrieval import bm25_candidates, bm25_expanded_candidates
        if len(self._trace) >= self._max_rounds:
            raise ContractError('direct retrieval round limit reached')
        if not isinstance(query, str) or not query.strip() or len(query.encode('utf-8')) > 4096:
            raise ContractError('invalid direct retrieval query')
        candidates = (bm25_expanded_candidates if self._expanded else bm25_candidates)(self._entries, query)
        packet = build_packet(candidates[:self._want], max_bytes=self._max_bytes)
        record = {'round': len(self._trace) + 1, 'query': query, 'matches': len(candidates),
                  'top_k_omitted': len(candidates) - min(len(candidates), self._want),
                  'method': 'bm25_query_expansion_v1' if self._expanded else 'bm25_okapi_v1',
                  'interpretation': 'candidates_not_validated' if candidates else 'no_hits_not_evidence_of_absence'}
        self._trace.append(record)
        return {**record, 'packet': packet}


def _full_source_entries(revisions):
    """Create deterministic, whole-text evidence entries for pinned revisions."""
    from .indexing import IndexEntry, make_entry_id
    from .spans import make_span
    entries = []
    for revision in sorted(revisions, key=lambda r: r.revision_id):
        text = revision.decoded.text
        if not text:
            raise ContractError('empty source cannot be represented as a full-text span')
        span = make_span(revision, 0, len(text))
        ident = make_entry_id(revision.revision_id, 'full_source', 'full_source_v1', 0, len(text))
        entries.append(IndexEntry(ident, revision.revision_id, span, 'full_source', None, 'full_source_v1', 'accepted'))
    return entries


def _full_source_packet(entries, max_bytes):
    from .packets import build_packet
    packet = build_packet(entries, max_bytes=max_bytes)
    if packet.omitted or packet.truncated_entry_ids or len(packet.items) != len(entries):
        raise ContractError('full source evidence exceeds packet budget')
    return packet


class FullEvidence(DirectRetrieval):
    """Provide all declared source text in one packet or refuse before dispatch."""
    def __init__(self, root, sources: list[dict], protected: list[dict], *, want: int, max_bytes: int):
        super().__init__(root, sources, protected, want=want, max_bytes=max_bytes, followups=0, expanded=False)
        self._entries = _full_source_entries(self._revisions)
        self._packet = _full_source_packet(self._entries, max_bytes)

    def search(self, query: str) -> dict:
        if self._trace:
            raise ContractError('full evidence has no search followup')
        if not isinstance(query, str) or not query.strip() or len(query.encode('utf-8')) > 4096:
            raise ContractError('invalid full evidence question')
        record = {'round': 1, 'query': query, 'matches': len(self._entries), 'top_k_omitted': 0,
                  'method': 'full_source_v1', 'interpretation': 'complete_source_text_supplied'}
        self._trace.append(record)
        return {**record, 'packet': self._packet}


class CatalogRetrieval(DirectRetrieval):
    """Expose qJig's planning acquisition for a non-decomposed question.

    Applicability is caller-supplied metadata, and missing channel hits never
    establish the absence of an exception. This class does not call a model.
    """
    def __init__(self, root, sources: list[dict], protected: list[dict], *, want: int,
                 max_bytes: int, followups: int, applicability_inputs, scope: str, role_priors=None):
        from .applicability import ApplicabilityInputs
        from .acquisition import _check_role_priors
        if not isinstance(applicability_inputs, ApplicabilityInputs) or not isinstance(scope, str) or not scope.strip():
            raise ContractError('recorded applicability and scope required')
        priors = {} if role_priors is None else role_priors
        _check_role_priors(priors)
        super().__init__(root, sources, protected, want=want, max_bytes=max_bytes, followups=followups, expanded=True)
        self._inputs = ApplicabilityInputs.from_dict(applicability_inputs.to_dict())
        if {m.revision_id for m in self._inputs.collection.members} != {r.revision_id for r in self._revisions}:
            raise ContractError('catalog applicability source set differs')
        self._scope, self._role_priors = scope, dict(priors)

    def search(self, query: str) -> dict:
        import json
        from .acquisition import _planning_packet
        from .applicability import combine_applicability, scope_applicability
        from .packets import EvidencePacket, Omission, PacketItem
        from .spans import Span
        from .store import Catalog
        if len(self._trace) >= self._max_rounds:
            raise ContractError('catalog retrieval round limit reached')
        if not isinstance(query, str) or not query.strip() or len(query.encode('utf-8')) > 4096:
            raise ContractError('invalid catalog retrieval query')
        def applicability(revision_id):
            member = self._inputs.collection.member(revision_id)
            return combine_applicability(self._inputs.verdict(revision_id), scope_applicability(self._scope,member.scope))
        with Catalog.open(':memory:') as catalog:
            for revision in self._revisions:
                catalog.add_revision(revision)
            evidence = _planning_packet(catalog,self._entries,query,applicability,want=self._want,
                                        max_bytes=self._max_bytes,role_priors=self._role_priors)
        raw = evidence.pop('packet')
        items = tuple(PacketItem(i['entry_id'],Span(i['revision_id'],i['text_sha256'],i['start'],i['end'],i['text']),
                                 i['truncated'],i['original_end']) for i in raw['items'])
        omitted = tuple(Omission(i['entry_id'],i['reason']) for i in raw['omitted'])
        size = len(json.dumps(raw,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        packet = EvidencePacket(items,omitted,tuple(i.entry_id for i in items if i.truncated),raw['limit'],size)
        record = {'round':len(self._trace)+1,'query':query,'matches':evidence['channel_hits']['primary'],
                  'method':'qjig_catalog_v1','interpretation':'untrusted_incomplete','channels':evidence}
        self._trace.append(record)
        return {**record,'packet':packet}
