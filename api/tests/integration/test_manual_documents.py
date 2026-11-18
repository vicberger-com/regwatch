"""``POST /sources/{id}/documents`` (CP-17): a manual source's document, by URL or by file."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from regwatch.capture import manual, services
from regwatch.core import objectstore
from tests.integration.test_admin import _api, _as_new_user, admin
from tests.integration.test_auth import ORIGIN, clear_limits, db_url
from tests.integration.test_capture_runs import Queue, queue
from tests.integration.test_sources import rss

pytestmark = pytest.mark.integration
__all__ = ["admin", "clear_limits", "db_url", "queue"]  # shared fixtures

PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    async def put(key: str, data: bytes) -> None:
        objects[key] = data

    monkeypatch.setattr(objectstore, "put", put)
    return objects


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.5"] if host == "inside.example" else ["93.184.215.14"]

    monkeypatch.setattr(services, "RESOLVER", resolve)


async def _manual(admin: httpx.AsyncClient) -> str:
    made = await admin.post(_api("/sources"), json={"name": "Uploads", "kind": "manual",
                                                    "config": {}})  # fmt: skip
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_a_url_is_recorded_for_a_worker(admin: httpx.AsyncClient, queue: Queue,
                                              stored: dict[str, bytes]) -> None:  # fmt: skip
    sid = await _manual(admin)
    got = await admin.post(_api(f"/sources/{sid}/documents"),
                           json={"url": "https://reg.example/act", "title": "The Act"})  # fmt: skip
    assert got.status_code == 202, got.text
    run_id = got.json()["run_id"]
    request = json.loads(stored[manual.request_key(sid, run_id)])
    assert request == {"kind": "url", "url": "https://reg.example/act", "title": "The Act"}
    assert len(queue.sent) == 1  # handed over like "Run now"
    busy = await admin.post(
        _api(f"/sources/{sid}/documents"), json={"url": "https://reg.example/b"}
    )
    assert busy.status_code == 409  # one run at a time
    audit = await admin.get(_api("/admin/audit"), params={"action": "source.document_added"})
    assert audit.status_code == 200 and audit.json()["items"][0]["after"]["run_id"] == run_id


async def test_a_file_is_checked_by_its_content_and_stored(
    admin: httpx.AsyncClient, queue: Queue, stored: dict[str, bytes]
) -> None:
    sid = await _manual(admin)
    got = await admin.post(_api(f"/sources/{sid}/documents"),
                           files={"file": ("x.txt", PDF, "text/plain")},
                           data={"title": "Guidance"})  # fmt: skip
    assert got.status_code == 202, got.text
    request = json.loads(stored[manual.request_key(sid, got.json()["run_id"])])
    assert request["mime"] == "application/pdf"  # by the bytes, not the name or declared type
    assert stored[request["body_ref"]] == PDF and request["title"] == "Guidance"


@pytest.mark.parametrize(
    ("body", "status"),
    [({"files": {"file": ("a.bin", b"\x00\x01\x02binary", "application/octet-stream")}}, 415),
     ({"files": {"file": ("a.txt", b"\xff\xfe not utf-8", "text/plain")}}, 415),
     ({"files": {"file": ("a.txt", b"", "text/plain")}}, 422),
     ({"files": {"file": ("big.txt", b"x" * (manual.MAX_FILE_BYTES + 1), "text/plain")}}, 413),
     ({"json": {"url": "https://inside.example/x"}}, 422),
     ({"json": {"url": "file:///etc/passwd"}}, 422),
     ({"json": {"url": "https://reg.example/", "extra": 1}}, 422),
     ({"json": {"url": "https://reg.example/", "title": "x" * 501}}, 422),
     ({"content": b"url=https://reg.example/",
       "headers": {"content-type": "application/x-www-form-urlencoded"}}, 415)],
)  # fmt: skip
async def test_bad_documents_are_refused(admin: httpx.AsyncClient, queue: Queue,
                                         stored: dict[str, bytes], body: dict[str, Any],
                                         status: int) -> None:  # fmt: skip
    sid = await _manual(admin)
    got = await admin.post(_api(f"/sources/{sid}/documents"), **body)
    assert got.status_code == status, got.text
    assert stored == {} and queue.sent == []  # nothing stored, nothing queued


async def test_only_manual_sources_and_only_admins(admin: httpx.AsyncClient, queue: Queue,
                                                   stored: dict[str, bytes]) -> None:  # fmt: skip
    feed = (await admin.post(_api("/sources"), json=rss())).json()["id"]
    not_manual = await admin.post(_api(f"/sources/{feed}/documents"),
                                  json={"url": "https://reg.example/"})  # fmt: skip
    assert not_manual.status_code == 409
    missing = await admin.post(_api(f"/sources/{uuid.uuid4()}/documents"),
                               json={"url": "https://reg.example/"})  # fmt: skip
    assert missing.status_code == 404
    sid = await _manual(admin)
    viewer = await _as_new_user(admin, f"viewer-{uuid.uuid4().hex[:8]}@example.org", ["viewer"])
    refused = await viewer.post(_api(f"/sources/{sid}/documents"),
                                json={"url": "https://reg.example/"})  # fmt: skip
    await viewer.aclose()
    assert refused.status_code == 403
    anonymous = httpx.AsyncClient(transport=admin._transport, base_url="https://localhost",
                                  headers=ORIGIN)  # fmt: skip
    async with anonymous:
        nobody = await anonymous.post(_api(f"/sources/{sid}/documents"),
                                      json={"url": "https://reg.example/"})  # fmt: skip
        assert nobody.status_code == 401
    assert stored == {}


async def test_the_body_cap_is_larger_only_on_this_route(
    admin: httpx.AsyncClient, queue: Queue, stored: dict[str, bytes]
) -> None:
    sid = await _manual(admin)
    three_mb = b"x" * (3 * 1024 * 1024)
    upload = await admin.post(_api(f"/sources/{sid}/documents"),
                              files={"file": ("a.txt", three_mb, "text/plain")})  # fmt: skip
    assert upload.status_code != 413  # within this route's cap
    elsewhere = await admin.post(_api("/sources"), content=three_mb,
                                 headers={"content-type": "application/json"})  # fmt: skip
    assert elsewhere.status_code == 413
