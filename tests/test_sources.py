import hashlib

import pytest

from qjig.contracts import ContractError
from qjig.sources import decode_source


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
