"""The proxy's Compose address and the trusted-proxy settings agree (BL-73, review finding 5)."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))


def _proxy_address() -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(
        COMPOSE["services"]["proxy"]["networks"]["regwatch"]["ipv4_address"]
    )


def _networks(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(part.strip()) for part in value.split(",") if part.strip()]


def test_proxy_address_is_inside_the_pinned_subnet() -> None:
    subnet = COMPOSE["networks"]["regwatch"]["ipam"]["config"][0]["subnet"]
    assert _proxy_address() in ipaddress.ip_network(subnet)


def test_dev_env_trusts_exactly_the_proxy() -> None:
    script = (ROOT / "scripts" / "dev-env.sh").read_text(encoding="utf-8")
    value = re.search(
        r"REGWATCH_TRUSTED_PROXIES=([^|\"]+)\|", script.split("TRUSTED_PROXIES=.*|")[1]
    )
    assert value is not None
    nets = _networks(value.group(1))
    assert nets == [ipaddress.ip_network(f"{_proxy_address()}/32")]


def test_contract_and_code_defaults_are_exactly_the_proxy() -> None:
    lines = (ROOT / "docs" / "contracts" / "env.example").read_text().splitlines()
    line = next(line for line in lines if line.startswith("REGWATCH_TRUSTED_PROXIES="))
    default = line.split("=", 1)[1].split("#", 1)[0]
    assert _networks(default) == [ipaddress.ip_network(f"{_proxy_address()}/32")]
    from regwatch.core.settings import Settings

    assert Settings.model_fields["trusted_proxies"].default == tuple(_networks(default))


def test_dynamic_addresses_cannot_take_the_proxy_address() -> None:
    ipam = COMPOSE["networks"]["regwatch"]["ipam"]["config"][0]
    dynamic = ipaddress.ip_network(ipam["ip_range"])
    assert dynamic.subnet_of(ipaddress.ip_network(ipam["subnet"]))  # type: ignore[arg-type]
    assert _proxy_address() not in dynamic
    pinned = [svc["networks"]["regwatch"]["ipv4_address"] for svc in COMPOSE["services"].values()
              if isinstance(svc.get("networks"), dict) and "regwatch" in svc["networks"]
              and (svc["networks"]["regwatch"] or {}).get("ipv4_address")]  # fmt: skip
    assert pinned == [str(_proxy_address())]


def test_published_ports_are_loopback_only() -> None:
    for name, service in COMPOSE["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


async def test_uvicorn_takes_the_client_address_only_from_the_proxy() -> None:
    """``regwatch-api`` passes REGWATCH_TRUSTED_PROXIES to uvicorn as forwarded_allow_ips."""
    from starlette.types import Receive, Scope, Send
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["client"][0])

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=f"{_proxy_address()}/32")
    for peer in (str(_proxy_address()), "10.89.0.3"):
        scope = {"type": "http", "scheme": "http", "client": (peer, 5000),
                 "headers": [(b"x-forwarded-for", b"203.0.113.7")]}  # fmt: skip
        await wrapped(scope, None, None)  # type: ignore[arg-type]
    assert seen == ["203.0.113.7", "10.89.0.3"]
