"""Regression tests for P2.1 simple/advanced UI mode.

The full MainWindow is not constructed (teardown fragility); the mode logic
is exercised on a bare instance with stub tab widgets.
"""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QLabel, QTabWidget

from mainwindow import MainWindow


def _stub_window(qtbot):
    """Bare MainWindow with stub tab definitions, bypassing __init__."""
    win = MainWindow.__new__(MainWindow)
    win._ui_mode = "simple"
    win.tabs = QTabWidget()
    qtbot.addWidget(win.tabs)
    win._tab_defs = [
        (QLabel("frames"), "tab.frames", True),
        (QLabel("signals"), "tab.signals", True),
        (QLabel("gateway"), "tab.gateway", False),
        (QLabel("obd"), "tab.obd", False),
    ]
    return win


def test_simple_mode_shows_core_tabs_only(qtbot):
    win = _stub_window(qtbot)
    MainWindow._apply_ui_mode(win, "simple")
    assert win._ui_mode == "simple"
    assert win.tabs.count() == 2
    assert win.tabs.indexOf(win._tab_defs[0][0]) >= 0
    assert win.tabs.indexOf(win._tab_defs[2][0]) < 0  # advanced tab hidden


def test_advanced_mode_shows_all_tabs(qtbot):
    win = _stub_window(qtbot)
    MainWindow._apply_ui_mode(win, "advanced")
    assert win._ui_mode == "advanced"
    assert win.tabs.count() == 4


def test_hidden_tab_widgets_survive_mode_switch(qtbot):
    win = _stub_window(qtbot)
    gateway = win._tab_defs[2][0]
    MainWindow._apply_ui_mode(win, "advanced")
    MainWindow._apply_ui_mode(win, "simple")
    assert gateway is not None  # removeTab must not destroy the widget
    MainWindow._apply_ui_mode(win, "advanced")
    assert win.tabs.indexOf(gateway) >= 0  # same instance re-attached


def test_show_tab_escalates_to_advanced_for_hidden_tab(qtbot):
    win = _stub_window(qtbot)
    MainWindow._apply_ui_mode(win, "simple")
    qs = QSettings("CAN-Space", "CAN-Space")
    original = qs.value("ui_mode", None)
    try:
        hidden = win._tab_defs[2][0]
        MainWindow._show_tab(win, hidden)
        assert win._ui_mode == "advanced"
        assert win.tabs.currentWidget() is hidden
    finally:
        if original is None:
            qs.remove("ui_mode")
        else:
            qs.setValue("ui_mode", original)


def test_show_tab_visible_tab_keeps_mode(qtbot):
    win = _stub_window(qtbot)
    MainWindow._apply_ui_mode(win, "simple")
    qs = QSettings("CAN-Space", "CAN-Space")
    original = qs.value("ui_mode", None)
    try:
        visible = win._tab_defs[0][0]
        MainWindow._show_tab(win, visible)
        assert win._ui_mode == "simple"
        assert win.tabs.currentWidget() is visible
    finally:
        if original is None:
            qs.remove("ui_mode")
        else:
            qs.setValue("ui_mode", original)
