import pytest

from qjig.contracts import ContractError
from qjig.legacy_jig import translate_jig_offsets, translate_jig_quote
from qjig.sources import SourceRevision, decode_source
from qjig.spans import verify_span

JIG_HASH = "6a3b3844470e683f7a512580fadff3a56d3f793f7339eef7cecddaf7a7d82b8e"  # real JIG hash of "One\r\nTwo\r\n"


def rev(raw: bytes, source_id="p/doc.txt"):
    return SourceRevision.create(source_id, "/x", decode_source(raw, encoding="utf-8"))


def test_translate_raw_offsets():
    revision = rev(b"One\r\nTwo\r\n")
    span = translate_jig_offsets(revision, JIG_HASH, 5, 8, "Two")
    assert span.text == "Two" and (span.start, span.end) == (5, 8)
    verify_span(revision, span)
    # a unique quote resolves to the same canonical span
    assert translate_jig_quote(revision, JIG_HASH, "Two") == span


def test_same_text_cannot_bind_to_changed_revision():
    original_hash = JIG_HASH
    changed = rev(b"One\r\nTwo\r\nThree\r\n")  # still contains the quote at the same offsets
    assert changed.decoded.text[5:8] == "Two"
    with pytest.raises(ContractError):
        translate_jig_offsets(changed, original_hash, 5, 8, "Two")
    with pytest.raises(ContractError):
        translate_jig_quote(changed, original_hash, "Two")


def test_wrong_quote_missing_and_ambiguous_quotes_rejected():
    revision = rev(b"One\r\nTwo\r\n")
    with pytest.raises(ContractError):
        translate_jig_offsets(revision, JIG_HASH, 5, 8, "Tow")
    with pytest.raises(ContractError):
        translate_jig_quote(revision, JIG_HASH, "absent")
    dup = rev(b"ab ab")
    import hashlib

    h = hashlib.sha256(b"ab ab").hexdigest()
    with pytest.raises(ContractError):
        translate_jig_quote(dup, h, "ab")
    with pytest.raises(ContractError):
        translate_jig_quote(dup, h, "   ")
