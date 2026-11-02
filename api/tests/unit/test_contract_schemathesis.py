"""Schemathesis against the stub API in process (issue #30): zero schema violations.

Every documented operation is fuzzed and its responses checked against the live document,
which ``test_contract_routes`` holds semantically equal to openapi/regwatch.v1.yaml. Two
default checks cannot hold while handlers are stubs and are replaced, not dropped:
``not_a_server_error`` (a stub answers 501 by design) becomes ``no_unexpected_server_error``
(any 5xx other than a documented 501 fails), and ``positive_data_acceptance`` (valid input
must get 2xx) returns when each module implements its routes.
"""

from __future__ import annotations

from typing import Any

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error, positive_data_acceptance

from regwatch.api.app import create_app
from regwatch.core.settings import Settings

from ..conftest import VALID_ENV

APP = create_app(Settings(**{k.removeprefix("REGWATCH_").lower(): v for k, v in VALID_ENV.items()}))
schema = schemathesis.openapi.from_asgi("/api/v1/openapi.json", APP)


def no_unexpected_server_error(ctx: Any, response: Any, case: Any) -> bool:
    status = response.status_code
    documented = str(status) in case.operation.definition.raw.get("responses", {})
    assert status < 500 or (status == 501 and documented), f"unexpected {status} from {case.path}"
    return True


@schema.parametrize()
@settings(max_examples=8, deadline=None, suppress_health_check=list(HealthCheck))
def test_stub_api_conforms(case: schemathesis.Case) -> None:
    case.call_and_validate(
        excluded_checks=[not_a_server_error, positive_data_acceptance],
        additional_checks=[no_unexpected_server_error],
    )
