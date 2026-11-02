"""Pytest fixtures for the fixture server (issue #12). Registered in ``tests/conftest.py``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.support.fixture_server import FixtureServer


@pytest.fixture(scope="session")
def fixture_server_session() -> Iterator[FixtureServer]:
    with FixtureServer() as server:
        yield server


@pytest.fixture
def fixture_server(fixture_server_session: FixtureServer) -> FixtureServer:
    """The shared fixture server, with robots, sequences and the request log reset."""
    fixture_server_session.reset()
    return fixture_server_session
