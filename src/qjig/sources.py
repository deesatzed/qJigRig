"""Source bytes and decoded text, kept as separate identities. Pure; no I/O."""
from __future__ import annotations

import hashlib
import json
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


REVISION_ID_VERSION = "rev1"


def _check_source_id(source_id: str) -> None:
    if not isinstance(source_id, str) or not source_id:
        raise ContractError("source_id must be a non-empty string")
    parts = source_id.replace("\\", "/").split("/")
    if (
        source_id.startswith(("/", "~", "\\"))
        or (len(source_id) > 1 and source_id[1] == ":")
        or ".." in parts
    ):
        raise ContractError(f"source_id must be a portable logical id, not a path: {source_id!r}")


@dataclass(frozen=True)
class SourceRevision:
    """A pinned revision of a logical source.

    revision_id depends on source_id and content/decoding identities only. `origin`
    (where this copy was read from) is recorded provenance and never part of the id.
    """

    source_id: str
    origin: str
    revision_id: str
    decoded: DecodedSource

    @classmethod
    def create(cls, source_id: str, origin: str, decoded: DecodedSource) -> "SourceRevision":
        _check_source_id(source_id)
        if not isinstance(origin, str):
            raise ContractError("origin must be a string")
        identity = json.dumps(
            {
                "source_id": source_id,
                "raw_sha256": decoded.raw_sha256,
                "text_sha256": decoded.text_sha256,
                "encoding": decoded.encoding,
                "normalizer": decoded.normalizer,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        revision_id = f"{REVISION_ID_VERSION}:{sha256_hex(identity.encode('utf-8'))}"
        return cls(source_id=source_id, origin=origin, revision_id=revision_id, decoded=decoded)

    def require_pin(self, pinned_revision_id: str) -> None:
        if self.revision_id != pinned_revision_id:
            raise ContractError(
                f"revision mismatch for {self.source_id}: pinned {pinned_revision_id}, "
                f"found {self.revision_id}"
            )
