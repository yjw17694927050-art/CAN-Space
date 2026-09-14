"""Behavioral tests for central CAN ownership and receive distribution."""
from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from core import can_service
from core.safety import set_armed


class RawBus:
    """Thread-aware Bus double with externally queued receive frames."""

    def __init__(self):
        self.incoming = queue.Queue()
        self.sent = []
        self.recv_thread_ids = set()
        self.shutdown_called = False
        self.shutdown_saw_receiver_stopped = False
        self.receiver_stopped = threading.Event()

    def send(self, message, timeout=None):
        self.sent.append(message)

    def recv(self, timeout=0.05):
        self.recv_thread_ids.add(threading.get_ident())
        try:
            return self.incoming.get(timeout=min(timeout, 0.02))
        except queue.Empty:
            return None

    def shutdown(self):
        self.shutdown_called = True
        self.shutdown_saw_receiver_stopped = self.receiver_stopped.is_set()


def frame(arbitration_id: int, data: bytes = b"\x00"):
    return SimpleNamespace(arbitration_id=arbitration_id, data=data)


def new_coordinator(raw, **kwargs):
    cls = getattr(can_service, "CanCoordinator", None)
    assert cls is not None, "central CanCoordinator is not implemented"
    coordinator = cls(bus=raw, **kwargs)
    coordinator.start()
    assert coordinator.wait_started(0.5)
    return coordinator


@pytest.fixture(autouse=True)
def _reset_arm():
    set_armed(False)
    try:
        yield
    finally:
        set_armed(False)


def test_one_raw_receiver_fans_frame_to_capture_and_diagnostic():
    raw = RawBus()
    captured = []
    capture_ready = threading.Event()

    def capture(message):
        captured.append(message)
        capture_ready.set()

    coordinator = new_coordinator(raw, on_message=capture)
    subscription = coordinator.subscribe(arbitration_ids={0x7E8})
    message = frame(0x7E8, b"\x02\x50\x01")
    raw.incoming.put(message)

    assert subscription.recv(0.5) is message
    assert capture_ready.wait(0.5)
    assert captured == [message]
    assert coordinator.stop(0.5)


def test_unmatched_frame_reaches_capture_but_not_diagnostic():
    raw = RawBus()
    captured = []
    capture_ready = threading.Event()

    def capture(message):
        captured.append(message)
        capture_ready.set()

    coordinator = new_coordinator(raw, on_message=capture)
    subscription = coordinator.subscribe(arbitration_ids={0x7E8})
    message = frame(0x123, b"\xAA")
    raw.incoming.put(message)

    assert capture_ready.wait(0.5)
    assert captured == [message]
    assert subscription.recv(0.03) is None
    assert coordinator.stop(0.5)


