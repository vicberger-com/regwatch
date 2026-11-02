"""Schemathesis CLI hooks for the CI `contract` job (SCHEMATHESIS_HOOKS=tests.schemathesis_hooks).

While handlers are 501 stubs (#30), two default checks cannot hold: ``not_a_server_error`` is
replaced by ``no_unexpected_server_error`` below, which fails any 5xx except a documented 501.
``positive_data_acceptance`` (valid input must get a 2xx) returns when modules implement routes.
"""

from __future__ import annotations

from typing import Any

import schemathesis


@schemathesis.check
def no_unexpected_server_error(ctx: Any, response: Any, case: Any) -> bool | None:
    status = response.status_code
    documented = str(status) in case.operation.definition.raw.get("responses", {})
    if status >= 500 and not (status == 501 and documented):
        raise AssertionError(f"unexpected {status} from {case.method} {case.path}")
    return None
