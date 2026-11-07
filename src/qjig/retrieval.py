"""Deterministic lexical retrieval over index entries, with score provenance. Pure."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace

from .indexing import IndexEntry
from .spans import Span

BM25_METHOD = "bm25_okapi_v1"
K1 = 1.2
B = 0.75

_TOKEN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass(frozen=True)
class TermScore:
    term: str
    term_frequency: int
    document_frequency: int
    contribution: float


@dataclass(frozen=True)
class ScoreProvenance:
    method: str
    k1: float
    b: float
    corpus_size: int
    average_length: float
    terms: tuple[TermScore, ...]


@dataclass(frozen=True)
class Candidate:
    entry_id: str
    revision_id: str
    span: Span
    score: float
    provenance: ScoreProvenance


def bm25_candidates(entries: list[IndexEntry], query: str) -> list[Candidate]:
    """Entries with at least one query term, best first; ties break by entry_id ascending."""
    docs = [(e, Counter(tokenize(e.span.text))) for e in entries]
    n = len(docs)
    q_terms = sorted(set(tokenize(query)))
    if n == 0 or not q_terms:
        return []
    lengths = {e.entry_id: sum(tf.values()) for e, tf in docs}
    avg = sum(lengths.values()) / n
    df = {t: sum(1 for _, tf in docs if t in tf) for t in q_terms}
    out: list[Candidate] = []
    for e, tf in docs:
        contributions = []
        for t in q_terms:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            norm = f + K1 * (1 - B + B * lengths[e.entry_id] / avg) if avg else f + K1
            contributions.append(TermScore(t, f, df[t], idf * f * (K1 + 1) / norm))
        if contributions:
            score = sum(c.contribution for c in contributions)
            prov = ScoreProvenance(BM25_METHOD, K1, B, n, avg, tuple(contributions))
            out.append(Candidate(e.entry_id, e.revision_id, e.span, score, prov))
    out.sort(key=lambda c: (-c.score, c.entry_id))
    return out


# Small, explicit morphology set derived from the recorded refund counterexamples.
# This is not a general stemmer or a claim that matching passages are relevant.
EXPANDED_BM25_METHOD = "bm25_query_expansion_v1"
_QUERY_EXPANSIONS = {
    "refund": ("refunds", "refunded"),
    "exception": ("exceptions",),
    "waiver": ("waivers",),
}


def expand_query_v1(query: str) -> str:
    """Append controlled lexical variants; original query terms remain intact."""
    original = tokenize(query)
    extra = sorted({variant for term in original for variant in _QUERY_EXPANSIONS.get(term, ())})
    return " ".join(original + extra)


def bm25_expanded_candidates(entries: list[IndexEntry], query: str) -> list[Candidate]:
    """BM25 over the versioned expanded query, retaining original source spans."""
    return [replace(candidate, provenance=replace(candidate.provenance, method=EXPANDED_BM25_METHOD))
            for candidate in bm25_candidates(entries, expand_query_v1(query))]


NEUTRAL_PRIOR = 0.5  # used only when no role estimate exists; never excludes anything


@dataclass(frozen=True)
class Selection:
    selected: tuple[tuple[str, Candidate], ...]  # (channel, candidate)
    missing_required: tuple[str, ...]  # required channels with no candidate at all
    omitted_required: tuple[str, ...]  # required channels that had candidates but no room


def select_with_mandatory(
    channels: dict[str, list[Candidate]],
    required_channels: set[str],
    limit: int,
    role_priors: dict[str, float],
) -> Selection:
    """Pick up to `limit` candidates; every required channel with a candidate gets its best first.

    Within a channel, order is lexical score, then role prior (a tie-breaker only), then entry_id.
    Role priors never remove a candidate or a channel.
    """
    ordered = {
        ch: sorted(cs, key=lambda c: (-c.score, -role_priors.get(c.entry_id, NEUTRAL_PRIOR), c.entry_id))
        for ch, cs in channels.items()
    }
    missing = tuple(sorted(ch for ch in required_channels if not ordered.get(ch)))
    reserve = [ch for ch in sorted(required_channels) if ordered.get(ch)]
    chosen: list[tuple[str, Candidate]] = []
    taken: set[tuple[str, str]] = set()
    omitted = []
    for ch in reserve:
        if len(chosen) < limit:
            c = ordered[ch][0]
            chosen.append((ch, c))
            taken.add((ch, c.entry_id))
        else:
            omitted.append(ch)
    rest = sorted(
        ((ch, c) for ch, cs in ordered.items() for c in cs if (ch, c.entry_id) not in taken),
        key=lambda x: (-x[1].score, -role_priors.get(x[1].entry_id, NEUTRAL_PRIOR), x[0], x[1].entry_id),
    )
    for item in rest:
        if len(chosen) >= limit:
            break
        chosen.append(item)
    chosen.sort(key=lambda x: (-x[1].score, -role_priors.get(x[1].entry_id, NEUTRAL_PRIOR), x[0], x[1].entry_id))
    return Selection(tuple(chosen), missing, tuple(omitted))


@dataclass(frozen=True)
class UniqueSelection:
    candidates: tuple[Candidate, ...]
    covered: tuple[str, ...]
    missing: tuple[str, ...]
    omitted: tuple[str, ...]


def select_unique_with_mandatory(channels: dict[str, list[Candidate]], required_channels: set[str],
                                 limit: int, role_priors: dict[str, float]) -> UniqueSelection:
    """Reserve channel access without counting a shared source span twice."""
    if type(limit) is not int or limit < 1:
        raise ValueError("selection limit must be a positive integer")
    ordered = {name: sorted(items, key=lambda c: (-c.score, -role_priors.get(c.entry_id, NEUTRAL_PRIOR), c.entry_id))
               for name, items in channels.items()}
    chosen: dict[str, Candidate] = {}
    order = sorted(required_channels, key=lambda name: (name != "primary", name))
    for name in order:
        items = ordered.get(name, [])
        if not items or any(c.entry_id in chosen for c in items):
            continue
        if len(chosen) < limit:
            chosen[items[0].entry_id] = items[0]
    for _, candidate in sorted(((name, c) for name, items in ordered.items() for c in items),
                               key=lambda pair: (-pair[1].score, -role_priors.get(pair[1].entry_id, NEUTRAL_PRIOR), pair[0], pair[1].entry_id)):
        if len(chosen) >= limit:
            break
        chosen.setdefault(candidate.entry_id, candidate)
    covered = tuple(sorted(name for name, items in ordered.items() if any(c.entry_id in chosen for c in items)))
    missing = tuple(sorted(name for name in required_channels if not ordered.get(name)))
    omitted = tuple(sorted(name for name in required_channels if ordered.get(name) and name not in covered))
    return UniqueSelection(tuple(chosen.values()), covered, missing, omitted)
