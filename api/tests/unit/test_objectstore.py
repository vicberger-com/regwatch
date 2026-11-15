"""The local object store: server-made keys only, atomic writes (BL-68)."""

from __future__ import annotations

from pathlib import Path

import pytest

from regwatch.core import objectstore
from regwatch.core.settings import get_settings


@pytest.fixture
def store(valid_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("REGWATCH_OBJECT_STORE_PATH", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


async def test_put_then_get(store: Path) -> None:
    await objectstore.put("branding/logo-ab.png", b"one")
    await objectstore.put("branding/logo-ab.png", b"two")
    assert await objectstore.get("branding/logo-ab.png") == b"two"
    assert (store / "branding" / "logo-ab.png").read_bytes() == b"two"
    assert not [p for p in (store / "branding").iterdir() if p.name.startswith(".tmp-")]


async def test_missing_object_is_none(store: Path) -> None:
    assert await objectstore.get("branding/none.png") is None


@pytest.mark.parametrize(
    "key",
    ["../escape", "branding/../../etc/passwd", "/abs", "a//b", "a/./b", ".hidden", "UPPER",
     "a b", "a\\b", "", "x/" * 9 + "y"],
)  # fmt: skip
async def test_malformed_keys_are_refused(store: Path, key: str) -> None:
    with pytest.raises(objectstore.ObjectStoreError, match="malformed"):
        await objectstore.put(key, b"x")
    with pytest.raises(objectstore.ObjectStoreError, match="malformed"):
        await objectstore.get(key)


async def test_s3_is_not_used_silently(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGWATCH_OBJECT_STORE_S3_ENDPOINT", "https://s3.example.org")
    get_settings.cache_clear()
    with pytest.raises(objectstore.ObjectStoreError, match="BL-79"):
        await objectstore.get("branding/logo.png")


async def test_failed_write_leaves_no_temporary_file(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(objectstore.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        await objectstore.put("branding/logo-x.png", b"data")
    assert list((store / "branding").iterdir()) == []


async def test_a_symlink_out_of_the_store_is_refused(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """BL-68 review finding 8: resolve() follows links, so the root check is the guard."""
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.png").write_bytes(b"secret")
    (store / "branding").symlink_to(outside, target_is_directory=True)
    with pytest.raises(objectstore.ObjectStoreError, match="leaves the store"):
        await objectstore.get("branding/secret.png")
