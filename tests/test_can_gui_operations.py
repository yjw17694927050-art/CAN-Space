"""GUI CAN operations must leave all Bus I/O off the main thread."""
from __future__ import annotations

import queue
import threading
import time

import pytest
from PyQt6.QtWidgets import QMessageBox

from core.i18n import tr
from core.safety import set_armed
from core.state import get_state


class OperationBus:
    def __init__(self, response=None, send_error=None, recv_delay=0.0):
        self.response = response
        self.send_error = send_error
        self.recv_delay = recv_delay
        self.sent = []
        self.send_thread_ids = []
        self.recv_thread_ids = []
        self._replies = queue.Queue()

    def send(self, message, timeout=None):
        self.send_thread_ids.append(threading.get_ident())
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message)
        if self.response is not None:
            self._replies.put(self.response)
            self.response = None

    def recv(self, timeout=0.05):
        self.recv_thread_ids.append(threading.get_ident())
        if self.recv_delay:
            time.sleep(min(self.recv_delay, timeout))
        try:
            return self._replies.get_nowait()
        except queue.Empty:
            return None


class Reply:
    def __init__(self, data):
        self.arbitration_id = 0x7E8
        self.data = bytes(data)


@pytest.fixture(autouse=True)
def reset_can_state():
    state = get_state()
    state.can_bus = None
    state.can_service = None
    set_armed(False)
    try:
        yield
    finally:
        state.can_bus = None
        state.can_service = None
        set_armed(False)


def configure_injection(tab, bus):
    get_state().can_bus = bus
    tab.sig_combo.clear()
    tab.sig_combo.addItem("Speed", {
        "message_id": "123", "signal_name": "Speed", "start_bit": 0,
        "length": 8, "byte_order": "little", "value_type": "unsigned",
        "scale": 1.0, "offset": 0.0, "msg_length": 8,
    })
    tab.sig_combo.setCurrentIndex(0)


def test_single_injection_bus_io_runs_outside_gui_thread(qtbot):
    from canlab.tabs.injection_tab import InjectionTab

    tab = InjectionTab()
    qtbot.addWidget(tab)
    bus = OperationBus()
    configure_injection(tab, bus)
    set_armed(True)
    gui_thread = threading.get_ident()

    tab._send_once()
    qtbot.waitUntil(lambda: bool(bus.sent), timeout=1000)
    qtbot.waitUntil(tab.btn_send_once.isEnabled, timeout=1000)

    assert bus.send_thread_ids == [bus.send_thread_ids[0]]
    assert bus.send_thread_ids[0] != gui_thread


def test_single_injection_failure_restores_button(qtbot):
    from canlab.tabs.injection_tab import InjectionTab

    tab = InjectionTab()
    qtbot.addWidget(tab)
    bus = OperationBus(send_error=RuntimeError("adapter offline"))
    configure_injection(tab, bus)
    set_armed(True)

    tab._send_once()
    qtbot.waitUntil(lambda: "adapter offline" in tab.lbl_inj_status.text(), timeout=1000)

    assert tab.btn_send_once.isEnabled()


def approve_clear(monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


def test_clear_dtc_positive_response_reports_success_off_gui_thread(qtbot, monkeypatch):
    from canlab.tabs.diagnostics_tab import DiagnosticsTab

    tab = DiagnosticsTab()
    qtbot.addWidget(tab)
    bus = OperationBus(response=Reply([0x01, 0x54, 0, 0, 0, 0, 0, 0]))
    get_state().can_bus = bus
    set_armed(True)
    approve_clear(monkeypatch)
    gui_thread = threading.get_ident()

    tab._clear_dtc()
    qtbot.waitUntil(
        lambda: tab.btn_clear_dtc.isEnabled()
        and (bool(bus.recv_thread_ids) or tab.dtc_text.toPlainText() == tr("diag.cleared")),
        timeout=1500,
    )

    assert tab.dtc_text.toPlainText() == tr("diag.cleared")
    assert bus.send_thread_ids and bus.recv_thread_ids
    assert all(thread_id != gui_thread for thread_id in bus.send_thread_ids)
    assert all(thread_id != gui_thread for thread_id in bus.recv_thread_ids)


def test_clear_dtc_negative_response_is_not_success(qtbot, monkeypatch):
    from canlab.tabs.diagnostics_tab import DiagnosticsTab

    tab = DiagnosticsTab()
    qtbot.addWidget(tab)
    reply = Reply(bytes.fromhex("03 7F 14 22 00 00 00 00"))
    bus = OperationBus(response=reply)
    get_state().can_bus = bus
    set_armed(True)
    approve_clear(monkeypatch)

    tab._clear_dtc()
    qtbot.waitUntil(tab.btn_clear_dtc.isEnabled, timeout=1500)
    qtbot.wait(50)

    success_text = tr("diag.cleared")
    assert tab.dtc_text.toPlainText() != success_text


@pytest.mark.parametrize(
    "bus, expected",
    [
        (OperationBus(send_error=RuntimeError("adapter offline")), "adapter offline"),
        (OperationBus(), "Timed out"),
    ],
)
def test_clear_dtc_send_failure_and_timeout_restore_ui(
        qtbot, monkeypatch, bus, expected):
    from canlab.tabs.diagnostics_tab import DiagnosticsTab

    tab = DiagnosticsTab()
    qtbot.addWidget(tab)
    get_state().can_bus = bus
    set_armed(True)
    approve_clear(monkeypatch)

    tab._clear_dtc()
    qtbot.waitUntil(tab.btn_clear_dtc.isEnabled, timeout=2500)

    assert expected in tab.dtc_text.toPlainText()
    assert tab.dtc_text.toPlainText() != tr("diag.cleared")


def test_repeated_clear_dtc_does_not_start_second_operation(qtbot, monkeypatch):
    from canlab.tabs.diagnostics_tab import DiagnosticsTab

    tab = DiagnosticsTab()
    qtbot.addWidget(tab)
    bus = OperationBus(recv_delay=0.05)
    get_state().can_bus = bus
    set_armed(True)
    approve_clear(monkeypatch)

    tab._clear_dtc()
    qtbot.waitUntil(lambda: len(bus.sent) == 1, timeout=1000)
    tab._clear_dtc()

    assert len(bus.sent) == 1
    worker = getattr(tab, "_clear_dtc_worker", None)
    if worker is not None:
        worker.stop()
        worker.wait(1000)
