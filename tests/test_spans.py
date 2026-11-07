import pytest

from qjig.contracts import ContractError
from qjig.sources import SourceRevision, decode_source
from qjig.spans import make_span, verify_span

TEXT = "naïve 日本語 😀 end"  # includes a 2-byte, 3-byte and an astral (4-byte, 2 UTF-16 unit) character


def revision(text=TEXT):
    return SourceRevision.create("p/doc.txt", "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


def test_verify_unicode_span():
    rev = revision()
    start = TEXT.index("日本語")
    span = make_span(rev, start, start + 3)
    assert span.text == "日本語"
    verify_span(rev, span)
    # code-point offsets, end-exclusive: the astral character counts as one position
    emoji = TEXT.index("😀")
    s2 = make_span(rev, emoji, emoji + 1)
    assert s2.text == "😀"
    verify_span(rev, s2)
    # an altered quote fails
    from dataclasses import replace

    with pytest.raises(ContractError):
        verify_span(rev, replace(span, text="日本誌"))
    # moving the offsets without changing the quote fails
    with pytest.raises(ContractError):
        verify_span(rev, replace(span, start=span.start + 1, end=span.end + 1))


def test_span_bound_to_revision_text_identity():
    from dataclasses import replace

    rev = revision()
    span = make_span(rev, 0, 5)
    other = revision("naïve 日本語 😀 end!")
    with pytest.raises(ContractError):
        verify_span(other, span)  # same quote exists, but a different revision
    with pytest.raises(ContractError):
        verify_span(rev, replace(span, text_sha256="0" * 64))


@pytest.mark.parametrize("start,end", [(-1, 3), (3, 3), (4, 3), (0, len(TEXT) + 1), (True, 3)])
def test_invalid_offsets_rejected(start, end):
    with pytest.raises(ContractError):
        make_span(revision(), start, end)
