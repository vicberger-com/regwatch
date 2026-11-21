"""Run inside the release image (CI `images` job; M10.4): every regwatch module, the Celery app
and its transports import with the runtime dependencies alone. M10.3 found the worker failing
on a module only the development dependencies brought (packaging)."""

from __future__ import annotations

import importlib
import pkgutil
import sys

import regwatch

failures = []
for module in pkgutil.walk_packages(regwatch.__path__, "regwatch."):
    try:
        importlib.import_module(module.name)
    except Exception as exc:  # noqa: BLE001 - every failure is reported
        failures.append(f"{module.name}: {type(exc).__name__}: {exc}")
for name in ("kombu.transport.redis", "celery.backends.redis", "ippx", "prometheus_client"):
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
from regwatch.core.worker import celery_app  # noqa: E402

celery_app()
print("\n".join(failures) or "every module imports")
sys.exit(1 if failures else 0)
