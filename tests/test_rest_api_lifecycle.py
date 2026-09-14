"""REST server start/stop reports actual thread lifecycle state."""
import sys
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import requests

pytest.importorskip("fastapi")

from core.rest_api import RestAPIServer


class FakeConfig:
    def __init__(self, app, **kwargs):
        self.app = app
        self.kwargs = kwargs


class FakeServer:
    instances = []

    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.exited = threading.Event()
        self.__class__.instances.append(self)

    def run(self):
        self.started = True
        while not self.should_exit:
            time.sleep(0.001)
        self.exited.set()


@pytest.fixture
def fake_uvicorn(monkeypatch):
    FakeServer.instances.clear()
    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(Config=FakeConfig, Server=FakeServer)
    )
    return FakeServer


def test_start_waits_until_ready_and_duplicate_start_reuses_thread(fake_uvicorn):
    server = RestAPIServer(lambda: SimpleNamespace(), port=18765)
    assert server.start(timeout=1.0) is True
    thread = server._thread
    assert server.is_running
    assert server.start(timeout=1.0) is False
    assert server._thread is thread
    assert len(fake_uvicorn.instances) == 1
    assert server.stop(timeout=1.0) is True


def test_stop_returns_only_after_thread_exits_and_is_idempotent(fake_uvicorn):
    server = RestAPIServer(lambda: SimpleNamespace(), port=18766)
    server.start(timeout=1.0)
    running = fake_uvicorn.instances[-1]
    assert server.stop(timeout=1.0) is True
    assert running.exited.is_set()
    assert server._thread is None and server._server is None
    assert server.stop(timeout=1.0) is True


def test_stop_then_immediate_restart_creates_fresh_server(fake_uvicorn):
    server = RestAPIServer(lambda: SimpleNamespace(), port=18767)
    server.start(timeout=1.0)
    server.stop(timeout=1.0)
    assert server.start(timeout=1.0) is True
    assert len(fake_uvicorn.instances) == 2
    server.stop(timeout=1.0)


def test_start_failure_keeps_server_stopped(monkeypatch):
    class FailingServer(FakeServer):
        def run(self):
            raise OSError("address already in use")

    monkeypatch.setitem(
        sys.modules, "uvicorn",
        SimpleNamespace(Config=FakeConfig, Server=FailingServer),
    )
    server = RestAPIServer(lambda: SimpleNamespace(), port=18768)
    with pytest.raises(RuntimeError, match="address already in use"):
        server.start(timeout=1.0)
    assert not server.is_running
    assert server._thread is None and server._server is None


def test_stop_timeout_preserves_live_references(monkeypatch):
    class StuckServer(FakeServer):
        def run(self):
            self.started = True
            time.sleep(0.2)

    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(Config=FakeConfig, Server=StuckServer)
    )
    server = RestAPIServer(lambda: SimpleNamespace(), port=18769)
    server.start(timeout=1.0)
    with pytest.raises(TimeoutError, match="did not stop"):
        server.stop(timeout=0.001)
    assert server._thread is not None and server._server is not None
    server._thread.join(1.0)
    server.stop(timeout=1.0)


def test_real_server_responds_and_rebinds_same_port_after_stop():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = RestAPIServer(lambda: SimpleNamespace(), port=port)
    try:
        assert server.start(timeout=3.0)
        response = requests.get(f"http://127.0.0.1:{port}/", timeout=2.0)
        assert response.status_code == 200
        assert server.stop(timeout=3.0)
        assert server.start(timeout=3.0)
        assert requests.get(f"http://127.0.0.1:{port}/", timeout=2.0).status_code == 200
    finally:
        server.stop(timeout=3.0)


def test_occupied_port_fails_before_thread_and_keeps_stopped():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        server = RestAPIServer(lambda: SimpleNamespace(), port=port)
        with pytest.raises(OSError, match="unavailable"):
            server.start(timeout=1.0)
    assert server._thread is None and server._server is None