def test_two_consumers_never_call_underlying_recv():
    raw = RawBus()
    coordinator = new_coordinator(raw)
    first = coordinator.subscribe(arbitration_ids={0x100})
    second = coordinator.subscribe(arbitration_ids={0x200})
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(first.recv(0.1))),
        threading.Thread(target=lambda: results.append(second.recv(0.1))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(0.5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(raw.recv_thread_ids) == 1
    assert next(iter(raw.recv_thread_ids)) not in {thread.ident for thread in threads}
    assert coordinator.stop(0.5)


def test_same_diagnostic_channel_transactions_do_not_cross_responses():
    """Concurrent ISO-TP calls sharing an RX ID must be serialized and drained."""
    from core.isotp import ISOTPSession

    class RespondingBus(RawBus):
        def send(self, message, timeout=None):
            super().send(message, timeout)
            marker = bytes(message.data)[2]
            delay = 0.03 if marker == 1 else 0.04
            response = frame(0x7E8, bytes([0x02, 0x62, marker, 0, 0, 0, 0, 0]))
            threading.Timer(delay, self.incoming.put, args=(response,)).start()

    raw = RespondingBus()
    coordinator = new_coordinator(raw)
    set_armed(True)
    first_bus = coordinator.endpoint({0x7E8}, transaction_key=(0x7E0, 0x7E8))
    second_bus = coordinator.endpoint({0x7E8}, transaction_key=(0x7E0, 0x7E8))
    sessions = [
        ISOTPSession(first_bus, 0x7E0, 0x7E8),
        ISOTPSession(second_bus, 0x7E0, 0x7E8),
    ]
    results = {}

    first = threading.Thread(target=lambda: results.setdefault(1, sessions[0].send(b"\x22\x01", 0.3)))
    second = threading.Thread(target=lambda: results.setdefault(2, sessions[1].send(b"\x22\x02", 0.3)))
    first.start()
    while not raw.sent:
        time.sleep(0.001)
    second.start()
    first.join(1.0)
    second.join(1.0)

    assert results == {1: b"\x62\x01", 2: b"\x62\x02"}
    first_bus.close()
    second_bus.close()
    assert coordinator.stop(0.5)


def test_subscription_timeout_does_not_stop_receive_dispatch():
    raw = RawBus()
    coordinator = new_coordinator(raw)
    subscription = coordinator.subscribe(arbitration_ids={0x7E8})

    assert subscription.recv(0.02) is None
    message = frame(0x7E8, b"\x01")
    raw.incoming.put(message)

    assert subscription.recv(0.5) is message
    assert coordinator.is_running
    assert coordinator.stop(0.5)


def test_stop_joins_receiver_before_shutting_down_bus():
    raw = RawBus()
    coordinator = new_coordinator(raw)
    receiver = coordinator._receiver_thread

    # The test Bus exposes this event solely to observe shutdown ordering.
    original_run = coordinator._receive_loop

    def observed_run():
        try:
            original_run()
        finally:
            raw.receiver_stopped.set()

    # Restart with the observed loop is not allowed; use the coordinator's
    # explicit stopped event as the Bus shutdown observation instead.
    del observed_run
    raw.receiver_stopped = coordinator._receiver_stopped

    assert coordinator.stop(0.5)
    assert not receiver.is_alive()
    assert raw.shutdown_called
    assert raw.shutdown_saw_receiver_stopped


def test_disarmed_coordinator_never_calls_underlying_send():
    raw = RawBus()
    coordinator = new_coordinator(raw)

    with pytest.raises(Exception) as caught:
        coordinator.send(frame(0x123))

    assert caught.type.__name__ == "BusNotArmedError"
    assert raw.sent == []
    assert coordinator.stop(0.5)


def test_stop_rejects_new_sends_before_waiting_for_receiver():
    class SlowBus(RawBus):
        def __init__(self):
            super().__init__()
            self.in_recv = threading.Event()
            self.release_recv = threading.Event()

        def recv(self, timeout=0.05):
            self.in_recv.set()
            self.release_recv.wait(0.5)
            return None

    raw = SlowBus()
    coordinator = new_coordinator(raw)
    assert raw.in_recv.wait(0.5)
    stopped = []
    stopper = threading.Thread(target=lambda: stopped.append(coordinator.stop(1.0)))
    stopper.start()
    time.sleep(0.02)
    set_armed(True)
    with pytest.raises(can_service.CanServiceClosedError):
        coordinator.send(frame(0x123))
    raw.release_recv.set()
    stopper.join(1.0)
    assert stopped == [True]
    assert raw.sent == []


def test_obd_poller_disarmed_never_calls_underlying_send():
    from core.obd2_poller import OBD2Poller

    raw = RawBus()
    poller = OBD2Poller(raw, pids=[0x0C], interval_ms=50)
    poller.start()
    time.sleep(0.08)
    poller.stop()

    assert not poller.isRunning()
    assert raw.sent == []


def test_live_worker_exposes_coordinator_and_owns_injected_bus(qtbot):
    """The main window must never publish the raw receiver Bus to consumers."""
    from mainwindow import LiveCANWorker

    raw = RawBus()
    worker = LiveCANWorker("virtual", "unused", 500_000, bus=raw)
    worker.start()
    qtbot.waitUntil(lambda: worker.get_bus() is not None, timeout=1000)

    assert isinstance(worker.get_bus(), can_service.CanCoordinator)
    worker.stop()
    assert not worker.isRunning()
    assert raw.shutdown_called
