"""
pytest-qt UI tests at the per-tab level.

Design note: constructing the full 15-tab MainWindow and tearing it down is
unstable on this Windows box (native access-violation / stack-guard crashes from
animation timers and pyqtgraph resources being released mid-teardown), while a
single lightweight tab builds, shows, and closes cleanly. So we cover the UI one
tab at a time - loading real sample data and driving actual widget interaction -
which gives meaningful UI coverage without the MainWindow teardown fragility.

Run on CI with a real/virtual display (Xvfb on Linux); PyQt6 needs one.
"""
import os
import time
import pytest
import pandas as pd
from pytestqt.qtbot import QtBot

_SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "canlab", "sample_data", "sample_kona_drive.csv",
)


@pytest.fixture
def frames():
    """Real parsed sample frames loaded into shared AppState.

    MUST import through the same top-level ``core.*`` the app itself uses
    (conftest puts canlab/ on sys.path). Importing via ``canlab.core.*`` instead
    creates a *second* module instance with its own get_state() singleton, so the
    tabs — which read ``core.state`` — see an empty frame table.
    """
    from core.log_parser import parse_log_file
    from core.state import get_state
    df = parse_log_file(_SAMPLE)
    assert not df.empty and len(df["ID"].unique()) > 5
    get_state().load_frames(df, "sample_kona_drive")
    try:
        yield df
    finally:
        try:
            get_state().frames_df = pd.DataFrame()
        except Exception:
            pass


# ── FRAMES tab ────────────────────────────────────────────────────────────────

def test_frames_tab_builds_and_has_rows(qtbot: QtBot, frames):
    from canlab.tabs.frames_tab import FramesTab
    tab = FramesTab()
    qtbot.add_widget(tab)
    tab.show()
    # Table refresh is coalesced on a 300 ms QTimer; drive it explicitly.
    tab._refresh()
    qtbot.wait(20)
    assert tab.table.rowCount() > 0
    # Count label is language-agnostic here (numeric "shown / total").
    assert "5000" in tab.lbl_count.text()
    assert "6610" in tab.lbl_count.text()


def test_frames_tab_selects_id(qtbot: QtBot, frames):
    from canlab.tabs.frames_tab import FramesTab
    from core.state import get_state
    tab = FramesTab()
    qtbot.add_widget(tab)
    tab.show()
    an_id = get_state().get_unique_ids()[0]
    get_state().select_id(an_id)
    qtbot.wait(30)
    assert get_state().selected_id == an_id


def test_frames_tab_id_filter_reduces_rows(qtbot: QtBot, frames):
    """Typing an ID in the filter box must narrow the visible rows.

    Uses a *rare* ID so the filtered table is a few hundred rows — building the
    full MAX_DISPLAY=5000-row table twice in one process triggers heavy
    QTableWidgetItem churn under ResizeToContents and makes the test slow/flaky.
    """
    from canlab.tabs.frames_tab import FramesTab
    counts = frames["ID"].astype(str).value_counts()
    rare = counts.idxmin()
    pat = str(rare)
    expected = int(
        frames["ID"].astype(str).str.contains(pat, case=False, na=False).sum()
    )
    assert 0 < expected < len(frames), "sample should have a rare ID that narrows rows"

    tab = FramesTab()
    qtbot.add_widget(tab)
    tab.show()
    tab.filter_id.setText(pat)   # textChanged -> _on_filter_changed -> _refresh (once)
    assert tab.table.rowCount() == expected


# ── PLOT tab (covers the live-update throttling fix) ──────────────────────────

def test_plot_tab_add_remove_signal(qtbot: QtBot, frames):
    from canlab.tabs.plot_tab import PlotTab
    tab = PlotTab()
    qtbot.add_widget(tab)
    tab.show()
    can_id = list(frames["ID"].unique())[0]
    tab._add_signal(f"{can_id}:B0", "byte", can_id, "B0")
    assert f"{can_id}:B0" in tab._plot_items
    tab._remove_signal(f"{can_id}:B0")
    assert f"{can_id}:B0" not in tab._plot_items


