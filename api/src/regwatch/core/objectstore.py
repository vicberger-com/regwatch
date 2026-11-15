"""Object store: bytes under server-generated keys (local directory now; S3 is BL-79).

Keys are made by the application, never taken from a request, and are still checked here: lower
case letters, digits, ``-``, ``_``, ``.`` and ``/`` separators, no empty or dot segments, so a key
can only name a file inside the store's root. Writes go to a temporary file in the same directory
and are renamed into place, so a reader never sees half a file.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from regwatch.core.settings import get_settings

_KEY = re.compile(r"[a-z0-9_-][a-z0-9._-]{0,127}(/[a-z0-9_-][a-z0-9._-]{0,127}){0,7}")


class ObjectStoreError(RuntimeError):
    """The store is not usable as configured, or a key is malformed."""


def _path(key: str) -> Path:
    if not _KEY.fullmatch(key) or any(part in {".", ".."} for part in key.split("/")):
        raise ObjectStoreError(f"malformed object key: {key!r}")
    settings = get_settings()
    if settings.object_store_s3_endpoint is not None:
        raise ObjectStoreError("the S3 object store is not implemented yet (BL-79)")
    root = Path(settings.object_store_path).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):  # a symlink inside the store that points out of it
        raise ObjectStoreError(f"object key leaves the store: {key!r}")
    return path


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


async def put(key: str, data: bytes) -> None:
    await asyncio.to_thread(_write, _path(key), data)


async def get(key: str) -> bytes | None:
    """The object's bytes, or None when there is no such object."""
    return await asyncio.to_thread(_read, _path(key))
