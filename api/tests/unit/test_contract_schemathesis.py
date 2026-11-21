"""Schemathesis against the API in process (issues #30, #31): zero schema violations.

Every documented operation is fuzzed and its responses checked against the live document,
which ``test_contract_routes`` holds semantically equal to openapi/regwatch.v1.yaml. Two
default checks cannot hold while handlers are stubs and are replaced, not dropped:
``not_a_server_error`` (a stub answers 501 by design) becomes ``no_unexpected_server_error``
(any 5xx other than a documented 501 fails), and ``positive_data_acceptance`` (valid input
must get 2xx) returns when each module implements its routes.

``test_gated_api_conforms`` runs with the real session gate (cookies dropped, so 401, 403 or the
public routes' own answers). The pass that fuzzed stubs without the gate is retired: since
M8.5b no route is a stub (``test_no_stub_routes_remain``). Implemented routes need a database
and are left to the CI contract job and the integration tests.
"""

from __future__ import annotations

from typing import Any

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error, positive_data_acceptance
from schemathesis.config._checks import (
    NEGATIVE_DATA_REJECTION_EXPECTED_STATUSES,
    NegativeDataRejectionConfig,
)

from regwatch.api.app import create_app
from regwatch.core.settings import Settings
from regwatch.identity.permissions import authorize

from ..conftest import VALID_ENV


def _app(gated: bool) -> Any:
    app = create_app(
        Settings(**{k.removeprefix("REGWATCH_").lower(): v for k, v in VALID_ENV.items()})
    )
    if not gated:
        app.dependency_overrides[authorize] = lambda: None
    return app


# Public routes that read the database, which unit tests do not have; their integration tests
# cover them (/branding/logo: tests/integration/test_logo.py; /branding/public and /legal:
# tests/integration/test_admin.py).
gated = (
    schemathesis.openapi.from_asgi("/api/v1/openapi.json", _app(gated=True))
    .exclude(path="/health")
    .exclude(path="/ready")  # reads the database: tests/integration/test_ready.py
    .exclude(path="/branding/logo")
    .exclude(path="/branding/public")
    .exclude(path="/legal")
)


# A fuzzed body over the 2 MB cap is refused with 413 before anything reads it, which is a
# correct rejection of invalid data; schemathesis's default list for that check omits 413.
for _schema in (gated,):
    _schema.config.checks.negative_data_rejection = NegativeDataRejectionConfig(
        expected_statuses=[*NEGATIVE_DATA_REJECTION_EXPECTED_STATUSES, "413"]
    )


def no_unexpected_server_error(ctx: Any, response: Any, case: Any) -> bool:
    status = response.status_code
    documented = str(status) in case.operation.definition.raw.get("responses", {})
    assert status < 500 or (status == 501 and documented), f"unexpected {status} from {case.path}"
    return True


def _validate(case: schemathesis.Case) -> None:
    case.call_and_validate(
        excluded_checks=[not_a_server_error, positive_data_acceptance],
        additional_checks=[no_unexpected_server_error],
    )


@gated.parametrize()
@settings(max_examples=4, deadline=None, suppress_health_check=list(HealthCheck))
def test_gated_api_conforms(case: schemathesis.Case) -> None:
    case.cookies = {}  # a fuzzed rw_session would be looked up in a database
    _validate(case)
    if case.operation.definition.raw.get("security") != []:
        # 413: a fuzzed body over the 2 MB cap is refused before the gate, as it should be.
        assert case.call().status_code in {401, 403, 405, 413, 422}


def test_no_stub_routes_remain() -> None:
    """M8.5b implemented the printer routes, the last stubs: every documented operation has a
    real handler, fuzzed behind the gate here and through a database by the CI contract job
    and the integration tests. The stub pass that fuzzed them without the gate is retired."""
    document = _app(gated=True).openapi()
    stubs = [f"{method.upper()} {path}" for path, item in document["paths"].items()
             for method, operation in item.items()
             if isinstance(operation, dict)
             and "501" in operation.get("responses", {})]  # fmt: skip
    assert stubs == []


def test_a_body_over_the_cap_counts_as_rejected() -> None:
    """The 413 allowance above reaches the negative-data check (it lives in a private
    schemathesis module, so an upgrade that moves it fails here, not by chance in a fuzz run)."""
    for schema in (gated,):
        statuses = schema.config.checks.negative_data_rejection.expected_statuses
        assert "413" in statuses and "422" in statuses
