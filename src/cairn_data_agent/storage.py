from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    byte_size: int


class LocalBlobStore:
    """Small content-addressed store; callers never construct blob paths."""

    def __init__(self, root: Path):
        self._root = root / "blobs"
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> StoredBlob:
        digest = hashlib.sha256(content).hexdigest()
        target = self._path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix="blob-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, target)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        return StoredBlob(sha256=digest, byte_size=len(content))

    def get(self, sha256: str) -> bytes:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("invalid blob digest")
        content = self._path(sha256).read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise OSError("blob digest verification failed")
        return content

    def _path(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256[2:]
