"""The package layout is part of docs/contracts/M0-tooling.md."""

from __future__ import annotations

import importlib

import pytest
from fastapi import APIRouter

SUBPACKAGES = [
    "core",
    "identity",
    "taxonomy",
    "capture",
    "processing",
    "search",
    "reports",
    "outputs",
    "admin",
    "api",
]
STANDARD = ["router", "models", "schemas", "services", "tasks", "permissions"]


@pytest.mark.parametrize("pkg", SUBPACKAGES)
def test_subpackage_exposes_standard_modules(pkg: str) -> None:
    for name in STANDARD:
        importlib.import_module(f"regwatch.{pkg}.{name}")
    router = importlib.import_module(f"regwatch.{pkg}.router").router
    assert isinstance(router, APIRouter)
    permissions = importlib.import_module(f"regwatch.{pkg}.permissions").PERMISSIONS
    assert isinstance(permissions, tuple)
