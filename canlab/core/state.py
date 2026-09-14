from PyQt6.QtCore import QObject, pyqtSignal
import pandas as pd

# Timestamp provenance tags (P2.3 trust infrastructure). Stored as a pandas
# category column so the per-frame cost is ~1 byte.
TS_SOURCE_ADAPTER = "adapter_hw"   # adapter/kernel timestamp from live capture
TS_SOURCE_LOG     = "log_file"     # timestamp parsed from a log file
TS_SOURCE_PC      = "pc_clock"     # PC wall-clock fallback
TS_SOURCE_COLUMN  = "TsSource"


def _ensure_ts_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Tag df with a timestamp-source column; never overwrite existing tags."""
    if df is None or df.empty or TS_SOURCE_COLUMN in df.columns:
        return df
    df = df.copy()
    df[TS_SOURCE_COLUMN] = pd.Categorical(
        [source] * len(df),
        categories=[TS_SOURCE_ADAPTER, TS_SOURCE_LOG, TS_SOURCE_PC],
    )
    return df


class AppState(QObject):
    id_selected       = pyqtSignal(str)
    frames_loaded     = pyqtSignal(int)
    signal_analyzed   = pyqtSignal(str)
    dbc_updated       = pyqtSignal()
    can_connected     = pyqtSignal(bool)
    frames_updated    = pyqtSignal()
    source_added      = pyqtSignal(str, int)
    repo_loaded       = pyqtSignal(dict)

    # New signals for advanced features
    project_loaded      = pyqtSignal()
    fingerprint_matched = pyqtSignal(dict)
    trigger_fired       = pyqtSignal(dict, object)   # rule, frame
    uds_response        = pyqtSignal(int, bytes)     # arb_id, data
    replay_tick         = pyqtSignal(int, int)       # current, total
    bus_load_update     = pyqtSignal(float)          # 0.0–1.0
    opendbc_matched     = pyqtSignal(dict)
    anomaly_requested   = pyqtSignal(str, object)    # hex_id, frames_df

    # ── New signals for 12-feature additions ──────────────────────────────────
    canfd_toggled        = pyqtSignal(bool)
    change_detected      = pyqtSignal(list)           # list of delta dicts
    fuzz_progress        = pyqtSignal(int, int)        # done, total
    multibus_frame       = pyqtSignal(str, object)     # bus_name, frame
    safety_cutout        = pyqtSignal(float, str)      # value_at_cutout, reason
    note_updated         = pyqtSignal(str)             # signal_key

    # ── New signals for 8 production enhancements ─────────────────────────────
    isotp_response       = pyqtSignal(int, bytes)      # arb_id, full assembled payload
    bus_health_update    = pyqtSignal(dict)             # health snapshot
    test_step_completed  = pyqtSignal(int, bool, str)  # step_idx, ok, message
    j1939_decoded        = pyqtSignal(int, dict)        # pgn, {spn: value}
    dbc_db_updated       = pyqtSignal()                 # cantools cache rebuilt

    # ── OBD-II live gauges ────────────────────────────────────────────────────
    pid_value_updated    = pyqtSignal(int, float, str)  # pid, value, unit

    # ── Signal Intelligence (ML) ──────────────────────────────────────────────
    ml_analysis_ready    = pyqtSignal(str, dict)         # id, roles_dict
    anomaly_detected     = pyqtSignal(str, float)        # id, score

    def __init__(self, parent=None):
        super().__init__(parent)

        # Frames are stored as a base DataFrame plus a list of appended live
        # chunks; `frames_df` (property below) concatenates them lazily and
        # caches the result. This keeps live append() at O(chunk) instead of the
        # O(n) full-DataFrame copy the old concat-per-batch did (which made long
        # captures O(n²) and eventually froze the UI).
        self._frames_base:   pd.DataFrame = pd.DataFrame()
        self._frame_chunks:  list         = []
        self._frames_cache:  pd.DataFrame = None
        # Cap on total frames kept in memory. Prevents OOM on long captures.
        # When exceeded, the oldest chunks are dropped.
        self.max_frames:     int          = 500_000
        self.selected_id:      str          = ""
        self.sources:          list         = []
        self.can_bus           = None
        self.is_connected:     bool         = False
        self.dbc_signals:      list         = []
        self.analyzed_ids:     dict         = {}
        self.live_frame_count: int          = 0
        self.frame_rate:       float        = 0.0
        self.annotations:      dict         = {}

        # GitHub repo context
        self.repo_info:        dict         = {}
        self.repo_readme:      str          = ""
        self.repo_url:         str          = ""

        # Advanced feature state
        self.diff_baseline_df: pd.DataFrame = pd.DataFrame()
        self.periodicities:    dict         = {}   # id -> cycle_time_ms
        self.fingerprint:      dict         = {}   # model, confidence, matched_ids
        self.ai_memory:        list         = []   # list of prior AI conclusions
        self.opendbc_matches:  dict         = {}   # sig_name -> opendbc path
        self.project_path:     str          = ""
        self.plugins:          list         = []
        self.rest_api_running: bool         = False
        self.rest_api_port:    int          = 8765
        self.triggers:         list         = []   # list of trigger dicts
        self.injection_active: dict         = {}   # sig_name -> (value, period_ms)

        # ── New fields for 12-feature additions ───────────────────────────────
        self.canfd_enabled:     bool         = False
        self.multibus_buses:    dict         = {}   # name -> Bus instance
        self.change_baseline                 = None # ChangeRecorder snapshot
        self.notes_by_signal:   dict         = {}   # "{msg_id}/{sig_name}" -> str
        self.fuzz_running:      bool         = False
        self.active_backend:    str          = "python-can"
        self.panda_safety_model: str         = "SAFETY_NOOUTPUT"
        self.community_profiles: list        = []
        self.community_profiles_url: str     = (
            "https://raw.githubusercontent.com/commaai/opendbc/master/"
            "opendbc/can/hyundai_kona.dbc"
        )

        # ── New fields for 8 production enhancements ──────────────────────────
        self.dbc_db              = None        # cached cantools.database.Database
        self.bus_health: dict    = {           # live health counters
            "error_frames": 0,
            "bus_off":      0,
            "peak_load":    0.0,
            "avg_load":     0.0,
            "total_frames": 0,
        }
        self.test_sequences: list = []         # list of TestStep dicts

        # OBD-II live gauges
        self.obd_active_pids: list = []        # PID ints selected by user

        # Signal Intelligence
        self._embedding_index: dict = {}       # id -> np.ndarray, built by signal_intelligence_tab

    # ── frames_df storage (lazy base + chunks) ────────────────────────────────

    @property
    def frames_df(self) -> pd.DataFrame:
        if self._frames_cache is not None:
            return self._frames_cache
        if not self._frame_chunks:
            self._frames_cache = self._frames_base
        else:
            parts = ([self._frames_base] if not self._frames_base.empty
                     else []) + self._frame_chunks
            self._frames_cache = (pd.concat(parts, ignore_index=True)
                                  if parts else pd.DataFrame())
        return self._frames_cache

    @frames_df.setter
    def frames_df(self, df: pd.DataFrame):
        # Direct assignment (project load, transforms) replaces everything and
        # collapses any pending live chunks.
        self._frames_base  = df if df is not None else pd.DataFrame()
        self._frame_chunks = []
        self._frames_cache = self._frames_base

    def select_id(self, hex_id: str):
        self.selected_id = hex_id
        self.id_selected.emit(hex_id)

    def load_frames(self, df: pd.DataFrame, source_name: str,
                    timestamp_source: str = TS_SOURCE_LOG):
        self.frames_df = _ensure_ts_source(df, timestamp_source)
        count = len(self._frames_base)
        self.sources.append({"name": source_name, "count": count})
        self.frames_loaded.emit(count)
        self.source_added.emit(source_name, count)
        self.frames_updated.emit()

    def append_frames(self, new_df: pd.DataFrame,
                      timestamp_source: str = TS_SOURCE_ADAPTER):
        if new_df is None or new_df.empty:
            return
        new_df = _ensure_ts_source(new_df, timestamp_source)
        # O(chunk): just stash the chunk and invalidate the cache. The full
        # DataFrame is rebuilt lazily on the next read (throttled by the UI).
        self._frame_chunks.append(new_df)
        self._frames_cache = None
        # Enforce memory cap: drop oldest chunks when total exceeds max_frames.
        total = (len(self._frames_base) +
                 sum(len(c) for c in self._frame_chunks))
        while total > self.max_frames and self._frame_chunks:
            dropped = self._frame_chunks.pop(0)
            total -= len(dropped)
        self.frames_updated.emit()

    def set_repo_context(self, info: dict, readme: str, url: str):
        self.repo_info   = info
        self.repo_readme = readme
        self.repo_url    = url
        self.repo_loaded.emit(info)

    def add_dbc_signal(self, signal_def: dict):
        self.dbc_signals.append(signal_def)
        self.dbc_updated.emit()

    def update_dbc_signal(self, index: int, signal_def: dict):
        if 0 <= index < len(self.dbc_signals):
            self.dbc_signals[index] = signal_def
            self.dbc_updated.emit()

    def remove_dbc_signal(self, index: int):
        if 0 <= index < len(self.dbc_signals):
            self.dbc_signals.pop(index)
            self.dbc_updated.emit()

    def timestamp_sources(self) -> set:
        """Provenance tags present in the current frame set (P2.3)."""
        df = self.frames_df
        if df.empty or TS_SOURCE_COLUMN not in df.columns:
            return set()
        return set(df[TS_SOURCE_COLUMN].dropna().unique())

    def get_frames_for_id(self, hex_id: str) -> pd.DataFrame:
        if self.frames_df.empty:
            return pd.DataFrame()
        from core.canid import normalize_id
        return self.frames_df[self.frames_df["ID"] == normalize_id(hex_id)].copy()

    def get_unique_ids(self) -> list:
        if self.frames_df.empty:
            return []
        return sorted(self.frames_df["ID"].unique().tolist())


_state = None

def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
