"""Tabs own their workers; the main window only invokes one lifecycle API."""
from types import SimpleNamespace
import time
import queue
import threading

import pytest

from mainwindow import MainWindow
from ui.lifecycle import shutdown_owned
from ui.lifecycle import LifecycleTabMixin


class Timer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class Worker:
    def __init__(self, finishes=True):
        self.stop_called = False
        self.finishes = finishes

    def isRunning(self):
        return not self.stop_called or not self.finishes

    def stop(self):
        self.stop_called = True

    def wait(self, timeout):
        return self.finishes


def test_main_window_calls_each_tabs_shutdown_without_worker_attribute_knowledge():
    calls = []
    tabs = [SimpleNamespace(shutdown=lambda i=i: calls.append(i)) for i in range(3)]
    owner = SimpleNamespace(_tab_defs=[(tab, str(i), True) for i, tab in enumerate(tabs)])
    MainWindow._stop_tab_workers(owner)
    assert calls == [0, 1, 2]


def test_tab_shutdown_stops_timer_and_worker_then_clears_worker_reference():
    owner = SimpleNamespace(_timer=Timer(), _special_background_job=Worker())
    shutdown_owned(
        owner, worker_attrs=("_special_background_job",), timer_attrs=("_timer",)
    )
    assert owner._timer.stopped
    assert owner._special_background_job is None


def test_shutdown_timeout_is_reported_and_preserves_live_reference():
    worker = Worker(finishes=False)
    owner = SimpleNamespace(_worker=worker)
    with pytest.raises(RuntimeError, match="_worker"):
        shutdown_owned(owner, worker_attrs=("_worker",), timeout_ms=1)
    assert owner._worker is worker


def test_main_window_does_not_swallow_tab_shutdown_errors():
    def fail():
        raise TimeoutError("still running")

    owner = SimpleNamespace(
        _tab_defs=[(SimpleNamespace(shutdown=fail), "diagnostics", False)]
    )
    with pytest.raises(RuntimeError, match="diagnostics.*still running"):
        MainWindow._stop_tab_workers(owner)


def test_running_worker_slot_cannot_be_overwritten():
    class Owner(LifecycleTabMixin):
        pass

    worker = Worker(finishes=False)
    owner = Owner()
    owner._worker = worker
    assert owner.worker_slot_available("_worker") is False
    assert owner._worker is worker


def test_tabs_declare_all_reviewed_background_jobs():
    from tabs.ai_engine_tab import AIEngineTab
    from tabs.auto_re_tab import AutoRETab
    from tabs.diagnostics_tab import DiagnosticsTab
    from tabs.intelligence_tab import IntelligenceTab
    from tabs.obd_dashboard_tab import OBDDashboardTab

    assert {"_worker", "_nl_worker"} <= set(AIEngineTab.worker_attrs)
    assert {"_ctr_worker", "_entropy_worker", "_corr_worker"} <= set(AutoRETab.worker_attrs)
    assert {
        "_uds_worker", "_dtc_worker", "_deep_worker", "_svc_worker",
        "_sa_worker", "_clear_dtc_worker",
    } <= set(DiagnosticsTab.worker_attrs)
    assert "_comm_worker" in IntelligenceTab.worker_attrs
    assert {"_poller", "_discover_worker"} <= set(OBDDashboardTab.worker_attrs)


def test_obd_long_interval_stop_is_prompt(qtbot):
    from core.obd2_poller import OBD2Poller

    class Bus:
        def send(self, message):
            pass

        def recv(self, timeout=0.05):
            return None

    poller = OBD2Poller(Bus(), pids=[], interval_ms=10_000)
    poller.start()
    qtbot.wait(20)
    started = time.monotonic()
    poller.stop()
    assert time.monotonic() - started < 0.5
    assert not poller.isRunning()


def test_disconnect_stops_can_tasks_before_bus_owner(monkeypatch):
    events = []

    class Action:
        def setEnabled(self, value):
            pass

    class Signal:
        def emit(self, value):
            events.append("disconnected-signal")

    tab = SimpleNamespace(stop_can_tasks=lambda: events.append("tab-stopped"))
    live = SimpleNamespace(stop=lambda: events.append("bus-closed"))
    state = SimpleNamespace(
        can_bus=object(), can_service=object(), is_connected=True,
        can_connected=Signal(), append_frames=lambda df: None,
    )
    owner = SimpleNamespace(
        _tab_defs=[(tab, "diagnostics", False)], _live_worker=live,
        _multibus_worker=None, _live_rows=[], _live_last_ts={}, _state=state,
        _act_connect=Action(), _act_disconnect=Action(),
        _bus_load_meter=SimpleNamespace(reset=lambda: None),
        _live_frame_count=0, _health_timer=None, _bus_health_meter=object(),
        lbl_bus_health=SimpleNamespace(setText=lambda value: None),
        lbl_bitrate=SimpleNamespace(setText=lambda value: None),
    )
    monkeypatch.setattr("core.event_log.log_event", lambda *a, **k: None)

    MainWindow._disconnect_can(owner)

    assert events[:2] == ["tab-stopped", "bus-closed"]
    assert state.can_bus is None and state.can_service is None


def test_gateway_reader_thread_is_joinable_after_stop():
    from core.gateway import _BusReader

    class Bus:
        def recv(self, timeout=0.05):
            time.sleep(0.005)
            return None

    stopped = threading.Event()
    reader = _BusReader(Bus(), "A", queue.Queue(), stopped)
    reader.start()
    stopped.set()
    reader.join(0.5)
    assert not reader.is_alive()


def test_deep_uds_scan_shutdown_waits_for_thread(qtbot):
    from core.safety import set_armed
    from core.uds import UDSScanner

    class Bus:
        def __init__(self):
            self.sent = []

        def send(self, message):
            self.sent.append(message)

        def recv(self, timeout=0.05):
            time.sleep(min(timeout, 0.01))
            return None

    bus = Bus()
    worker = UDSScanner(bus, mode="DEEP")
    set_armed(True)
    try:
        worker.start()
        qtbot.waitUntil(lambda: bool(bus.sent), timeout=1000)
        owner = SimpleNamespace(_deep_worker=worker)
        shutdown_owned(owner, worker_attrs=("_deep_worker",), timeout_ms=1500)
        assert owner._deep_worker is None
        assert not worker.isRunning()
    finally:
        set_armed(False)
