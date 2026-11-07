"""Source bytes and decoded text, kept as separate identities. Pure; no I/O."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import ContractError

NORMALIZER_IDENTITY = "identity"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class DecodedSource:
    """Original bytes plus their explicit decoding.

    raw_sha256 hashes the original bytes. text_sha256 hashes the UTF-8 encoding of
    `text`. They are different fields and may differ even for the same file.
    """

    raw: bytes
    raw_sha256: str
    encoding: str
    normalizer: str
    text: str
    text_sha256: str


def decode_source(raw: bytes, *, encoding: str) -> DecodedSource:
    if not isinstance(raw, bytes):
        raise ContractError("raw source must be bytes")
    try:
        text = raw.decode(encoding)  # strict: never substitute replacement characters
    except LookupError as exc:
        raise ContractError(f"unknown encoding: {encoding!r}") from exc
    except UnicodeDecodeError as exc:
        raise ContractError(f"cannot decode source as {encoding}: {exc}") from exc
    return DecodedSource(
        raw=raw,
        raw_sha256=sha256_hex(raw),
        encoding=encoding,
        normalizer=NORMALIZER_IDENTITY,
        text=text,
        text_sha256=sha256_hex(text.encode("utf-8")),
    )
