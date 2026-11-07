import hashlib

import pytest

from qjig.contracts import ContractError
from qjig.sources import SourceRevision, decode_source


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_preserve_raw_bytes():
    raw = "café\r\nline2\r\n".encode("latin-1")
    src = decode_source(raw, encoding="latin-1")
    # raw identity is of the original bytes, CRLF included
    assert src.raw == raw
    assert src.raw_sha256 == sha(raw)
    # decoding is explicit and newlines are not normalized
    assert src.encoding == "latin-1"
    assert src.normalizer == "identity"
    assert src.text == "café\r\nline2\r\n"
    # text identity is of the UTF-8 encoding of the decoded text: a distinct field and value
    assert src.text_sha256 == sha(src.text.encode("utf-8"))
    assert src.text_sha256 != src.raw_sha256


def test_decoding_failure_is_explicit_not_replaced():
    with pytest.raises(ContractError):
        decode_source(b"\xff\xfe\x00bad", encoding="utf-8")


def test_encoding_must_be_named():
    with pytest.raises(TypeError):
        decode_source(b"abc")  # type: ignore[call-arg]
    with pytest.raises(ContractError):
        decode_source(b"abc", encoding="no-such-codec")
    with pytest.raises(ContractError):
        decode_source("abc", encoding="utf-8")  # type: ignore[arg-type]


def make_revision(origin, raw=b"rule: ship on green\r\n", source_id="alpha/docs/policy.md"):
    return SourceRevision.create(source_id, origin, decode_source(raw, encoding="utf-8"))


def test_portable_source_identity():
    here = make_revision("/Volumes/WS4TB/QUIX/docs/policy.md")
    moved = make_revision("/Users/other/checkout/docs/policy.md")
    # relocating the origin leaves the pinned revision identity unchanged
    assert here.origin != moved.origin
    assert here.revision_id == moved.revision_id
    assert here.source_id == moved.source_id
    # the origin is still recorded, not discarded
    assert moved.origin == "/Users/other/checkout/docs/policy.md"
    # but any change of content, encoding choice or logical source changes the identity
    assert make_revision("/x", raw=b"rule: ship on green\n").revision_id != here.revision_id
    assert make_revision("/x", source_id="alpha/docs/other.md").revision_id != here.revision_id
    latin = SourceRevision.create("alpha/docs/policy.md", "/x", decode_source(b"abc", encoding="latin-1"))
    utf = SourceRevision.create("alpha/docs/policy.md", "/x", decode_source(b"abc", encoding="utf-8"))
    assert latin.revision_id != utf.revision_id


def test_pin_check_fails_on_changed_content_not_on_move():
    pinned = make_revision("/a").revision_id
    make_revision("/b").require_pin(pinned)
    with pytest.raises(ContractError):
        make_revision("/b", raw=b"changed").require_pin(pinned)


@pytest.mark.parametrize(
    "bad", ["/abs/path.md", "C:\\docs\\p.md", "../escape.md", "a/../b.md", "", "~/x.md"]
)
def test_source_id_must_not_be_a_workstation_path(bad):
    with pytest.raises(ContractError):
        make_revision("/x", source_id=bad)
