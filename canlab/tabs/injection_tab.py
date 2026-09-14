"""INJECTION tab — signal injection wizard, replay mode, trigger capture."""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QPushButton, QLabel,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QGroupBox, QSlider,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFileDialog,
    QProgressBar, QLineEdit, QMessageBox, QTextEdit,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QBrush

from theme import COLORS, mono_font
from core.state import get_state
from core.canid import normalize_id
from core.i18n import tr
from ui.lifecycle import LifecycleTabMixin


class InjectionTab(LifecycleTabMixin, QWidget):
    worker_attrs = (
        "_send_once_worker", "_inj_worker", "_replay_worker",
        "_scan_worker", "_fuzz_worker", "_seq_worker",
    )
    timer_attrs = ("_trigger_timer",)

    def stop_can_tasks(self):
        self.shutdown()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state           = get_state()
        self._send_once_worker = None
        self._inj_worker      = None
        self._replay_worker   = None
        self._trigger_timer   = QTimer()
        self._trigger_log     = []
        self._build_ui()
        self._state.dbc_updated.connect(self._refresh_signal_list)
        self._state.can_connected.connect(self._on_can_status)
        self._trigger_timer.setInterval(200)
        self._trigger_timer.timeout.connect(self._poll_triggers)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._build_inject_tab(),    tr("inject.tab.inject"))
        tabs.addTab(self._build_replay_tab(),    tr("inject.tab.replay"))
        tabs.addTab(self._build_trigger_tab(),   tr("inject.tab.triggers"))
        tabs.addTab(self._build_safety_tab(),    tr("inject.tab.safety"))
        tabs.addTab(self._build_fuzz_tab(),      tr("inject.tab.fuzz"))
        tabs.addTab(self._build_sequence_tab(),  tr("inject.tab.sequence"))
        outer.addWidget(tabs)

    # ── Inject sub-tab ────────────────────────────────────────────────────────

    def _build_inject_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.lbl_can_status = QLabel(tr("inject.can.disconnected_ph"))
        self.lbl_can_status.setFont(mono_font(8))
        self.lbl_can_status.setStyleSheet(f"color:{COLORS['error']}")
        lay.addWidget(self.lbl_can_status)

        # Signal picker
        sig_grp = QGroupBox(tr("inject.grp.signal"))
        sg = QHBoxLayout(sig_grp)
        sg.addWidget(QLabel(tr("inject.signal_colon")))
        self.sig_combo = QComboBox()
        self.sig_combo.setFont(mono_font())
        self.sig_combo.currentIndexChanged.connect(self._on_sig_changed)
        sg.addWidget(self.sig_combo, 1)
        lay.addWidget(sig_grp)

        # Value slider + spin
        val_grp = QGroupBox(tr("inject.grp.value"))
        vg = QHBoxLayout(val_grp)
        self.val_slider = QSlider(Qt.Orientation.Horizontal)
        self.val_slider.setMinimum(-10000)
        self.val_slider.setMaximum(10000)
        self.val_slider.setValue(0)
        self.val_slider.valueChanged.connect(
            lambda v: self.val_spin.setValue(v / 100.0)
        )
        vg.addWidget(self.val_slider, 1)
        self.val_spin = QDoubleSpinBox()
        self.val_spin.setRange(-100, 100)
        self.val_spin.setDecimals(2)
        self.val_spin.setFixedWidth(90)
        self.val_spin.valueChanged.connect(
            lambda v: self.val_slider.setValue(int(v * 100))
        )
        vg.addWidget(self.val_spin)
        self.lbl_unit = QLabel("")
        self.lbl_unit.setFont(mono_font(8))
        vg.addWidget(self.lbl_unit)
        lay.addWidget(val_grp)

        # Period + options
        opt_grp = QGroupBox(tr("inject.grp.options"))
        og = QHBoxLayout(opt_grp)
        og.addWidget(QLabel(tr("inject.period")))
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 5000)
        self.period_spin.setValue(10)
        og.addWidget(self.period_spin)
        self.chk_checksum = QCheckBox(tr("inject.chk.checksum"))
        self.chk_checksum.setChecked(True)
        self.chk_counter  = QCheckBox(tr("inject.chk.counter"))
        self.chk_counter.setChecked(True)
        og.addWidget(self.chk_checksum)
        og.addWidget(self.chk_counter)
        og.addStretch()
        lay.addWidget(opt_grp)

        # Send / Loop / Stop
        btn_row = QHBoxLayout()
        self.btn_send_once = QPushButton(tr("inject.btn.sendOnce"))
        self.btn_send_once.setObjectName("btn_green")
        self.btn_send_once.clicked.connect(self._send_once)
        self.btn_loop = QPushButton(tr("inject.btn.startLoop"))
        self.btn_loop.setObjectName("btn_amber")
        self.btn_loop.clicked.connect(self._toggle_loop)
        self.btn_stop_inj = QPushButton(tr("inject.btn.stop"))
        self.btn_stop_inj.clicked.connect(self._stop_injection)
        self.btn_stop_inj.setEnabled(False)
        for b in [self.btn_send_once, self.btn_loop, self.btn_stop_inj]:
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self.lbl_inj_status = QLabel("")
        self.lbl_inj_status.setFont(mono_font(8))
        lay.addWidget(self.lbl_inj_status)
        lay.addStretch()
        return w

    # ── Replay sub-tab ────────────────────────────────────────────────────────

    def _build_replay_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        file_row = QHBoxLayout()
        self.lbl_replay_file = QLabel(tr("inject.replay.noLog"))
        self.lbl_replay_file.setFont(mono_font(8))
        file_row.addWidget(self.lbl_replay_file, 1)
        btn_load = QPushButton(tr("inject.replay.loadLog"))
        btn_load.clicked.connect(self._load_replay_log)
        file_row.addWidget(btn_load)
        lay.addLayout(file_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel(tr("inject.replay.speed")))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)
        self.speed_spin.setSingleStep(0.5)
        self.speed_spin.setValue(1.0)
        speed_row.addWidget(self.speed_spin)
        self.chk_replay_loop = QCheckBox(tr("inject.replay.loop"))
        speed_row.addWidget(self.chk_replay_loop)
        speed_row.addStretch()
        lay.addLayout(speed_row)

        self.replay_scrubber = QSlider(Qt.Orientation.Horizontal)
        self.replay_scrubber.setMinimum(0)
        self.replay_scrubber.setValue(0)
        self.replay_scrubber.setStyleSheet(
            f"QSlider::groove:horizontal {{ height:6px; background:{COLORS['border']}; border-radius:3px; }}"
            f"QSlider::handle:horizontal {{ width:14px; height:14px; margin:-4px 0; "
            f"background:{COLORS['green']}; border-radius:7px; }}"
            f"QSlider::sub-page:horizontal {{ background:{COLORS['green']}; border-radius:3px; }}"
        )
        self.replay_scrubber.sliderReleased.connect(self._on_replay_scrub)
        lay.addWidget(self.replay_scrubber)

        btn_row2 = QHBoxLayout()
        self.btn_replay_start = QPushButton(tr("inject.replay.play"))
        self.btn_replay_start.setObjectName("btn_green")
        self.btn_replay_start.clicked.connect(self._start_replay)
        self.btn_replay_pause = QPushButton(tr("inject.replay.pause"))
        self.btn_replay_pause.clicked.connect(self._pause_replay)
        self.btn_replay_stop  = QPushButton(tr("inject.btn.stop"))
        self.btn_replay_stop.clicked.connect(self._stop_replay)
        for b in [self.btn_replay_start, self.btn_replay_pause, self.btn_replay_stop]:
            btn_row2.addWidget(b)
        lay.addLayout(btn_row2)

        self.lbl_replay_status = QLabel("")
        self.lbl_replay_status.setFont(mono_font(8))
        lay.addWidget(self.lbl_replay_status)
        lay.addStretch()

        self._replay_df = None
        return w

    # ── Trigger sub-tab ───────────────────────────────────────────────────────

    def _build_trigger_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(QLabel(tr("inject.trig.rulesTitle"), font=mono_font(9)))

        # Rule editor
        rule_grp = QGroupBox(tr("inject.trig.addEditRule"))
        rg = QHBoxLayout(rule_grp)
        rg.addWidget(QLabel(tr("inject.trig.id")))
        self.trig_id = QLineEdit()
        self.trig_id.setPlaceholderText(tr("inject.trig.idPh"))
        self.trig_id.setFixedWidth(80)
        rg.addWidget(self.trig_id)
        rg.addWidget(QLabel(tr("inject.trig.byte")))
        self.trig_byte = QSpinBox()
        self.trig_byte.setRange(0, 7)
        rg.addWidget(self.trig_byte)
        rg.addWidget(QLabel(tr("inject.trig.op")))
        self.trig_op = QComboBox()
        self.trig_op.addItems([">", "<", "==", "!=", "&", ">=", "<="])
        rg.addWidget(self.trig_op)
        rg.addWidget(QLabel(tr("inject.trig.val")))
        self.trig_val = QSpinBox()
        self.trig_val.setRange(0, 255)
        rg.addWidget(self.trig_val)
        rg.addWidget(QLabel(tr("inject.trig.label")))
        self.trig_label = QLineEdit()
        self.trig_label.setPlaceholderText(tr("inject.trig.labelPh"))
        rg.addWidget(self.trig_label, 1)
        btn_add_rule = QPushButton(tr("inject.trig.add"))
        btn_add_rule.clicked.connect(self._add_trigger_rule)
        rg.addWidget(btn_add_rule)
        lay.addWidget(rule_grp)

        # Rules table
        self.rules_table = QTableWidget(0, 6)
        self.rules_table.setHorizontalHeaderLabels(["ID", "Byte", "Op", "Value", "Label", "Del"])
        self.rules_table.setFont(mono_font())
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.verticalHeader().setDefaultSectionSize(20)
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rules_table.setMaximumHeight(140)
        lay.addWidget(self.rules_table)

        # Enable / start
        trig_ctl = QHBoxLayout()
        self.btn_trig_start = QPushButton(tr("inject.trig.enable"))
        self.btn_trig_start.setObjectName("btn_amber")
        self.btn_trig_start.clicked.connect(self._toggle_triggers)
        trig_ctl.addWidget(self.btn_trig_start)
        trig_ctl.addStretch()
        lay.addLayout(trig_ctl)

        lay.addWidget(QLabel(tr("inject.trig.logTitle"), font=mono_font(8)))
        self.trig_log_text = QTextEdit()
        self.trig_log_text.setReadOnly(True)
        self.trig_log_text.setFont(mono_font(8))
        lay.addWidget(self.trig_log_text)

        self._triggers_active = False
        return w

    # ── Signal list refresh ───────────────────────────────────────────────────

    def _refresh_signal_list(self):
        self.sig_combo.blockSignals(True)
        current = self.sig_combo.currentText()
        self.sig_combo.clear()
        for sig in self._state.dbc_signals:
            name = sig.get("signal_name", "?")
            mid  = sig.get("message_id", "?")
            self.sig_combo.addItem(f"0x{mid}  {name}", userData=sig)
        idx = self.sig_combo.findText(current)
        if idx >= 0:
            self.sig_combo.setCurrentIndex(idx)
        self.sig_combo.blockSignals(False)

    def _on_sig_changed(self, idx: int):
        sig = self.sig_combo.itemData(idx)
        if not sig:
            return
        unit = sig.get("unit", "")
        self.lbl_unit.setText(unit)
        lo = float(sig.get("min_val", -100))
        hi = float(sig.get("max_val", 100))
        self.val_spin.setRange(lo, hi)

    def _on_can_status(self, connected: bool):
        if connected:
            self.lbl_can_status.setText(tr("inject.can.connected"))
            self.lbl_can_status.setStyleSheet(f"color:{COLORS['green']}")
        else:
            self.lbl_can_status.setText(tr("inject.can.disconnected"))
            self.lbl_can_status.setStyleSheet(f"color:{COLORS['error']}")

    # ── Injection actions ─────────────────────────────────────────────────────

    def _get_bus(self):
        return self._state.can_bus

    def _get_selected_sig(self) -> dict | None:
        idx = self.sig_combo.currentIndex()
        if idx < 0:
            return None
        return self.sig_combo.itemData(idx)

    def _send_once(self):
        if self._send_once_worker and self._send_once_worker.isRunning():
            return
        sig = self._get_selected_sig()
        if not sig:
            QMessageBox.information(self, tr("inject.msgNoSig.title"),
                                    tr("inject.msgNoSig.text"))
            return
        bus = self._get_bus()
        if bus is None:
            QMessageBox.information(self, tr("inject.msgNoBus.title"),
                                    tr("inject.msgNoBus.text"))
            return
        from core.injection import pack_signal, hyundai_checksum
        from core.safety import is_armed
        if not is_armed():
            QMessageBox.warning(self, tr("inject.msgDisarmed.title"),
                                tr("inject.msgDisarmed.text"))
            return
        value = self.val_spin.value()
        data  = pack_signal(value, sig)
        try:
            mid = int(normalize_id(sig.get("message_id", "0")), 16)
        except (ValueError, TypeError):
            mid = 0
        if self.chk_checksum.isChecked() and len(data) > 0:
            data[-1] = hyundai_checksum(bytes(data), mid)
        extended = bool(sig.get("extended")) or mid > 0x7FF
        from core.can_operations import inject_once
        from ui.can_operation_worker import CanOperationWorker

        self.btn_send_once.setEnabled(False)
        worker = CanOperationWorker(
            inject_once, bus, mid, bytes(data), extended, parent=self
        )
        self._send_once_worker = worker
        worker.succeeded.connect(self._on_send_once_success)
        worker.failed.connect(self._on_send_once_error)
        worker.finished.connect(self._on_send_once_finished)
        worker.start()

    def _on_send_once_success(self, message):
        data = bytes(message.data)
        self.lbl_inj_status.setText(
            tr(
                "inject.sent",
                mid=message.arbitration_id,
                data=" ".join(f"{byte:02X}" for byte in data),
            )
        )
        self.lbl_inj_status.setStyleSheet(f"color:{COLORS['green']}")

    def _on_send_once_error(self, error: str):
        self.lbl_inj_status.setText(f"Error: {error}")
        self.lbl_inj_status.setStyleSheet(f"color:{COLORS['error']}")

    def _on_send_once_finished(self):
        self.btn_send_once.setEnabled(True)
        self._send_once_worker = None

    def _toggle_loop(self):
        if self._inj_worker and self._inj_worker.isRunning():
            self._stop_injection()
            return
        sig = self._get_selected_sig()
        if not sig:
            return
        bus = self._get_bus()
        if bus is None:
            QMessageBox.information(self, tr("inject.msgNoBus.title"),
                                    tr("inject.msgNoBus.text"))
            return
        from core.injection import InjectionWorker
        value  = self.val_spin.value()
        period = self.period_spin.value()
        self._inj_worker = InjectionWorker(
            bus=bus, sig=sig, value=value, period_ms=period,
            apply_checksum=self.chk_checksum.isChecked(),
            apply_counter=self.chk_counter.isChecked(),
        )
        self._inj_worker.tick.connect(
            lambda n, v: self.lbl_inj_status.setText(tr("inject.sending", n=n, v=v))
        )
        self._inj_worker.error.connect(
            lambda e: self.lbl_inj_status.setText(f"Error: {e}")
        )
        self._inj_worker.start()
        self.btn_loop.setText(tr("inject.btn.stopLoop"))
        self.btn_stop_inj.setEnabled(True)
        self.lbl_inj_status.setStyleSheet(f"color:{COLORS['amber']}")

    def _stop_injection(self):
        if self._inj_worker:
            self._inj_worker.stop()
            self._inj_worker = None
        self.btn_loop.setText(tr("inject.btn.startLoop"))
        self.btn_stop_inj.setEnabled(False)
        self.lbl_inj_status.setText(tr("inject.stopped"))
        self.lbl_inj_status.setStyleSheet(f"color:{COLORS['dim']}")

    # ── Replay actions ────────────────────────────────────────────────────────

    def _load_replay_log(self):
        from core.log_parser import parse_log_file
        path, _ = QFileDialog.getOpenFileName(
            self, tr("inject.replay.openTitle"), "",
            tr("inject.replay.fileFilter")
        )
        if not path:
            return
        try:
            self._replay_df = parse_log_file(path)
            self.lbl_replay_file.setText(
                tr("inject.replay.loaded",
                   name=path.split('/')[-1], n=len(self._replay_df))
            )
        except Exception as e:
            QMessageBox.critical(self, tr("inject.msgError.title"), str(e))

    def _start_replay(self):
        if self._replay_df is None or self._replay_df.empty:
            QMessageBox.information(self, tr("inject.replay.noLogTitle"),
                                    tr("inject.replay.msgLoad"))
            return
        bus = self._get_bus()
        if bus is None:
            QMessageBox.information(self, tr("inject.msgNoBus.title"),
                                    tr("inject.msgNoBus.text"))
            return
        from core.replay import ReplayWorker
        self._replay_worker = ReplayWorker(
            bus=bus,
            frames_df=self._replay_df,
            speed=self.speed_spin.value(),
            loop=self.chk_replay_loop.isChecked(),
        )
        self._replay_worker.tick.connect(self._on_replay_tick)
        self._replay_worker.loop_started.connect(
            lambda n: self.lbl_replay_status.setText(tr("inject.replay.loopIter", n=n))
        )
        self._replay_worker.finished.connect(self._on_replay_done)
        self._replay_worker.error.connect(
            lambda e: self.lbl_replay_status.setText(f"Error: {e}")
        )
        n = len(self._replay_df)
        self.replay_scrubber.setMaximum(max(1, n))
        self.replay_scrubber.setValue(0)
        self._replay_worker.start()
        self.lbl_replay_status.setText(tr("inject.replay.playing"))
        self.lbl_replay_status.setStyleSheet(f"color:{COLORS['amber']}")

    def _pause_replay(self):
        if self._replay_worker:
            if self._replay_worker.is_paused():
                self._replay_worker.resume()
                self.btn_replay_pause.setText(tr("inject.replay.pause"))
            else:
                self._replay_worker.pause()
                self.btn_replay_pause.setText(tr("inject.replay.resume"))

    def _stop_replay(self):
        if self._replay_worker:
            self._replay_worker.stop()
            self._replay_worker = None
        self.lbl_replay_status.setText(tr("inject.stopped"))
        self.lbl_replay_status.setStyleSheet(f"color:{COLORS['dim']}")

    def _on_replay_tick(self, current: int, total: int):
        self.replay_scrubber.blockSignals(True)
        self.replay_scrubber.setValue(current)
        self.replay_scrubber.blockSignals(False)
        self.lbl_replay_status.setText(
            tr("inject.replay.progress", current=current, total=total)
        )
        self._state.replay_tick.emit(current, total)

    def _on_replay_scrub(self):
        if self._replay_worker and self._replay_worker.isRunning():
            self._replay_worker.seek(self.replay_scrubber.value())

    def _on_replay_done(self):
        self.lbl_replay_status.setText(tr("inject.replay.complete"))
        self.lbl_replay_status.setStyleSheet(f"color:{COLORS['green']}")

    # ── Trigger actions ───────────────────────────────────────────────────────

    def _add_trigger_rule(self):
        rule = {
            "id":      normalize_id(self.trig_id.text()),
            "byte":    self.trig_byte.value(),
            "op":      self.trig_op.currentText(),
            "value":   self.trig_val.value(),
            "label":   self.trig_label.text().strip() or f"Rule{len(self._state.triggers)}",
            "enabled": True,
        }
        self._state.triggers.append(rule)
        self._refresh_rules_table()

    def _refresh_rules_table(self):
        rules = self._state.triggers
        self.rules_table.setRowCount(len(rules))
        for row, r in enumerate(rules):
            cells = [
                f"0x{r['id']}" if r['id'] else "*",
                str(r["byte"]),
                r["op"],
                str(r["value"]),
                r["label"],
                "✕",
            ]
            for ci, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setFont(mono_font())
                self.rules_table.setItem(row, ci, item)

    def _toggle_triggers(self):
        self._triggers_active = not self._triggers_active
        if self._triggers_active:
            self.btn_trig_start.setText(tr("inject.trig.disable"))
            self.btn_trig_start.setStyleSheet(f"color:{COLORS['error']}")
            self._trigger_timer.start()
        else:
            self.btn_trig_start.setText(tr("inject.trig.enable"))
            self.btn_trig_start.setStyleSheet("")
            self._trigger_timer.stop()
            try:
                self._state.frames_updated.disconnect(self._check_live_triggers)
            except Exception:
                pass

    def _check_live_triggers(self):
        from core.trigger import check_triggers
        df = self._state.frames_df
        if df.empty or not self._state.triggers:
            return
        last = df.tail(10)
        for _, row in last.iterrows():
            try:
                arb_id = int(str(row["ID"]), 16) if isinstance(row["ID"], str) else int(row["ID"])
                data   = bytes(
                    int(row[f"B{i}"]) if __import__("pandas").notna(row.get(f"B{i}")) else 0
                    for i in range(8)
                )
            except Exception:
                continue
            fired = check_triggers(self._state.triggers, arb_id, data)
            for rule in fired:
                msg = f"[{row.get('Timestamp',0):.3f}]  {rule['label']}  — 0x{arb_id:03X}"
                if not self._trigger_log or self._trigger_log[-1] != msg:
                    self._trigger_log.append(msg)
                    self._state.trigger_fired.emit(rule, row)
                    self._refresh_trigger_log()

    def _refresh_trigger_log(self):
        self.trig_log_text.setPlainText(
            "\n".join(reversed(self._trigger_log[-100:]))
        )

    def _poll_triggers(self):
        # Driven by the 200 ms timer while triggers are active. (Previously a
        # no-op, so the timer did nothing.)
        self._check_live_triggers()

    # ── Safety Scan sub-tab ───────────────────────────────────────────────────

    def _build_safety_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(QLabel(tr("inject.safety.title"), font=mono_font(9)))
        lay.addWidget(QLabel(tr("inject.safety.desc"), font=mono_font(8)))

        cfg_grp = QGroupBox(tr("inject.safety.grp"))
        cg = QHBoxLayout(cfg_grp)

        cg.addWidget(QLabel(tr("inject.signal_colon")))
        self.scan_sig_combo = QComboBox()
        self.scan_sig_combo.setFont(mono_font())
        cg.addWidget(self.scan_sig_combo, 1)

        cg.addWidget(QLabel(tr("inject.safety.steps")))
        self.scan_steps_spin = QSpinBox()
        self.scan_steps_spin.setRange(2, 200)
        self.scan_steps_spin.setValue(50)
        cg.addWidget(self.scan_steps_spin)

        cg.addWidget(QLabel(tr("inject.safety.delay")))
        self.scan_delay_spin = QSpinBox()
        self.scan_delay_spin.setRange(10, 5000)
        self.scan_delay_spin.setValue(200)
        cg.addWidget(self.scan_delay_spin)

        cg.addWidget(QLabel(tr("inject.safety.watchdog")))
        self.scan_watchdog_edit = QLineEdit("000")
        self.scan_watchdog_edit.setFixedWidth(60)
        cg.addWidget(self.scan_watchdog_edit)

        cg.addWidget(QLabel(tr("inject.safety.wdTimeout")))
        self.scan_wd_timeout = QSpinBox()
        self.scan_wd_timeout.setRange(100, 5000)
        self.scan_wd_timeout.setValue(500)
        cg.addWidget(self.scan_wd_timeout)

        lay.addWidget(cfg_grp)

        btn_row = QHBoxLayout()
        self.btn_scan_start = QPushButton(tr("inject.safety.start"))
        self.btn_scan_start.setObjectName("btn_green")
        self.btn_scan_start.clicked.connect(self._start_safety_scan)
        self.btn_scan_abort = QPushButton(tr("inject.safety.abort"))
        self.btn_scan_abort.clicked.connect(self._abort_safety_scan)
        self.btn_scan_abort.setEnabled(False)
        btn_row.addWidget(self.btn_scan_start)
        btn_row.addWidget(self.btn_scan_abort)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.scan_progress = QProgressBar()
        self.scan_progress.setValue(0)
        lay.addWidget(self.scan_progress)

        self.scan_log = QTextEdit()
        self.scan_log.setReadOnly(True)
        self.scan_log.setFont(mono_font(8))
        lay.addWidget(self.scan_log)

        self._scan_worker    = None
        self._scan_log_lines = []

        # Keep signal list in sync
        self._state.dbc_updated.connect(self._refresh_scan_signals)
        self._refresh_scan_signals()
        return w

    def _refresh_scan_signals(self):
        self.scan_sig_combo.blockSignals(True)
        self.scan_sig_combo.clear()
        for sig in self._state.dbc_signals:
            name = sig.get("signal_name", "?")
            mid  = sig.get("message_id", "?")
            self.scan_sig_combo.addItem(f"0x{mid}  {name}", userData=sig)
        self.scan_sig_combo.blockSignals(False)

    def _start_safety_scan(self):
        bus = self._get_bus()
        if bus is None:
            QMessageBox.information(self, tr("inject.msgNoBus.title"),
                                    tr("inject.msgNoBus.text"))
            return
        idx = self.scan_sig_combo.currentIndex()
        if idx < 0:
            return
        sig = self.scan_sig_combo.itemData(idx)
        if not sig:
            return

        try:
            wd_id = int(self.scan_watchdog_edit.text().strip(), 16)
        except ValueError:
            wd_id = 0

        min_val = float(sig.get("min_val", 0))
        max_val = float(sig.get("max_val", 255))

        from core.safety_scanner import SafetyScanWorker
        self._scan_worker = SafetyScanWorker(
            bus=bus, sig=sig,
            min_val=min_val, max_val=max_val,
            steps=self.scan_steps_spin.value(),
            step_delay_ms=self.scan_delay_spin.value(),
            watchdog_id=wd_id,
            watchdog_timeout_ms=self.scan_wd_timeout.value(),
        )
        self._scan_worker.step_done.connect(self._on_scan_step)
        self._scan_worker.cutout.connect(self._on_scan_cutout)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(lambda e: self._scan_log_append(f"ERROR: {e}"))

        steps = self.scan_steps_spin.value()
        self.scan_progress.setMaximum(steps)
        self.scan_progress.setValue(0)
        self._scan_log_lines.clear()
        self.scan_log.clear()

        self._scan_worker.start()
        self.btn_scan_start.setEnabled(False)
        self.btn_scan_abort.setEnabled(True)

    def _abort_safety_scan(self):
        if self._scan_worker:
            self._scan_worker.stop()
            self._scan_worker = None
        self._scan_log_append(tr("inject.safety.aborted"))
        self.btn_scan_start.setEnabled(True)
        self.btn_scan_abort.setEnabled(False)

    def _on_scan_step(self, value: float, data: bytes):
        n = self.scan_progress.value() + 1
        self.scan_progress.setValue(n)
        hex_str = " ".join(f"{b:02X}" for b in data)
        self._scan_log_append(f"Step {n:3d}  val={value:8.3f}  [{hex_str}]")

    def _on_scan_cutout(self, value: float, reason: str):
        self._scan_log_append(
            tr("inject.safety.cutout", value=value, reason=reason)
        )
        self.scan_log.setStyleSheet(f"color:{COLORS['error']}")
        self._state.safety_cutout.emit(value, reason)
        self.btn_scan_start.setEnabled(True)
        self.btn_scan_abort.setEnabled(False)

    def _on_scan_finished(self):
        self._scan_log_append(tr("inject.safety.done"))
        self.scan_log.setStyleSheet(f"color:{COLORS['green']}")
        self.btn_scan_start.setEnabled(True)
        self.btn_scan_abort.setEnabled(False)

    def _scan_log_append(self, msg: str):
        self._scan_log_lines.append(msg)
        self.scan_log.setPlainText("\n".join(self._scan_log_lines[-200:]))
        self.scan_log.verticalScrollBar().setValue(
            self.scan_log.verticalScrollBar().maximum()
        )

    # ── Fuzz sub-tab ──────────────────────────────────────────────────────────

    def _build_fuzz_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(QLabel(tr("inject.fuzz.title"), font=mono_font(9)))
        lay.addWidget(QLabel(tr("inject.fuzz.desc"), font=mono_font(8)))

        cfg_grp = QGroupBox(tr("inject.fuzz.grp"))
        cg = QHBoxLayout(cfg_grp)

        cg.addWidget(QLabel(tr("inject.fuzz.targetId")))
        self.fuzz_id_edit = QLineEdit("000")
        self.fuzz_id_edit.setFixedWidth(70)
        cg.addWidget(self.fuzz_id_edit)

        cg.addWidget(QLabel("DLC:"))
        self.fuzz_dlc_spin = QSpinBox()
        self.fuzz_dlc_spin.setRange(1, 8)
        self.fuzz_dlc_spin.setValue(8)
        cg.addWidget(self.fuzz_dlc_spin)

        cg.addWidget(QLabel(tr("inject.fuzz.strategy")))
        self.fuzz_strategy_combo = QComboBox()
        self.fuzz_strategy_combo.addItems(["boundary", "random", "mutation"])
        cg.addWidget(self.fuzz_strategy_combo)

        cg.addWidget(QLabel(tr("inject.fuzz.rate")))
        self.fuzz_rate_spin = QDoubleSpinBox()
        self.fuzz_rate_spin.setRange(0.1, 100.0)
        self.fuzz_rate_spin.setValue(10.0)
        cg.addWidget(self.fuzz_rate_spin)

        cg.addWidget(QLabel(tr("inject.fuzz.maxIter")))
        self.fuzz_maxiter_spin = QSpinBox()
        self.fuzz_maxiter_spin.setRange(0, 100000)
        self.fuzz_maxiter_spin.setValue(0)
        cg.addWidget(self.fuzz_maxiter_spin)

        lay.addWidget(cfg_grp)

        btn_row = QHBoxLayout()
        self.btn_fuzz_start = QPushButton(tr("inject.fuzz.start"))
        self.btn_fuzz_start.setObjectName("btn_amber")
        self.btn_fuzz_start.clicked.connect(self._start_fuzz)
        self.btn_fuzz_stop = QPushButton(tr("inject.btn.stop"))
        self.btn_fuzz_stop.clicked.connect(self._stop_fuzz)
        self.btn_fuzz_stop.setEnabled(False)
        btn_row.addWidget(self.btn_fuzz_start)
        btn_row.addWidget(self.btn_fuzz_stop)
        btn_row.addStretch()
        self.lbl_fuzz_count = QLabel(tr("inject.fuzz.sentCount", n=0))
        self.lbl_fuzz_count.setFont(mono_font(8))
        btn_row.addWidget(self.lbl_fuzz_count)
        lay.addLayout(btn_row)

        self.fuzz_log = QTextEdit()
        self.fuzz_log.setReadOnly(True)
        self.fuzz_log.setFont(mono_font(8))
        lay.addWidget(self.fuzz_log)

        self._fuzz_worker    = None
        self._fuzz_log_lines = []
        return w

    def _start_fuzz(self):
        bus = self._get_bus()
        if bus is None:
            QMessageBox.information(self, tr("inject.msgNoBus.title"),
                                    tr("inject.msgNoBus.text"))
            return
        try:
            target_id = int(self.fuzz_id_edit.text().strip(), 16)
        except ValueError:
            QMessageBox.warning(self, tr("inject.fuzz.invalidId.title"),
                                tr("inject.fuzz.invalidId.text"))
            return

        from core.fuzzer import FuzzWorker
        self._fuzz_worker = FuzzWorker(
            bus=bus,
            target_id=target_id,
            dlc=self.fuzz_dlc_spin.value(),
            strategy=self.fuzz_strategy_combo.currentText(),
            rate_hz=self.fuzz_rate_spin.value(),
            max_iter=self.fuzz_maxiter_spin.value(),
        )
        self._fuzz_worker.hit.connect(self._on_fuzz_hit)
        self._fuzz_worker.progress.connect(
            lambda n: self.lbl_fuzz_count.setText(tr("inject.fuzz.sentCount", n=n))
        )
        self._fuzz_worker.error.connect(lambda e: self._fuzz_log_append(f"ERROR: {e}"))
        self._fuzz_worker.finished.connect(self._on_fuzz_done)

        self._fuzz_log_lines.clear()
        self.fuzz_log.clear()
        self._fuzz_worker.start()
        self._state.fuzz_running = True
        self.btn_fuzz_start.setEnabled(False)
        self.btn_fuzz_stop.setEnabled(True)

    def _stop_fuzz(self):
        if self._fuzz_worker:
            self._fuzz_worker.stop()
            self._fuzz_worker = None
        self._state.fuzz_running = False
        self.btn_fuzz_start.setEnabled(True)
        self.btn_fuzz_stop.setEnabled(False)
        self._fuzz_log_append(tr("inject.fuzz.stopped"))

    def _on_fuzz_hit(self, id_hex: str, data: bytes, ts: float):
        hex_str = " ".join(f"{b:02X}" for b in data)
        self._fuzz_log_append(f"[{ts:.3f}]  0x{id_hex}  [{hex_str}]")

    def _on_fuzz_done(self):
        self._state.fuzz_running = False
        self.btn_fuzz_start.setEnabled(True)
        self.btn_fuzz_stop.setEnabled(False)
        self._fuzz_log_append(tr("inject.fuzz.complete"))

    def _fuzz_log_append(self, msg: str):
        self._fuzz_log_lines.append(msg)
        self.fuzz_log.setPlainText("\n".join(self._fuzz_log_lines[-300:]))
        self.fuzz_log.verticalScrollBar().setValue(
            self.fuzz_log.verticalScrollBar().maximum()
        )

    # ── Test Sequence sub-tab ─────────────────────────────────────────────────

    def _build_sequence_tab(self) -> QWidget:
        from PyQt6.QtWidgets import QSplitter
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(QLabel(tr("inject.seq.desc"), font=mono_font(8)))

        # ── Step editor ───────────────────────────────────────────────────────
        editor_grp = QGroupBox(tr("inject.seq.addStep"))
        eg = QVBoxLayout(editor_grp)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel(tr("inject.seq.type"), font=mono_font(8)))
        self.seq_type = QComboBox()
        self.seq_type.addItems(["INJECT", "WAIT", "ASSERT", "RECORD"])
        self.seq_type.setFont(mono_font(8))
        type_row.addWidget(self.seq_type)
        type_row.addWidget(QLabel(tr("inject.trig.label"), font=mono_font(8)))
        self.seq_label = QLineEdit()
        self.seq_label.setFont(mono_font(8))
        self.seq_label.setPlaceholderText(tr("inject.seq.labelPh"))
        type_row.addWidget(self.seq_label, 1)
        eg.addLayout(type_row)

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel(tr("inject.seq.msgId"), font=mono_font(8)))
        self.seq_msg_id = QLineEdit("0A6")
        self.seq_msg_id.setFixedWidth(60)
        self.seq_msg_id.setFont(mono_font(8))
        param_row.addWidget(self.seq_msg_id)
        param_row.addWidget(QLabel(tr("inject.trig.byte"), font=mono_font(8)))
        self.seq_byte = QSpinBox()
        self.seq_byte.setRange(0, 7)
        param_row.addWidget(self.seq_byte)
        param_row.addWidget(QLabel(tr("inject.seq.value"), font=mono_font(8)))
        self.seq_value = QSpinBox()
        self.seq_value.setRange(0, 65535)
        param_row.addWidget(self.seq_value)
        param_row.addWidget(QLabel(tr("inject.seq.min"), font=mono_font(8)))
        self.seq_min = QDoubleSpinBox()
        self.seq_min.setRange(-1e6, 1e6)
        param_row.addWidget(self.seq_min)
        param_row.addWidget(QLabel(tr("inject.seq.max"), font=mono_font(8)))
        self.seq_max = QDoubleSpinBox()
        self.seq_max.setRange(-1e6, 1e6)
        self.seq_max.setValue(255)
        param_row.addWidget(self.seq_max)
        eg.addLayout(param_row)

        btn_row = QHBoxLayout()
        btn_add = QPushButton(tr("inject.seq.add"))
        btn_add.setObjectName("btn_green")
        btn_add.clicked.connect(self._seq_add_step)
        btn_del = QPushButton(tr("inject.seq.remove"))
        btn_del.clicked.connect(self._seq_remove_step)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        eg.addLayout(btn_row)
        lay.addWidget(editor_grp)

        # ── Step list ─────────────────────────────────────────────────────────
        self.seq_table = QTableWidget(0, 5)
        self.seq_table.setHorizontalHeaderLabels(["#", "Type", "Label", "Params", ""])
        self.seq_table.setFont(mono_font(8))
        self.seq_table.verticalHeader().setVisible(False)
        self.seq_table.verticalHeader().setDefaultSectionSize(20)
        self.seq_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.seq_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.seq_table.setMaximumHeight(180)
        lay.addWidget(QLabel(tr("inject.seq.stepsTitle"), font=mono_font(8)))
        lay.addWidget(self.seq_table)
        self._seq_steps: list = []

        # ── Run controls ──────────────────────────────────────────────────────
        run_row = QHBoxLayout()
        self.btn_seq_run  = QPushButton(tr("inject.seq.run"))
        self.btn_seq_run.setObjectName("btn_green")
        self.btn_seq_run.clicked.connect(self._seq_run)
        self.btn_seq_stop = QPushButton(tr("inject.btn.seqStop"))
        self.btn_seq_stop.clicked.connect(self._seq_stop)
        self.btn_seq_stop.setEnabled(False)
        self.btn_seq_clear_steps = QPushButton(tr("inject.seq.clear"))
        self.btn_seq_clear_steps.clicked.connect(self._seq_clear)
        run_row.addWidget(self.btn_seq_run)
        run_row.addWidget(self.btn_seq_stop)
        run_row.addWidget(self.btn_seq_clear_steps)
        run_row.addStretch()
        lay.addLayout(run_row)

        self.seq_log = QTextEdit()
        self.seq_log.setReadOnly(True)
        self.seq_log.setFont(mono_font(8))
        lay.addWidget(QLabel(tr("inject.seq.runLog"), font=mono_font(8)))
        lay.addWidget(self.seq_log)

        self._seq_worker = None
        return w

    def _seq_add_step(self):
        from core.test_sequence import TestStep, StepType
        stype = StepType(self.seq_type.currentText())
        step  = TestStep(
            step_type    = stype,
            label        = self.seq_label.text().strip(),
            msg_id       = self.seq_msg_id.text().strip().upper(),
            byte_idx     = self.seq_byte.value(),
            value        = self.seq_value.value(),
            wait_ms      = self.seq_value.value(),
            assert_msg_id = self.seq_msg_id.text().strip().upper(),
            assert_byte  = self.seq_byte.value(),
            assert_min   = self.seq_min.value(),
            assert_max   = self.seq_max.value(),
        )
        self._seq_steps.append(step)
        self._seq_refresh_table()

    def _seq_remove_step(self):
        row = self.seq_table.currentRow()
        if 0 <= row < len(self._seq_steps):
            self._seq_steps.pop(row)
            self._seq_refresh_table()

    def _seq_clear(self):
        self._seq_steps.clear()
        self._seq_refresh_table()

    def _seq_refresh_table(self):
        self.seq_table.setRowCount(len(self._seq_steps))
        for i, step in enumerate(self._seq_steps):
            if step.step_type.value == "WAIT":
                params = f"wait {step.wait_ms} ms"
            elif step.step_type.value == "INJECT":
                params = f"0x{step.msg_id} B{step.byte_idx}=0x{step.value:02X}"
            else:
                params = (f"0x{step.assert_msg_id} B{step.assert_byte} "
                         f"[{step.assert_min},{step.assert_max}]")
            cells = [str(i), step.step_type.value, step.label, params, ""]
            color = {"INJECT": COLORS["amber"], "WAIT": COLORS["dim"],
                     "ASSERT": COLORS["green"], "RECORD": COLORS["text"]}.get(
                         step.step_type.value, COLORS["text"])
            for ci, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setFont(mono_font(8))
                if ci == 1:
                    item.setForeground(QBrush(QColor(color)))
                self.seq_table.setItem(i, ci, item)

    def _seq_run(self):
        bus = self._state.can_bus
        if bus is None:
            QMessageBox.warning(self, tr("inject.msgNoBus.title"),
                                tr("inject.seq.msgConnect"))
            return
        if not self._seq_steps:
            QMessageBox.information(self, tr("inject.seq.emptyTitle"),
                                    tr("inject.seq.msgEmpty"))
            return
        from core.test_sequence import TestSequenceWorker
        self._seq_worker = TestSequenceWorker(list(self._seq_steps), bus)
        self._seq_worker.step_started.connect(
            lambda idx: self.seq_log.append(f"→ Step {idx}: {self._seq_steps[idx].step_type.value}…")
        )
        self._seq_worker.step_completed.connect(
            lambda idx, ok, msg: self.seq_log.append(
                ("✓ " if ok else "✗ ") + msg
            )
        )
        self._seq_worker.sequence_finished.connect(self._seq_finished)
        self._seq_worker.error.connect(lambda e: self.seq_log.append(f"ERROR: {e}"))
        self.btn_seq_run.setEnabled(False)
        self.btn_seq_stop.setEnabled(True)
        self.seq_log.append("=== Sequence started ===")
        self._seq_worker.start()

    def _seq_stop(self):
        if self._seq_worker:
            self._seq_worker.stop()

    def _seq_finished(self, passed: bool, log: list):
        self.btn_seq_run.setEnabled(True)
        self.btn_seq_stop.setEnabled(False)
        result = "PASSED" if passed else "FAILED"
        color  = COLORS["green"] if passed else COLORS["error"]
        self.seq_log.append(f'<span style="color:{color}">═══ Sequence {result} ═══</span>')
