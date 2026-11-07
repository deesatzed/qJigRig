"""Deterministic lexical retrieval over index entries, with score provenance. Pure."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

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
