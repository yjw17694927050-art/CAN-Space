"""
GitHub repo fetcher — parses any GitHub URL, walks the full repo tree,
categorises files into logs / DBC / README, downloads them and returns
structured data the app can use directly.
"""
import os
import re
import base64
import hashlib
import tempfile
import requests
from pathlib import Path
from urllib.parse import quote, unquote
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QObject
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QProgressBar, QTextEdit,
    QTabWidget, QWidget, QLineEdit, QMessageBox, QCheckBox,
    QGroupBox,
)
from PyQt6.QtGui import QColor, QBrush
from theme import COLORS, mono_font

CACHE_DIR = Path.home() / ".canlab" / "cache"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

LOG_EXTS  = {".csv", ".log", ".bag"}
DBC_EXTS  = {".dbc"}
DOC_NAMES = {"readme", "readme.md", "readme.txt", "notes.md", "notes.txt",
             "annotations.md", "annotations.txt", "events.md", "events.txt"}


def _cache_path(remote_file: dict) -> Path:
    """Return a collision-resistant path tied to the remote object identity."""
    identity = "\0".join(str(remote_file.get(key, "")) for key in (
        "owner", "repo", "branch", "path", "sha",
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    name = Path(str(remote_file.get("name", "download"))).name or "download"
    return CACHE_DIR / digest[:2] / digest / name


def _cache_is_valid(path: Path, remote_file: dict) -> bool:
    if not path.is_file():
        return False
    expected_size = int(remote_file.get("size") or 0)
    actual_size = path.stat().st_size
    if expected_size > 0 and actual_size != expected_size:
        return False
    expected_sha = str(remote_file.get("sha") or "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        digest = hashlib.sha1()
        digest.update(f"blob {actual_size}\0".encode("ascii"))
        with path.open("rb") as cached:
            for chunk in iter(lambda: cached.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha
    return True


# ── URL helpers ────────────────────────────────────────────────────────────────

def parse_github_url(url: str) -> dict | None:
    """
    Accept any of:
      https://github.com/owner/repo
      https://github.com/owner/repo/tree/branch/path
      https://github.com/owner/repo/blob/branch/path/file
      https://api.github.com/repos/owner/repo/contents/path
    Returns dict with api_base, api_tree, readme_url etc.
    """
    url = url.strip().rstrip("/")

    # Already an API URL
    m = re.match(r"https://api\.github\.com/repos/([^/]+)/([^/]+)", url)
    if m:
        return _build_result(
            unquote(m.group(1)), unquote(m.group(2)), "HEAD", "", "root"
        )

    # Browser URL
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/(tree|blob)/([^/]+)(/.+)?)?", url)
    if m:
        owner  = unquote(m.group(1))
        repo   = unquote(m.group(2))
        branch = unquote(m.group(4)) if m.group(4) else "HEAD"
        path   = unquote((m.group(5) or "").lstrip("/"))
        return _build_result(owner, repo, branch, path, m.group(3) or "root")

    return None


def _build_result(owner, repo, branch, path, kind="root"):
    encoded_owner = quote(owner, safe="")
    encoded_repo = quote(repo, safe="")
    encoded_branch = quote(branch, safe="")
    base = f"https://api.github.com/repos/{encoded_owner}/{encoded_repo}"
    return {
        "owner":        owner,
        "repo":         repo,
        "branch":       branch,
        "path":         path,
        "kind":         kind,
        "api_base":     base,
        "api_tree":     f"{base}/git/trees/{encoded_branch}?recursive=1",
        "readme_url":   f"{base}/readme",
    }


# ── Workers ────────────────────────────────────────────────────────────────────

class RepoScanWorker(QThread):
    progress = pyqtSignal(str)
    done     = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, repo_info: dict, token: str = "", parent=None):
        super().__init__(parent)
        self.info  = repo_info
        self.token = token
        self._abort = False
        self._active_response = None

    def abort(self):
        self._abort = True
        self.requestInterruption()
        if self._active_response is not None:
            self._active_response.close()

    def _headers(self):
        h = {"Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def run(self):
        try:
            self.progress.emit("Fetching repo info…")
            r = requests.get(self.info["api_base"], headers=self._headers(), timeout=15)
            self._active_response = r
            r.raise_for_status()
            meta = r.json()
            if self._abort:
                return

            self.progress.emit("Walking repo tree…")
            requested_branch = self.info["branch"]
            branch = (
                meta.get("default_branch", "HEAD")
                if requested_branch == "HEAD" else requested_branch
            )
            tree_url = (f"{self.info['api_base']}/git/trees/"
                        f"{quote(branch, safe='')}?recursive=1")
            r = requests.get(tree_url, headers=self._headers(), timeout=30)
            self._active_response = r
            r.raise_for_status()
            tree = r.json().get("tree", [])
            if self._abort:
                return

            logs, dbcs, docs = [], [], []
            for item in tree:
                if item.get("type") != "blob":
                    continue
                fpath = item["path"]
                scope = self.info.get("path", "").strip("/")
                kind = self.info.get("kind", "root")
                if kind == "blob" and fpath != scope:
                    continue
                if kind == "tree" and scope and not (
                    fpath == scope or fpath.startswith(scope + "/")
                ):
                    continue
                fname = os.path.basename(fpath).lower()
                ext   = os.path.splitext(fname)[1]
                dl    = (f"https://raw.githubusercontent.com/"
                         f"{quote(self.info['owner'], safe='')}/"
                         f"{quote(self.info['repo'], safe='')}/"
                         f"{quote(branch, safe='')}/{quote(fpath, safe='/')}")
                entry = {
                    "name": os.path.basename(fpath),
                    "path": fpath,
                    "download_url": dl,
                    "size": item.get("size", 0),
                    "sha": item.get("sha", ""),
                    "owner": self.info["owner"],
                    "repo": self.info["repo"],
                    "branch": branch,
                }
                if ext in LOG_EXTS:
                    logs.append(entry)
                elif ext in DBC_EXTS:
                    dbcs.append(entry)
                elif fname in DOC_NAMES or "readme" in fname:
                    docs.append(entry)

            readme_text = ""
            self.progress.emit("Fetching README…")
            try:
                readme_url = (
                    f"{self.info['readme_url']}?ref={quote(branch, safe='')}"
                )
                r = requests.get(readme_url, headers=self._headers(), timeout=10)
                self._active_response = r
                if r.ok:
                    data = r.json()
                    content  = data.get("content", "")
                    encoding = data.get("encoding", "base64")
                    readme_text = (
                        base64.b64decode(content).decode("utf-8", errors="replace")
                        if encoding == "base64" else content
                    )
            except Exception:
                pass

            self.progress.emit(
                f"Found {len(logs)} logs, {len(dbcs)} DBC files — "
                f"{self.info['owner']}/{self.info['repo']}"
            )
            self.done.emit({
                "logs":   logs,
                "dbcs":   dbcs,
                "docs":   docs,
                "readme": readme_text,
                "meta":   meta,
                "branch": branch,
            })

        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code == 403:
                self.error.emit("GitHub rate limit hit. Add a token in Settings > GitHub.")
            elif code == 404:
                if self.info.get("kind") in ("tree", "blob"):
                    self.error.emit(
                        "Branch or path not found — check the GitHub URL."
                    )
                else:
                    self.error.emit("Repo not found — check the URL.")
            else:
                self.error.emit(f"HTTP {code}: {e}")
        except requests.ConnectionError:
            self.error.emit("Network error — check your internet connection.")
        except Exception as e:
            if not self._abort:
                self.error.emit(str(e))
        finally:
            self._active_response = None


class BatchDownloadWorker(QThread):
    file_done  = pyqtSignal(str, str)   # (repo_path, local_path)
    file_error = pyqtSignal(str, str)   # (repo_path, error)
    all_done   = pyqtSignal(list)       # list of local paths
    progress   = pyqtSignal(int, int)   # (done, total)

    def __init__(self, files: list, token: str = "", parent=None):
        super().__init__(parent)
        self.files = files
        self.token = token
        self._abort = False
        self._active_response = None

    def abort(self):
        self._abort = True
        self.requestInterruption()
        if self._active_response is not None:
            self._active_response.close()

    def run(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        results = []
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        for i, f in enumerate(self.files):
            if self._abort:
                break
            dest = _cache_path(f)
            if _cache_is_valid(dest, f):
                results.append(str(dest))
                self.file_done.emit(f["path"], str(dest))
            else:
                temp_path = None
                try:
                    declared_size = int(f.get("size") or 0)
                    if declared_size > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"File too large ({declared_size} bytes; "
                            f"limit {MAX_DOWNLOAD_BYTES})"
                        )
                    r = requests.get(
                        f["download_url"], timeout=60, headers=headers, stream=True
                    )
                    self._active_response = r
                    r.raise_for_status()
                    content_length = int(r.headers.get("Content-Length") or 0)
                    if content_length > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"File too large ({content_length} bytes; "
                            f"limit {MAX_DOWNLOAD_BYTES})"
                        )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=dest.parent, suffix=".part", delete=False
                    ) as temp_file:
                        temp_path = Path(temp_file.name)
                        downloaded = 0
                        for chunk in r.iter_content(chunk_size=64 * 1024):
                            if self._abort:
                                raise InterruptedError("Download cancelled")
                            if not chunk:
                                continue
                            downloaded += len(chunk)
                            if downloaded > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"File too large (limit {MAX_DOWNLOAD_BYTES})"
                                )
                            temp_file.write(chunk)
                    if declared_size > 0 and downloaded != declared_size:
                        raise OSError(
                            f"Incomplete download: expected {declared_size} bytes, "
                            f"received {downloaded}"
                        )
                    expected_sha = str(f.get("sha") or "").lower()
                    if (re.fullmatch(r"[0-9a-f]{40}", expected_sha)
                            and not _cache_is_valid(temp_path, f)):
                        raise OSError("Downloaded file failed Git blob SHA validation")
                    os.replace(temp_path, dest)
                    temp_path = None
                    results.append(str(dest))
                    self.file_done.emit(f["path"], str(dest))
                except Exception as e:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                    if not self._abort:
                        self.file_error.emit(f["path"], str(e))
                finally:
                    self._active_response = None
            self.progress.emit(i + 1, len(self.files))
        self.all_done.emit(results)


