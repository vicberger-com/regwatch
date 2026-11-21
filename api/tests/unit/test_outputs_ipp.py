"""Network printing (M8.5b; CP-33): addresses, networks, the stack's own services, and the
send through ippx against a mock printer. No network: the printer is an httpx mock transport
and name lookups are replaced."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import ippx
import pytest

from regwatch.outputs import ipp

PDF = b"%PDF-1.7 test"
PRIVATE = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"]  # as an admin may set


class MockPrinter:
    """Answers IPP over httpx: records each request; accepts Print-Job with job id 42."""

    def __init__(self, status: int = 0, http: int = 200, body: bytes | None = None) -> None:
        self.status, self.http, self.body = status, http, body
        self.requests: list[ippx.IppMessage] = []
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        msg = ippx.decode(request.read())
        self.requests.append(msg)
        self.urls.append(str(request.url))
        if self.body is not None:
            return httpx.Response(self.http, content=self.body)
        answer = ippx.IppMessage((2, 0), self.status, msg.request_id, [
            (ippx.Tag.OPERATION_ATTRS, [
                ippx.Attribute("attributes-charset", ippx.Tag.CHARSET, ["utf-8"]),
                ippx.Attribute("attributes-natural-language", ippx.Tag.NATURAL_LANGUAGE,
                               ["en"])]),
            (ippx.Tag.JOB_ATTRS, [ippx.Attribute("job-id", ippx.Tag.INTEGER, [42]),
                                  ippx.Attribute("job-state", ippx.Tag.ENUM, [3])]),
        ])  # fmt: skip
        return httpx.Response(self.http, content=ippx.encode(answer))


@pytest.fixture
def printer(monkeypatch: pytest.MonkeyPatch) -> MockPrinter:
    fake = MockPrinter()
    monkeypatch.setattr(ipp, "transport_factory", lambda verify: httpx.MockTransport(fake))
    return fake


def _names(table: dict[str, set[str]]) -> Callable[[str], object]:
    async def lookup(host: str) -> set[str]:
        return table.get(host, set())

    return lookup


@pytest.fixture(autouse=True)
def own(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The worker's own networks, as /proc/net/route would give them in the stack."""
    nets = ["10.90.0.0/24", "10.90.0.1/32"]
    monkeypatch.setattr(ipp, "own_networks", lambda: ipp.networks_of(nets))
    return nets


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[str]]:
    table = {"printer.example.internal": {"10.20.0.7"}, "db": {"10.90.0.3"}}
    monkeypatch.setattr(ipp, "lookup", _names(table))
    return table


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://printer.example.internal/ipp/print", "ipps:// address"),
        ("ipp://printer.example.internal/ipp/print", "clear-text"),
        ("ipps://admin:pw@printer.example.internal/ipp/print", "no user name"),
        ("ipps://printer.example.internal/ipp/print?x=1", "no user name"),
        ("ipps://db:5432/", "own services"),
        ("ipps://localhost/ipp/print", "own services"),
        ("ipps://ippeveprinter/ipp/print", "own services"),
        ("ipps://printer.example.internal:99999/", "a port"),
        ("ipps://printer.example.internal:8080/", "port 631"),  # another service's port
        ("ipps://10.20.0.7:22/", "port 631"),
        ("ipps://printer\n.example.internal/", "one line"),
    ],
)
def test_addresses_are_refused(url: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ipp.parse(url, allow_plain=False)


def test_a_good_address_and_its_defaults() -> None:
    target = ipp.parse("ipps://Printer.Example.Internal/", allow_plain=False)
    assert target.url() == "ipps://printer.example.internal:631/"
    assert ipp.parse("ipps://printer.example.internal", allow_plain=False).path == "/ipp/print"
    assert ipp.parse("ipp://printer.example.internal/", allow_plain=True).scheme == "ipp"
    assert ipp.parse("ipps://ippeveprinter/", allow_plain=False, allow_test_printer=True)


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("10.20.0.7", True),
        ("192.168.1.20", True),
        ("8.8.8.8", False),  # public
        ("127.0.0.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("::ffff:10.20.0.7", True),
        ("fd00::5", True),
        ("0.0.0.0", False),  # noqa: S104 - an address checked, not a bind
        ("224.0.0.1", False),
    ],
)
def test_only_the_allowed_networks(address: str, ok: bool) -> None:
    assert ipp.allowed(address, ipp.networks_of(PRIVATE)) is ok


async def test_a_name_must_resolve_entirely_inside_and_never_to_the_stack(
    dns: dict[str, set[str]],
) -> None:
    nets = ipp.networks_of(PRIVATE)
    target = ipp.parse("ipps://printer.example.internal/", allow_plain=False)
    assert await ipp.resolve(target, nets) == "10.20.0.7"
    dns["printer.example.internal"] = {"10.20.0.7", "8.8.8.8"}  # one answer outside
    with pytest.raises(ipp.PrinterError) as outside:
        await ipp.resolve(target, nets)
    assert outside.value.error_class == "printer-address-refused"
    dns["printer.example.internal"] = {"10.90.0.3"}  # the database's address
    with pytest.raises(ipp.PrinterError):
        await ipp.resolve(target, nets)
    by_ip = ipp.parse("ipps://10.90.0.3/", allow_plain=False)
    with pytest.raises(ipp.PrinterError):
        await ipp.resolve(by_ip, nets)
    for inside in ("10.90.0.77", "10.90.0.1"):  # the worker's own subnet and its gateway
        with pytest.raises(ipp.PrinterError):
            await ipp.resolve(ipp.parse(f"ipps://{inside}/", allow_plain=False), nets)
    with pytest.raises(ipp.PrinterError, match="no printer networks"):
        await ipp.resolve(ipp.parse("ipps://10.20.0.7/", allow_plain=False), [])  # the default
    del dns["printer.example.internal"]
    with pytest.raises(ipp.PrinterError) as missing:
        await ipp.resolve(target, nets)
    assert missing.value.error_class == "printer-not-found"


