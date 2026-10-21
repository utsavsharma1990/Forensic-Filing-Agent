"""Shared pytest fixtures for forensic-filing-agent.

* Network tests (``@pytest.mark.network``) hit real SEC EDGAR; they are skipped automatically when
  www.sec.gov is unreachable. Live downloads are cached under ``.cache/`` so reruns are fast.
* Offline tests build an :class:`EdgarClient` over ``httpx.MockTransport`` with a temp cache dir.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Callable

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import edgar_api  # noqa: E402


def _sec_reachable() -> bool:
    try:
        with socket.create_connection(("www.sec.gov", 443), timeout=5):
            return True
    except OSError:
        return False


_REACHABLE: dict[str, bool] = {}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``network`` tests when SEC is unreachable (evaluated lazily, once)."""
    net_items = [i for i in items if i.get_closest_marker("network")]
    if not net_items:
        return
    if "ok" not in _REACHABLE:
        _REACHABLE["ok"] = _sec_reachable()
    if not _REACHABLE["ok"]:
        skip = pytest.mark.skip(reason="www.sec.gov unreachable")
        for item in net_items:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _reset_edgar_singleton():
    """Every test starts and ends with no cached EdgarClient singleton."""
    edgar_api.set_client(None)
    yield
    edgar_api.set_client(None)


class MockSec:
    """Routes URL substrings to canned responses and counts requests."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, Callable[[httpx.Request], httpx.Response]]] = []
        self.requests: list[httpx.Request] = []

    def add(self, fragment: str, handler: Callable[[httpx.Request], httpx.Response] | httpx.Response | dict | str | bytes,
            status: int = 200, headers: dict | None = None) -> None:
        if callable(handler):
            fn = handler
        elif isinstance(handler, httpx.Response):
            fn = lambda req, r=handler: r  # noqa: E731
        elif isinstance(handler, dict):
            fn = lambda req, d=handler: httpx.Response(status, json=d, headers=headers)  # noqa: E731
        elif isinstance(handler, bytes):
            fn = lambda req, b=handler: httpx.Response(status, content=b, headers=headers)  # noqa: E731
        else:
            fn = lambda req, t=handler: httpx.Response(status, content=t.encode("utf-8"), headers=headers)  # noqa: E731
        self.routes.append((fragment, fn))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for frag, fn in self.routes:
            if frag in str(request.url):
                return fn(request)
        return httpx.Response(404, text="not found")


@pytest.fixture
def mock_sec() -> MockSec:
    return MockSec()


@pytest.fixture
def make_client(tmp_path, mock_sec):
    """Factory for an EdgarClient wired to ``mock_sec`` with a temp cache and a recording (non-sleeping) sleep."""
    sleeps: list[float] = []

    def _make(max_rps: float = 1000.0, sleep=None, user_agent: str | None = None) -> edgar_api.EdgarClient:
        c = edgar_api.EdgarClient(cache_dir=tmp_path / "edgar", transport=httpx.MockTransport(mock_sec),
                                  sleep=sleep or sleeps.append, max_rps=max_rps, user_agent=user_agent)
        edgar_api.set_client(c)
        return c

    _make.sleeps = sleeps  # type: ignore[attr-defined]
    return _make