def test_plot_live_update_is_throttled(qtbot: QtBot, frames):
    """Repeated frames_updated within the throttle window must NOT recompute."""
    from canlab.tabs.plot_tab import PlotTab
    tab = PlotTab()
    qtbot.add_widget(tab)
    tab.show()
    can_id = list(frames["ID"].unique())[0]
    tab._on_live_toggled(True)
    tab._add_signal(f"{can_id}:B0", "byte", can_id, "B0")

    # Force a refresh out of the throttle window, then hammer it again.
    tab._last_live_refresh = 0.0
    tab._live_update()
    key = f"{can_id}:B0"
    assert key in tab._plot_items
    pi, curve, *_ = tab._plot_items[key]
    assert curve.getData() is not None

    first_calls = tab._plot_items[key][1].getData()
    before = time.monotonic()
    tab._last_live_refresh = before     # emulate an event just inside the window
    tab._live_update()                   # must be a no-op (still throttled)
    assert time.monotonic() - before < 0.05  # returns immediately
    assert tab._plot_items[key][1].getData() == first_calls


# ── SIGNALS tab ───────────────────────────────────────────────────────────────

def test_signals_tab_builds(qtbot: QtBot, frames):
    from canlab.tabs.signals_tab import SignalsTab
    tab = SignalsTab()
    qtbot.add_widget(tab)
    tab.show()
    qtbot.wait(20)
    assert tab is not None


def test_signals_tab_classify_fills_table(qtbot: QtBot, frames):
    """Driving Auto-classify runs the AnalyzeWorker thread and populates rows."""
    from canlab.tabs.signals_tab import SignalsTab
    tab = SignalsTab()
    qtbot.add_widget(tab)
    tab.show()
    tab._run_classify()

    def classified():
        return len(tab._signals_df) > 0 and tab.lbl_status.text() != ""

    qtbot.waitUntil(classified, timeout=30000)
    assert tab.table.rowCount() > 0
    # Let the (now-finished) worker thread wind down before teardown.
    if getattr(tab, "_worker", None) is not None:
        tab._worker.wait(2000)


# ── AUTO-RE (analysis) tab ────────────────────────────────────────────────────

def test_auto_re_tab_builds(qtbot: QtBot, frames):
    from canlab.tabs.auto_re_tab import AutoRETab
    tab = AutoRETab()
    qtbot.add_widget(tab)
    tab.show()
    qtbot.wait(20)
    assert tab is not None


# ── Remaining leaf tabs: build + close must not crash ─────────────────────────

@pytest.mark.parametrize("module,cls", [
    ("dashboard_tab",     "DashboardTab"),
    ("timeline_tab",      "TimelineTab"),
    ("gateway_tab",       "GatewayTab"),
    ("injection_tab",     "InjectionTab"),
    ("dbc_builder_tab",   "DBCBuilderTab"),
    ("diagnostics_tab",   "DiagnosticsTab"),
    ("obd_dashboard_tab", "OBDDashboardTab"),
    ("code_gen_tab",      "CodeGenTab"),
    ("intelligence_tab",  "IntelligenceTab"),
    ("ai_engine_tab",     "AIEngineTab"),
])
def test_leaf_tab_builds(qtbot: QtBot, frames, module, cls):
    """Every remaining tab instantiates with sample data and closes cleanly.

    These tabs keep hardware/thread work lazy (created only inside methods), so
    a bare construct + show + teardown exercises widget setup without grabbing a
    CAN adapter or starting a worker.
    """
    import importlib
    tabmod = importlib.import_module(f"canlab.tabs.{module}")
    tab = getattr(tabmod, cls)(parent=None)
    qtbot.add_widget(tab)
    tab.show()
    qtbot.wait(20)
    assert tab is not None