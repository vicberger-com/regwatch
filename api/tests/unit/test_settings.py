from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from regwatch.core.settings import Settings

ENV_EXAMPLE = Path(__file__).parents[3] / "docs" / "contracts" / "env.example"
REQUIRED = ["SECRET_KEY", "DATABASE_URL", "QUEUE_URL", "BASE_URL"]


def contract_variables() -> list[str]:
    names = re.findall(r"^REGWATCH_([A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), flags=re.M)
    assert names, "env.example not found or empty"
    return names


def test_every_contract_variable_has_a_field() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    missing = sorted(set(contract_variables()) - fields)
    extra = sorted(fields - set(contract_variables()))
    assert missing == [] and extra == []


def test_valid_environment_loads(valid_env: dict[str, str]) -> None:
    s = Settings()
    assert s.secret_key.get_secret_value() == "a" * 64
    assert str(s.base_url) == "http://localhost/"
    assert s.env == "development"
    assert s.object_store_path == "/data/objectstore"
    assert s.trusted_proxies == (ipaddress.ip_network("10.89.0.2/32"),)
    assert s.session_cookie_name == "rw_session"
    assert s.smtp_port == 1025 and s.smtp_starttls is False
    assert str(s.pdf_url) == "http://pdf:3000/"
    assert s.metrics_enabled is True


@pytest.mark.parametrize("name", REQUIRED)
def test_missing_required_variable_fails_fast(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(f"REGWATCH_{name}")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert exc.value.errors()[0]["loc"] == (name.lower(),)
    assert exc.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize("name", REQUIRED)
def test_empty_required_variable_counts_as_missing(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(f"REGWATCH_{name}", "")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SECRET_KEY", "short"),
        ("SECRET_KEY", "z" * 64),
        ("SECRET_KEY_PREVIOUS", "abc"),
        ("DATABASE_URL", "mysql://x@db/regwatch"),
        ("QUEUE_URL", "amqp://queue"),
        ("BASE_URL", "not a url"),
        ("ENV", "staging"),
        ("LOG_LEVEL", "TRACE"),
        ("TRUSTED_PROXIES", "10.0.0.1/8"),
        ("SMTP_PORT", "70000"),
        ("SESSION_COOKIE_NAME", "bad name;"),
    ],
)
def test_invalid_values_are_rejected(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(f"REGWATCH_{name}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_optional_values_parse(valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REGWATCH_TRUSTED_PROXIES", "172.16.0.0/12, fd00::/8")
    monkeypatch.setenv("REGWATCH_SMTP_STARTTLS", "true")
    monkeypatch.setenv("REGWATCH_ENV", "production")
    monkeypatch.setenv("REGWATCH_SMTP_USERNAME", "")
    monkeypatch.setenv("REGWATCH_SECRET_KEY_PREVIOUS", "b" * 64)
    s = Settings()
    assert s.trusted_proxies == (
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("fd00::/8"),
    )
    assert s.smtp_starttls is True
    assert s.env == "production"
    assert s.smtp_username is None
    assert s.secret_key_previous is not None


def test_secrets_are_not_shown_in_repr(valid_env: dict[str, str]) -> None:
    text = repr(Settings())
    assert "a" * 64 not in text
    assert "pw@" not in text
