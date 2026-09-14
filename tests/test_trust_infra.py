"""Tests for P2.3 trust infrastructure:
- frame-level timestamp provenance (state.py)
- structured JSONL event log (core/event_log.py)
"""
import pandas as pd
import pytest

pytest.importorskip("PyQt6")


def _df(n=3):
    return pd.DataFrame({
        "Timestamp": [float(i) for i in range(n)],
        "ID": ["0CF"] * n,
        "Bus": ["live"] * n,
        "DLC": [8] * n,
        **{f"B{i}": [0] * n for i in range(8)},
    })


@pytest.fixture()
def state(qapp):
    from canlab.core.state import AppState
    return AppState()


def test_load_frames_tags_log_file_source(state):
    from canlab.core.state import TS_SOURCE_COLUMN, TS_SOURCE_LOG
    state.load_frames(_df(), "sample.csv")
    df = state.frames_df
    assert TS_SOURCE_COLUMN in df.columns
    assert set(df[TS_SOURCE_COLUMN].unique()) == {TS_SOURCE_LOG}
    assert state.timestamp_sources() == {TS_SOURCE_LOG}


def test_append_frames_tags_adapter_source(state):
    from canlab.core.state import TS_SOURCE_COLUMN, TS_SOURCE_ADAPTER
    state.append_frames(_df(2))
    df = state.frames_df
    assert set(df[TS_SOURCE_COLUMN].unique()) == {TS_SOURCE_ADAPTER}


def test_mixed_sources_union(state):
    from canlab.core.state import TS_SOURCE_ADAPTER, TS_SOURCE_LOG
    state.load_frames(_df(2), "a.csv")
    state.append_frames(_df(2))
    assert state.timestamp_sources() == {TS_SOURCE_LOG, TS_SOURCE_ADAPTER}
    assert len(state.frames_df) == 4


def test_existing_source_column_not_overwritten(state):
    from canlab.core.state import TS_SOURCE_COLUMN, TS_SOURCE_PC
    df = _df(2)
    df[TS_SOURCE_COLUMN] = TS_SOURCE_PC
    state.load_frames(df, "b.csv")  # default log_file must NOT clobber
    assert set(state.frames_df[TS_SOURCE_COLUMN].astype(str).unique()) == {
        TS_SOURCE_PC}


def test_event_log_roundtrip(tmp_path, monkeypatch):
    from canlab.core import event_log
    monkeypatch.setattr(event_log, "_LOG_DIR", str(tmp_path))
    ev = event_log.log_event("log.load", func="test", path="a.csv",
                             frames=10, duration_ms=12.34)
    assert ev["type"] == "log.load"
    events = event_log.read_events()
    assert len(events) == 1
    assert events[0]["frames"] == 10
    assert events[0]["duration_ms"] == 12.3
    assert events[0]["level"] == "info"


def test_event_log_error_level_and_traceback(tmp_path, monkeypatch):
    from canlab.core import event_log
    monkeypatch.setattr(event_log, "_LOG_DIR", str(tmp_path))
    try:
        raise ValueError("boom")
    except ValueError:
        event_log.log_event("can.connect", func="test", error="boom")
    events = event_log.read_events()
    assert events[0]["level"] == "error"
    assert events[0]["error"] == "boom"
    assert "ValueError" in events[0]["traceback"]


def test_event_log_survives_unwritable_dir(tmp_path, monkeypatch):
    from canlab.core import event_log
    monkeypatch.setattr(event_log, "_LOG_DIR", str(tmp_path / "\0bad"))
    event_log.log_event("x")  # must not raise