# ── Main dialog ────────────────────────────────────────────────────────────────

class GitHubRepoDialog(QDialog):
    """
    Full GitHub repo browser. Paste any GitHub URL → scans repo →
    shows logs / DBC files / README → user picks what to load.
    """
    logs_ready      = pyqtSignal(list)   # list of local log paths
    dbcs_ready      = pyqtSignal(list)   # list of local .dbc paths
    readme_ready    = pyqtSignal(str)    # README text (emitted first)
    repo_meta_ready = pyqtSignal(dict)   # repo metadata (emitted after readme)

    def __init__(self, initial_url: str = "", token: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("CANLAB — GitHub Repo Fetch")
        self.setMinimumSize(680, 560)
        self._token      = token
        self._scan_data  = {}
        self._scan_worker: RepoScanWorker | None = None
        self._dl_worker:   BatchDownloadWorker | None = None
        self._scanning   = False
        self._build_ui()
        if initial_url.strip():
            self.url_edit.setText(initial_url.strip())
            self._start_scan()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # URL bar
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("GitHub URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://github.com/owner/repo  or  .../tree/main/logs"
        )
        self.url_edit.setFont(mono_font(9))
        self.url_edit.returnPressed.connect(self._start_scan)
        url_row.addWidget(self.url_edit)
        self.btn_scan = QPushButton("Scan Repo")
        self.btn_scan.setObjectName("btn_green")
        self.btn_scan.clicked.connect(self._start_scan)
        url_row.addWidget(self.btn_scan)
        lay.addLayout(url_row)

        self.lbl_status = QLabel("Paste a GitHub repo URL and click Scan Repo.")
        self.lbl_status.setObjectName("label_dim")
        self.lbl_status.setFont(mono_font(8))
        lay.addWidget(self.lbl_status)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setFont(mono_font(9, bold=True))
        self.lbl_meta.setObjectName("label_green")
        lay.addWidget(self.lbl_meta)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        lay.addWidget(self.progress_bar)

        # Tabs
        self.file_tabs = QTabWidget()

        # Log files tab
        log_w = QWidget()
        log_lay = QVBoxLayout(log_w)
        log_lay.setContentsMargins(4, 4, 4, 4)
        log_top = QHBoxLayout()
        self.chk_all_logs = QCheckBox("Select All")
        self.chk_all_logs.toggled.connect(self._toggle_all_logs)
        log_top.addWidget(self.chk_all_logs)
        log_top.addStretch()
        log_hint = QLabel("Check files → Load Selected")
        log_hint.setFont(mono_font(8))
        log_hint.setObjectName("label_dim")
        log_top.addWidget(log_hint)
        log_lay.addLayout(log_top)
        self.log_list = QListWidget()
        self.log_list.setFont(mono_font())
        self.log_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        log_lay.addWidget(self.log_list)
        self.file_tabs.addTab(log_w, "LOG FILES")

        # DBC files tab
        dbc_w = QWidget()
        dbc_lay = QVBoxLayout(dbc_w)
        dbc_lay.setContentsMargins(4, 4, 4, 4)
        dbc_top = QHBoxLayout()
        self.chk_auto_dbc = QCheckBox("Auto-import all DBC files on load")
        self.chk_auto_dbc.setChecked(True)
        dbc_top.addWidget(self.chk_auto_dbc)
        dbc_top.addStretch()
        dbc_lay.addLayout(dbc_top)
        self.dbc_list = QListWidget()
        self.dbc_list.setFont(mono_font())
        dbc_lay.addWidget(self.dbc_list)
        self.file_tabs.addTab(dbc_w, "DBC FILES")

        # README tab
        readme_w = QWidget()
        readme_lay = QVBoxLayout(readme_w)
        readme_lay.setContentsMargins(4, 4, 4, 4)
        self.readme_text = QTextEdit()
        self.readme_text.setReadOnly(True)
        self.readme_text.setFont(mono_font(8))
        readme_lay.addWidget(self.readme_text)
        self.lbl_events = QLabel("")
        self.lbl_events.setFont(mono_font(8))
        self.lbl_events.setObjectName("label_amber")
        readme_lay.addWidget(self.lbl_events)
        self.file_tabs.addTab(readme_w, "README")

        lay.addWidget(self.file_tabs)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self.btn_load = QPushButton("Load Selected Logs + DBC")
        self.btn_load.setObjectName("btn_amber")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._load_selected)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_load)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_close)
        lay.addLayout(btn_row)

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _start_scan(self):
        if self._scanning:
            return   # prevent double-scan
        url = self.url_edit.text().strip()
        if not url:
            return
        info = parse_github_url(url)
        if not info:
            self._set_status(
                "Could not parse URL. Paste a full GitHub URL (https://github.com/owner/repo).",
                COLORS["error"],
            )
            return

        self._scanning = True
        self.btn_scan.setEnabled(False)
        self.btn_load.setEnabled(False)
        self._set_status(f"Scanning {info['owner']}/{info['repo']}…", COLORS["amber"])
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)

        # Stop any previous scan worker
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.quit()
            self._scan_worker.wait(2000)

        self._scan_worker = RepoScanWorker(info, self._token, parent=self)
        self._scan_worker.progress.connect(self._on_scan_progress, Qt.ConnectionType.QueuedConnection)
        self._scan_worker.done.connect(self._on_scan_done, Qt.ConnectionType.QueuedConnection)
        self._scan_worker.error.connect(self._on_scan_error, Qt.ConnectionType.QueuedConnection)
        self._scan_worker.start()

    def _on_scan_progress(self, msg: str):
        self._set_status(msg, COLORS["amber"])

    def _on_scan_done(self, data: dict):
        try:
            self._scanning = False
            self._scan_data = data
            meta   = data.get("meta", {})
            readme = data.get("readme", "")

            self.lbl_meta.setText(
                f"{meta.get('full_name', '')}  —  {meta.get('description', '')}  "
                f"[{meta.get('stargazers_count', 0)} ★]"
            )
            self._set_status(
                f"Scan complete: {len(data['logs'])} logs, "
                f"{len(data['dbcs'])} DBC files, "
                f"{'README found' if readme else 'no README'}",
                COLORS["green"],
            )
            self.progress_bar.setVisible(False)
            self.btn_scan.setEnabled(True)

            # Logs
            self.log_list.clear()
            for f in data["logs"]:
                item = QListWidgetItem(f"  {f['name']}  ({_fmt_size(f['size'])})")
                item.setData(Qt.ItemDataRole.UserRole, f)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setFont(mono_font())
                self.log_list.addItem(item)
            self.file_tabs.setTabText(0, f"LOG FILES ({len(data['logs'])})")

            # DBC
            self.dbc_list.clear()
            for f in data["dbcs"]:
                item = QListWidgetItem(f"  {f['name']}  ({f['path']})")
                item.setData(Qt.ItemDataRole.UserRole, f)
                item.setFont(mono_font())
                item.setForeground(QBrush(QColor(COLORS["accent"])))
                self.dbc_list.addItem(item)
            self.file_tabs.setTabText(1, f"DBC FILES ({len(data['dbcs'])})")

            # README
            self.readme_text.setPlainText(readme)
            from core.event_correlator import parse_annotations
            events = parse_annotations(readme)
            if events:
                self.lbl_events.setText(
                    f"{len(events)} annotated events found — used for AI correlation."
                )
                self.file_tabs.setTabText(2, f"README ({len(events)} events)")
            else:
                self.lbl_events.setText("No timestamp annotations found in README.")
                self.file_tabs.setTabText(2, "README")

            self.btn_load.setEnabled(True)

            # Emit readme FIRST so mainwindow stores it before meta fires
            self.readme_ready.emit(readme)
            self.repo_meta_ready.emit({
                "owner":       meta.get("owner", {}).get("login", ""),
                "repo":        meta.get("name", ""),
                "description": meta.get("description", ""),
                "readme":      readme,
                "branch":      data.get("branch", "main"),
            })

        except Exception as e:
            self._set_status(f"UI error after scan: {e}", COLORS["error"])
            self._scanning = False
            self.btn_scan.setEnabled(True)

    def _on_scan_error(self, err: str):
        self._scanning = False
        self._set_status(f"Error: {err}", COLORS["error"])
        self.progress_bar.setVisible(False)
        self.btn_scan.setEnabled(True)

    # ── Loading ───────────────────────────────────────────────────────────────

    def _toggle_all_logs(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.log_list.count()):
            self.log_list.item(i).setCheckState(state)

    def _load_selected(self):
        logs_to_dl = [
            self.log_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.log_list.count())
            if self.log_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        dbcs_to_dl = (
            self._scan_data.get("dbcs", [])
            if self.chk_auto_dbc.isChecked() else []
        )

        all_files = logs_to_dl + dbcs_to_dl
        if not all_files:
            QMessageBox.information(self, "Nothing Selected",
                                    "Check at least one log file to load.")
            return

        self.btn_load.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self._set_status(f"Downloading {len(all_files)} file(s)…", COLORS["amber"])
        self.progress_bar.setRange(0, len(all_files))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        if self._dl_worker and self._dl_worker.isRunning():
            self._dl_worker.abort()
            self._dl_worker.wait(2000)

        self._dl_worker = BatchDownloadWorker(all_files, self._token, parent=self)
        self._dl_worker.file_done.connect(self._on_file_done, Qt.ConnectionType.QueuedConnection)
        self._dl_worker.file_error.connect(self._on_file_error, Qt.ConnectionType.QueuedConnection)
        self._dl_worker.progress.connect(
            lambda d, t: self.progress_bar.setValue(d),
            Qt.ConnectionType.QueuedConnection,
        )
        self._dl_worker.all_done.connect(
            lambda paths: self._on_all_done(paths, logs_to_dl, dbcs_to_dl),
            Qt.ConnectionType.QueuedConnection,
        )
        self._dl_worker.start()

    def _on_file_done(self, path: str, local: str):
        self._set_status(f"Downloaded: {os.path.basename(local)}", COLORS["green"])

    def _on_file_error(self, path: str, err: str):
        self._set_status(f"Error — {os.path.basename(path)}: {err}", COLORS["error"])

    def _on_all_done(self, all_paths: list, logs_files: list, dbcs_files: list):
        try:
            self.progress_bar.setVisible(False)
            self.btn_scan.setEnabled(True)
            self._set_status(f"Downloaded {len(all_paths)} file(s).", COLORS["green"])

            log_names = {f["name"] for f in logs_files}
            dbc_names = {f["name"] for f in dbcs_files}
            log_paths = [p for p in all_paths if os.path.basename(p) in log_names]
            dbc_paths = [p for p in all_paths if os.path.basename(p) in dbc_names]

            if log_paths:
                self.logs_ready.emit(log_paths)
            if dbc_paths:
                self.dbcs_ready.emit(dbc_paths)

            # Close dialog only after signals have been emitted
            if log_paths or dbc_paths:
                self.accept()
            else:
                self.btn_load.setEnabled(True)
        except Exception as e:
            self._set_status(f"Error finalising download: {e}", COLORS["error"])
            self.btn_load.setEnabled(True)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Stop all background workers before closing."""
        errors = []
        for worker in [self._scan_worker, self._dl_worker]:
            if worker and worker.isRunning():
                if hasattr(worker, "abort"):
                    worker.abort()
                worker.quit()
                if not worker.wait(3000):
                    errors.append(type(worker).__name__)
        if errors:
            self._set_status(
                "Cannot close while workers are still stopping: "
                + ", ".join(errors),
                COLORS["error"],
            )
            event.ignore()
            return
        event.accept()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = COLORS["dim"]):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"color:{color}")


# ── Legacy shim ───────────────────────────────────────────────────────────────

class GitHubFetcherDialog(GitHubRepoDialog):
    file_ready = pyqtSignal(str)

    def __init__(self, repo_url: str = "", parent=None):
        super().__init__(initial_url=repo_url, parent=parent)
        self.logs_ready.connect(
            lambda paths: self.file_ready.emit(paths[0]) if paths else None
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.1f} MB"
