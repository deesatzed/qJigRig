"""Translation boundary for legacy QUIXER line spans. Pure; no QUIXER import.

Legacy QUIXER reads text with universal newlines ("\\r\\n" and "\\r" become "\\n"), hashes that
normalized text, and anchors sections by 1-based inclusive line numbers (lines as produced by
str.splitlines, rejoined with "\\n"). Canonical qJig text keeps the original newlines.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError
from .sources import SourceRevision, sha256_hex
from .spans import Span, make_span


@dataclass(frozen=True)
class TranslatedSpan:
    span: Span
    legacy_normalized_sha256: str
    start_line: int
    end_line: int


def _normalize_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Return legacy-normalized text and, per normalized char, (raw_start, raw_length)."""
    chars: list[str] = []
    table: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\r":
            n = 2 if text[i + 1 : i + 2] == "\n" else 1
            chars.append("\n")
            table.append((i, n))
            i += n
        else:
            chars.append(c)
            table.append((i, 1))
            i += 1
    return "".join(chars), table


def translate_quix_lines(
    revision: SourceRevision, start_line: int, end_line: int, *, legacy_normalized_sha256: str
) -> TranslatedSpan:
    normalized, table = _normalize_with_map(revision.decoded.text)
    if sha256_hex(normalized.encode("utf-8")) != legacy_normalized_sha256:
        raise ContractError("legacy normalized hash does not match this revision's normalized text")
    if type(start_line) is not int or type(end_line) is not int:
        raise ContractError("line numbers must be integers")
    lines = normalized.splitlines(keepends=True)
    if not (1 <= start_line <= end_line <= len(lines)):
        raise ContractError(f"line range {start_line}-{end_line} outside 1..{len(lines)}")
    n_start = sum(len(x) for x in lines[: start_line - 1])
    body = "".join(lines[start_line - 1 : end_line])
    last = lines[end_line - 1]
    n_end = n_start + len(body) - (len(last) - len(last.splitlines()[0]) if last.splitlines() else 0)
    if n_end <= n_start:
        raise ContractError("legacy line span is empty")
    raw_start = table[n_start][0]
    raw_end = table[n_end - 1][0] + table[n_end - 1][1]
    return TranslatedSpan(
        make_span(revision, raw_start, raw_end), legacy_normalized_sha256, start_line, end_line
    )
