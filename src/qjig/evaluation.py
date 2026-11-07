"""Offline evaluation input boundaries; no provider or corpus-quality claims.

The caller must supply the complete protected-artifact manifest. Exact byte and
file-identity checks cannot detect paraphrased, encoded or undeclared labels.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath

from .contracts import ContractError

_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 256
_SHA = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class EvaluationSource:
    path: str
    raw: bytes
    sha256: str


def _manifest(items, name):
    if not isinstance(items, list) or not items or len(items) > _MAX_FILES:
        raise ContractError(f'{name} manifest must be nonempty and bounded')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ContractError('invalid evaluation artifact')
        path, digest = item['path'], item['sha256']
        if (not isinstance(path, str) or not path or '\\' in path or '\x00' in path or
                PurePosixPath(path).is_absolute() or str(PurePosixPath(path)) != path or
                not PurePosixPath(path).parts or
                any(part in ('.', '..') for part in PurePosixPath(path).parts) or
                not isinstance(digest, str) or not _SHA.fullmatch(digest) or path in seen):
            raise ContractError('invalid evaluation artifact identity')
        seen.add(path)
    return seen


def _read_pinned(root_fd, item):
    """Open relative components without following symlinks; return bytes and inode."""
    parts = PurePosixPath(item['path']).parts
    directory_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE_BYTES:
                raise ContractError('evaluation artifact is not a bounded regular file')
            chunks, remaining = [], _MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b''.join(chunks)
            if len(raw) > _MAX_FILE_BYTES or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), item['sha256']):
                raise ContractError('evaluation artifact hash or size differs')
            return raw, (info.st_dev, info.st_ino)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def load_isolated_sources(root, sources: list[dict], protected: list[dict]) -> tuple[EvaluationSource, ...]:
    """Return all allowlisted source bytes only after checking every declared artifact.

    The protected manifest is an assertion of completeness, not proof no labels
    appear in other forms. The result must be the only source input to the
    evaluation pipeline; this helper does not police other catalog entrypoints.
    """
    source_paths = _manifest(sources, 'source')
    protected_paths = _manifest(protected, 'protected')
    if source_paths & protected_paths:
        raise ContractError('source and protected paths overlap')
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY') or os.open not in os.supports_dir_fd:
        raise ContractError('safe relative file opening is unavailable')
    try:
        root_fd = os.open(os.fspath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            hidden = [_read_pinned(root_fd, item) for item in protected]
            if any(not raw for raw, _ in hidden) or len({inode for _, inode in hidden}) != len(hidden):
                raise ContractError('protected artifacts must be distinct and nonempty')
            loaded = [(_read_pinned(root_fd, item), item) for item in sources]
            private_inodes = {inode for _, inode in hidden}
            if len({pair[0][1] for pair in loaded}) != len(loaded):
                raise ContractError('source artifacts must be distinct')
            result = []
            for (raw, inode), item in loaded:
                if inode in private_inodes or any(secret in raw for secret, _ in hidden):
                    raise ContractError('protected artifact appears in source')
                result.append(EvaluationSource(item['path'], raw, item['sha256']))
            return tuple(result)
        finally:
            os.close(root_fd)
    except (OSError, ValueError, TypeError) as exc:
        raise ContractError('evaluation artifact could not be read safely') from exc
