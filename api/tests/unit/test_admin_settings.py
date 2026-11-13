"""Setting value checks against the registry definitions (#32, REQ-16)."""

from __future__ import annotations

from typing import Any

import pytest

from regwatch.admin import services
from regwatch.core import registry
from regwatch.core.errors import ProblemError

DEFS = registry.settings()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("general.site_title", "Policy Watch"),
        ("auth.lockout_threshold", 10),
        ("auth.password_min_length", 12),
        ("processing.change_threshold_pct", 2.5),
        ("auth.breach_check_enabled", True),
        ("map.projection", "mercator"),
        ("outputs.allowed_recipient_domains", ["example.org"]),
        ("capture.max_body_bytes", 0),
    ],
)
def test_valid_values_pass(key: str, value: Any) -> None:
    assert services.check_value(DEFS[key], value) == value


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("general.site_title", 1),
        ("general.site_title", "x" * (services.MAX_STRING + 1)),
        ("auth.lockout_threshold", True),
        ("auth.lockout_threshold", 2),
        ("auth.password_min_length", 11),
        ("sessions.idle_timeout_max_minutes", 10),
        ("capture.max_body_bytes", -1),
        ("processing.change_threshold_pct", float("nan")),
        ("processing.change_threshold_pct", -1),
        ("processing.change_threshold_pct", False),
        ("auth.breach_check_enabled", "yes"),
        ("map.projection", "robinson"),
        ("outputs.allowed_recipient_domains", "example.org"),
        ("outputs.allowed_recipient_domains", [1]),
    ],
)
def test_invalid_values_are_400(key: str, value: Any) -> None:
    with pytest.raises(ProblemError) as exc:
        services.check_value(DEFS[key], value)
    assert exc.value.status == 400
    assert exc.value.errors and exc.value.errors[0].field == "value"


def test_bounded_settings_exist_in_the_registry() -> None:
    assert set(services.INT_BOUNDS) <= set(DEFS)
    assert all(DEFS[k].type == "integer" for k in services.INT_BOUNDS)
    assert set(services.BRANDING_KEYS.values()) | set(services.LEGAL_KEYS.values()) <= set(DEFS)


def test_not_found_and_invalid_problem_shapes() -> None:
    assert services.not_found("setting").status == 404
    assert services.invalid("f", "m", status=422).slug == "validation"
