"""AppState frame storage must enforce one hard limit at every entry point."""
import pandas as pd
import pytest

from core.state import AppState, TS_SOURCE_ADAPTER, TS_SOURCE_COLUMN, TS_SOURCE_LOG


def frames(start, count):
    return pd.DataFrame({
        "Seq": list(range(start, start + count)),
        "Timestamp": [float(i) for i in range(start, start + count)],
        "ID": ["123"] * count,
        "DLC": [1] * count,
        "B0": list(range(start, start + count)),
    })


def test_initial_load_keeps_latest_frames_only():
    state = AppState()
    state.max_frames = 3
    state.load_frames(frames(0, 5), "five")
    assert state.frames_df["Seq"].tolist() == [2, 3, 4]


def test_direct_assignment_obeys_same_limit():
    state = AppState()
    state.max_frames = 3
    state.frames_df = frames(0, 5)
    assert state.frames_df["Seq"].tolist() == [2, 3, 4]


def test_oversized_existing_base_then_append_is_trimmed():
    state = AppState()
    state.frames_df = frames(0, 5)
    state.max_frames = 3
    state.append_frames(frames(5, 1))
    assert state.frames_df["Seq"].tolist() == [3, 4, 5]


def test_single_oversized_chunk_replaces_old_data_with_its_tail():
    state = AppState()
    state.max_frames = 3
    state.frames_df = frames(0, 2)
    state.append_frames(frames(2, 5))
    assert state.frames_df["Seq"].tolist() == [4, 5, 6]


def test_many_chunks_always_stay_within_limit():
    state = AppState()
    state.max_frames = 3
    for index in range(10):
        state.append_frames(frames(index, 1))
        assert len(state.frames_df) <= 3
    assert state.frames_df["Seq"].tolist() == [7, 8, 9]


def test_trimming_preserves_timestamp_provenance():
    state = AppState()
    state.max_frames = 3
    state.load_frames(frames(0, 2), "log", timestamp_source=TS_SOURCE_LOG)
    state.append_frames(frames(2, 3), timestamp_source=TS_SOURCE_ADAPTER)
    result = state.frames_df
    assert result["Seq"].tolist() == [2, 3, 4]
    assert set(result[TS_SOURCE_COLUMN].astype(str)) == {TS_SOURCE_ADAPTER}


def test_repeated_reads_reuse_cache_until_mutation():
    state = AppState()
    state.max_frames = 3
    state.append_frames(frames(0, 1))
    first = state.frames_df
    assert state.frames_df is first
    state.append_frames(frames(1, 1))
    second = state.frames_df
    assert second is state.frames_df
    assert second is not first


@pytest.mark.parametrize("invalid", [0, -1, -100])
def test_non_positive_max_frames_is_invalid(invalid):
    state = AppState()
    with pytest.raises(ValueError):
        state.max_frames = invalid


def test_append_does_not_concat_whole_storage(monkeypatch):
    state = AppState()
    state.max_frames = 1000
    calls = []
    original = pd.concat

    def recording_concat(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "concat", recording_concat)
    for index in range(100):
        state.append_frames(frames(index, 1))
    assert calls == []