async def _send(**over: object) -> int:
    args: dict[str, object] = {"ipp_url": "ipps://printer.example.internal/ipp/print",
                               "tls_sha256": None, "pdf": PDF, "job_name": "regwatch-x.pdf",
                               "copies": 2, "media": "iso_a4_210x297mm", "networks": PRIVATE,
                               "allow_plain": False}  # fmt: skip
    args.update(over)
    return await ipp.send(**args)  # type: ignore[arg-type]


async def test_a_pdf_is_printed_with_its_copies_and_media(printer: MockPrinter) -> None:
    assert await _send() == 42
    msg = printer.requests[0]
    assert msg.code == ippx.Operation.PRINT_JOB and msg.data == PDF
    attrs = {a.name: a.values for _, group in msg.groups for a in group}
    assert attrs["copies"] == [2] and attrs["media"] == ["iso_a4_210x297mm"]
    assert attrs["document-format"] == ["application/pdf"]
    assert attrs["requesting-user-name"] == ["regwatch"]  # not the user's address
    assert printer.urls == ["https://printer.example.internal:631/ipp/print"]  # the name, TLS


async def test_clear_text_goes_to_the_checked_address(printer: MockPrinter) -> None:
    await _send(ipp_url="ipp://printer.example.internal/ipp/print", allow_plain=True)
    assert printer.urls == ["http://10.20.0.7:631/ipp/print"]  # no second lookup to rebind


async def test_refusals_and_failures_have_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    for fake, error_class in [
        (MockPrinter(status=0x0400), "printer-refused"),  # client-error-bad-request
        (MockPrinter(http=503, body=b""), "printer-unavailable"),
        (MockPrinter(body=b"\x02\x00" + b"x" * (ipp.MAX_ANSWER + 10)), "printer-answer-too-large"),
    ]:
        monkeypatch.setattr(ipp, "transport_factory", lambda verify, f=fake: httpx.MockTransport(f))
        with pytest.raises(ipp.PrinterError) as failed:
            await _send()
        assert failed.value.error_class == error_class
    with pytest.raises(ipp.PrinterError) as refused:
        await _send(ipp_url="ipps://db/")
    assert refused.value.error_class == "printer-address-refused"


def test_tls_keeps_the_full_default_policy() -> None:
    assert ipp.CIPHERS == "DEFAULT:@SECLEVEL=2"
    pinned = ipp._tls("ab" * 32)  # noqa: SLF001
    assert pinned.fingerprint == "ab" * 32 and pinned.ciphers == ipp.CIPHERS


ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t01005A0A\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t00005A0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
"""
ROUTE6 = (
    "fd000000000000000000000000000000 40 00000000000000000000000000000000 00 "
    "00000000000000000000000000000000 00000100 00000001 00000000 00000001 eth0\n"
    "00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
    "fd000000000000000000000000000001 00000400 00000001 00000000 00000003 eth0\n"
)


def test_the_workers_own_networks_come_from_its_routes() -> None:
    assert [str(n) for n in ipp._routes_v4(ROUTE)] == ["10.90.0.1/32", "10.90.0.0/24"]  # noqa: SLF001
    assert [str(n) for n in ipp._routes_v6(ROUTE6)] == ["fd00::/64", "fd00::1/128"]  # noqa: SLF001


def test_without_its_own_networks_nothing_is_printed(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
) -> None:
    import builtins

    from regwatch.core.settings import get_settings

    monkeypatch.undo()  # the real own_networks
    for key, value in valid_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("REGWATCH_STACK_NETWORKS", raising=False)
    get_settings.cache_clear()
    real_open = builtins.open

    def no_proc(path: object, *args: object, **kwargs: object) -> object:
        if str(path).startswith("/proc/net/"):
            raise FileNotFoundError(path)
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "open", no_proc)
    with pytest.raises(ipp.PrinterError) as unknown:
        ipp.own_networks()
    assert unknown.value.error_class == "stack-unknown"


def test_the_stack_networks_can_be_given(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
                                         ) -> None:  # fmt: skip
    from regwatch.core.settings import get_settings

    monkeypatch.undo()
    for key, value in valid_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("REGWATCH_STACK_NETWORKS", '["10.89.0.0/24"]')
    get_settings.cache_clear()
    assert [str(n) for n in ipp.own_networks()] == ["10.89.0.0/24"]
    get_settings.cache_clear()


async def test_a_printer_that_answers_slowly_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import anyio

    async def slow(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(5)
        return httpx.Response(200)

    monkeypatch.setattr(ipp, "TOTAL_S", 0.2)
    monkeypatch.setattr(ipp, "transport_factory", lambda verify: httpx.MockTransport(slow))
    with pytest.raises(ipp.PrinterError) as failed:
        await _send()
    assert failed.value.error_class == "printer-unavailable"


def test_ippx_is_the_reviewed_version() -> None:
    """``send`` replaces ippx's private ``_http`` client, which 0.1.1 uses for every request
    and closes on exit (review of 182bf1c): an upgrade must re-check that, so it fails here."""
    import inspect
    from importlib.metadata import version

    assert version("ippx") == "0.1.1"
    source = inspect.getsource(ippx.AsyncIppClient)
    assert "self._http.post(self._http_url" in source and "self._http.aclose()" in source
