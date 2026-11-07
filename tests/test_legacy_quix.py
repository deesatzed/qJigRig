import pytest

from qjig.contracts import ContractError
from qjig.legacy_quix import translate_quix_lines
from qjig.sources import SourceRevision, decode_source
from qjig.spans import verify_span

# Recorded from the real legacy runs (reports/compatibility-probes.json) for b"One\r\nTwo\r\n".
QUIX_HASH = "2fcfb7830c3bb1c40b0a64f0549acc4c661f7f9f8c39d3b8ecaaf51313670f68"  # hash of "One\nTwo\n"
JIG_HASH = "6a3b3844470e683f7a512580fadff3a56d3f793f7339eef7cecddaf7a7d82b8e"  # hash of raw CRLF text


def rev(raw: bytes):
    return SourceRevision.create("p/doc.txt", "/x", decode_source(raw, encoding="utf-8"))


def test_translate_normalized_lines():
    revision = rev(b"One\r\nTwo\r\n")
    t = translate_quix_lines(revision, 2, 2, legacy_normalized_sha256=QUIX_HASH)
    # canonical span is a slice of the raw (CRLF-preserving) text, verified against the revision
    assert t.span.text == "Two"
    assert (t.span.start, t.span.end) == (5, 8)
    verify_span(revision, t.span)
    # the three identities stay distinct
    assert t.legacy_normalized_sha256 == QUIX_HASH
    assert revision.decoded.raw_sha256 == JIG_HASH
    assert len({t.legacy_normalized_sha256, revision.decoded.raw_sha256}) == 2
    assert t.span.revision_id == revision.revision_id
    # a multi-line legacy span covers the CRLF between lines in canonical offsets
    both = translate_quix_lines(revision, 1, 2, legacy_normalized_sha256=QUIX_HASH)
    assert both.span.text == "One\r\nTwo"
    assert (both.span.start, both.span.end) == (0, 8)


def test_lone_cr_and_lf_files_translate_too():
    revision = rev(b"a\rb\nc")
    import hashlib

    h = hashlib.sha256(b"a\nb\nc").hexdigest()
    assert translate_quix_lines(revision, 2, 3, legacy_normalized_sha256=h).span.text == "b\nc"
    assert translate_quix_lines(revision, 1, 2, legacy_normalized_sha256=h).span.text == "a\rb"


def test_legacy_hash_mismatch_and_bad_lines_rejected():
    revision = rev(b"One\r\nTwo\r\n")
    with pytest.raises(ContractError):
        translate_quix_lines(revision, 1, 1, legacy_normalized_sha256=JIG_HASH)  # wrong contract's hash
    for a, b in [(0, 1), (2, 1), (1, 3), (True, 1)]:
        with pytest.raises(ContractError):
            translate_quix_lines(revision, a, b, legacy_normalized_sha256=QUIX_HASH)
