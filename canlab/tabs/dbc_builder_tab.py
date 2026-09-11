import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QGridLayout, QTextEdit,
    QFileDialog, QMessageBox, QHeaderView, QTableWidget, QTableWidgetItem,
    QMenu,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from theme import COLORS, mono_font
from core.state import get_state
from core.i18n import tr
from core.canid import normalize_id
from core.dbc_manager import signals_to_dbc_string, load_dbc, decode_frame, validate_signals

BYTE_COLS = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7"]


class DBCBuilderTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state        = get_state()
        self._selected_idx = -1
        self._build_ui()
        self._state.dbc_updated.connect(self._refresh_list)

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: signal list
        left = QWidget()
        left.setFixedWidth(220)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(4, 4, 4, 4)
        left_lay.setSpacing(4)

        lbl = QLabel(tr("dbc.signals"))
        lbl.setObjectName("label_dim")
        lbl.setFont(mono_font(8))
        left_lay.addWidget(lbl)

        self.sig_list = QListWidget()
        self.sig_list.setFont(mono_font())
        self.sig_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sig_list.customContextMenuRequested.connect(self._list_context_menu)
        self.sig_list.currentRowChanged.connect(self._on_list_select)
        left_lay.addWidget(self.sig_list)

        toolbar_btns = QHBoxLayout()
        btn_new = QPushButton(tr("dbc.btn_new"))
        btn_new.clicked.connect(self._new_signal)
        btn_imp = QPushButton(tr("dbc.btn_import"))
        btn_imp.clicked.connect(self._import_dbc)
        toolbar_btns.addWidget(btn_new)
        toolbar_btns.addWidget(btn_imp)
        left_lay.addLayout(toolbar_btns)

        toolbar2 = QHBoxLayout()
        btn_exp = QPushButton(tr("dbc.btn_export_dbc"))
        btn_exp.setObjectName("btn_green")
        btn_exp.clicked.connect(self._export_dbc)
        btn_val = QPushButton(tr("dbc.btn_validate"))
        btn_val.clicked.connect(self._validate)
        toolbar2.addWidget(btn_exp)
        toolbar2.addWidget(btn_val)
        left_lay.addLayout(toolbar2)

        btn_auto = QPushButton(tr("dbc.btn_auto_build"))
        btn_auto.setToolTip(tr("dbc.tooltip_auto_build"))
        btn_auto.clicked.connect(self._auto_build)
        left_lay.addWidget(btn_auto)

        btn_xref = QPushButton(tr("dbc.btn_cross_ref"))
        btn_xref.setToolTip(tr("dbc.tooltip_cross_ref"))
        btn_xref.clicked.connect(self._cross_ref)
        left_lay.addWidget(btn_xref)

        btn_op_dbc = QPushButton(tr("dbc.btn_export_openpilot"))
        btn_op_dbc.setToolTip(tr("dbc.tooltip_export_openpilot"))
        btn_op_dbc.clicked.connect(self._export_openpilot_dbc)
        left_lay.addWidget(btn_op_dbc)

        btn_lua = QPushButton(tr("dbc.btn_export_lua"))
        btn_lua.setToolTip(tr("dbc.tooltip_export_lua"))
        btn_lua.clicked.connect(self._export_lua_dissector)
        left_lay.addWidget(btn_lua)

        btn_matrix = QPushButton(tr("dbc.btn_import_matrix"))
        btn_matrix.setToolTip(tr("dbc.tooltip_import_matrix"))
        btn_matrix.clicked.connect(self._import_can_matrix)
        left_lay.addWidget(btn_matrix)

        btn_arxml_imp = QPushButton(tr("dbc.btn_import_arxml"))
        btn_arxml_imp.setToolTip(tr("dbc.tooltip_import_arxml"))
        btn_arxml_imp.clicked.connect(self._import_arxml)
        left_lay.addWidget(btn_arxml_imp)

        btn_arxml_exp = QPushButton(tr("dbc.btn_export_arxml"))
        btn_arxml_exp.setToolTip(tr("dbc.tooltip_export_arxml"))
        btn_arxml_exp.clicked.connect(self._export_arxml)
        left_lay.addWidget(btn_arxml_exp)

        btn_candbpp = QPushButton(tr("dbc.btn_export_candbpp"))
        btn_candbpp.setToolTip(tr("dbc.tooltip_export_candbpp"))
        btn_candbpp.clicked.connect(self._export_candbpp)
        left_lay.addWidget(btn_candbpp)

        splitter.addWidget(left)

        # Right: editor + preview
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(6, 6, 6, 6)
        right_lay.setSpacing(6)

        lbl_ed = QLabel(tr("dbc.signal_editor"))
        lbl_ed.setObjectName("label_dim")
        lbl_ed.setFont(mono_font(8))
        right_lay.addWidget(lbl_ed)

        grid = QGridLayout()
        grid.setSpacing(4)

        def add_row(row, label1, widget1, label2=None, widget2=None):
            grid.addWidget(QLabel(label1), row, 0)
            grid.addWidget(widget1, row, 1)
            if label2:
                grid.addWidget(QLabel(label2), row, 2)
                grid.addWidget(widget2, row, 3)

        self.f_msg_id   = QLineEdit(); self.f_msg_id.setPlaceholderText(tr("dbc.ph_msg_id"))
        self.f_msg_name = QLineEdit(); self.f_msg_name.setPlaceholderText(tr("dbc.ph_msg_name"))
        add_row(0, tr("dbc.lbl_msg_id"), self.f_msg_id, tr("dbc.lbl_msg_name"), self.f_msg_name)

        self.f_sig_name = QLineEdit(); self.f_sig_name.setPlaceholderText(tr("dbc.ph_sig_name"))
        self.f_unit     = QLineEdit(); self.f_unit.setPlaceholderText(tr("dbc.ph_unit"))
        add_row(1, tr("dbc.lbl_sig_name"), self.f_sig_name, tr("dbc.lbl_unit"), self.f_unit)

        self.f_start_bit = QLineEdit("0")
        self.f_length    = QLineEdit("8")
        add_row(2, tr("dbc.lbl_start_bit"), self.f_start_bit, tr("dbc.lbl_length"), self.f_length)

        self.f_byte_order = QComboBox()
        self.f_byte_order.addItems(["little", "big"])
        self.f_val_type = QComboBox()
        self.f_val_type.addItems(["unsigned", "signed"])
        add_row(3, tr("dbc.lbl_byte_order"), self.f_byte_order, tr("dbc.lbl_val_type"), self.f_val_type)

        self.f_scale  = QLineEdit("1.0")
        self.f_offset = QLineEdit("0.0")
        add_row(4, tr("dbc.lbl_scale"), self.f_scale, tr("dbc.lbl_offset"), self.f_offset)

        self.f_min = QLineEdit("0")
        self.f_max = QLineEdit("255")
        add_row(5, tr("dbc.lbl_min"), self.f_min, tr("dbc.lbl_max"), self.f_max)

        self.f_desc = QLineEdit()
        self.f_desc.setPlaceholderText(tr("dbc.ph_desc"))
        grid.addWidget(QLabel(tr("dbc.lbl_desc")), 6, 0)
        grid.addWidget(self.f_desc, 6, 1, 1, 3)

        right_lay.addLayout(grid)

        # Notes layer
        notes_lbl = QLabel(tr("dbc.signal_notes"))
        notes_lbl.setObjectName("label_dim")
        notes_lbl.setFont(mono_font(8))
        right_lay.addWidget(notes_lbl)
        self.f_notes = QTextEdit()
        self.f_notes.setPlaceholderText(tr("dbc.ph_notes"))
        self.f_notes.setMaximumHeight(60)
        self.f_notes.setFont(mono_font(8))
        right_lay.addWidget(self.f_notes)

        save_row = QHBoxLayout()
        btn_save = QPushButton(tr("dbc.btn_save_signal"))
        btn_save.setObjectName("btn_green")
        btn_save.clicked.connect(self._save_signal)
        btn_test = QPushButton(tr("dbc.btn_test_decode"))
        btn_test.clicked.connect(self._test_decode)
        save_row.addWidget(btn_save)
        save_row.addWidget(btn_test)
        save_row.addStretch()
        right_lay.addLayout(save_row)

        # Live decode preview
        lbl_prev = QLabel(tr("dbc.live_preview"))
        lbl_prev.setObjectName("label_dim")
        lbl_prev.setFont(mono_font(8))
        right_lay.addWidget(lbl_prev)

        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(["Timestamp", "Raw Bytes", "Decoded Value", "Unit"])
        self.preview_table.setFont(mono_font())
        self.preview_table.verticalHeader().setDefaultSectionSize(20)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setMaximumHeight(120)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        right_lay.addWidget(self.preview_table)

        self.status_label = QLabel("")
        self.status_label.setFont(mono_font(8))
        right_lay.addWidget(self.status_label)

        # Bit editor panel
        from tabs.widgets.bit_editor import BitGridWidget
        self.bit_editor = BitGridWidget()
        self.bit_editor.selection_changed.connect(self._on_bit_selection)
        right_lay.addWidget(self.bit_editor)

        right_lay.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([220, 780])
        lay.addWidget(splitter)

    def _refresh_list(self):
        self.sig_list.clear()
        for sig in self._state.dbc_signals:
            mid  = sig.get("message_id", "?")
            name = sig.get("signal_name", "?")
            item = QListWidgetItem(f"0x{mid}  {name}")
            item.setForeground(QBrush(QColor(COLORS["green"])))
            self.sig_list.addItem(item)

    def _on_list_select(self, idx: int):
        self._selected_idx = idx
        if 0 <= idx < len(self._state.dbc_signals):
            sig = self._state.dbc_signals[idx]
            self._populate_form(sig)
            self._update_preview(idx)
            # Load notes
            key = self._note_key(sig)
            self.f_notes.setPlainText(self._state.notes_by_signal.get(key, ""))
            # Update bit editor with last frame data for this message
            self._update_bit_editor(sig)

    def _populate_form(self, sig: dict):
        self.f_msg_id.setText(sig.get("message_id", ""))
        self.f_msg_name.setText(sig.get("message_name", ""))
        self.f_sig_name.setText(sig.get("signal_name", ""))
        self.f_unit.setText(sig.get("unit", ""))
        self.f_start_bit.setText(str(sig.get("start_bit", 0)))
        self.f_length.setText(str(sig.get("length", 8)))
        self.f_byte_order.setCurrentText(sig.get("byte_order", "little"))
        self.f_val_type.setCurrentText(sig.get("value_type", "unsigned"))
        self.f_scale.setText(str(sig.get("scale", 1.0)))
        self.f_offset.setText(str(sig.get("offset", 0.0)))
        self.f_min.setText(str(sig.get("min_val", 0)))
        self.f_max.setText(str(sig.get("max_val", 255)))
        self.f_desc.setText(sig.get("description", ""))

    def _collect_form(self) -> dict:
        return {
            "message_id":   normalize_id(self.f_msg_id.text()) or "000",
            "message_name": self.f_msg_name.text() or "MSG",
            "signal_name":  self.f_sig_name.text() or "Signal",
            "unit":         self.f_unit.text(),
            "start_bit":    int(self.f_start_bit.text() or "0"),
            "length":       int(self.f_length.text() or "8"),
            "byte_order":   self.f_byte_order.currentText(),
            "value_type":   self.f_val_type.currentText(),
            "scale":        float(self.f_scale.text() or "1.0"),
            "offset":       float(self.f_offset.text() or "0.0"),
            "min_val":      float(self.f_min.text() or "0"),
            "max_val":      float(self.f_max.text() or "255"),
            "description":  self.f_desc.text(),
        }

    def _new_signal(self):
        self._selected_idx = -1
        for w in [self.f_msg_id, self.f_msg_name, self.f_sig_name, self.f_unit,
                  self.f_desc]:
            w.clear()
        self.f_start_bit.setText("0")
        self.f_length.setText("8")
        self.f_scale.setText("1.0")
        self.f_offset.setText("0.0")
        self.f_min.setText("0")
        self.f_max.setText("255")
        # Pre-fill with selected ID
        if self._state.selected_id:
            self.f_msg_id.setText(self._state.selected_id)
            self.f_msg_name.setText(f"MSG_{self._state.selected_id}")

    def _save_signal(self):
        sig = self._collect_form()
        errors = validate_signals([sig])
        if errors:
            self.status_label.setText("  ".join(errors))
            self.status_label.setStyleSheet(f"color:{COLORS['error']}")
            return
        # Save notes
        note_text = self.f_notes.toPlainText().strip()
        key = self._note_key(sig)
        if note_text:
            self._state.notes_by_signal[key] = note_text
        elif key in self._state.notes_by_signal:
            del self._state.notes_by_signal[key]
        if note_text:
            self._state.note_updated.emit(key)

        if self._selected_idx >= 0:
            self._state.update_dbc_signal(self._selected_idx, sig)
        else:
            self._state.add_dbc_signal(sig)
        self.status_label.setText(tr("dbc.status_saved"))
        self.status_label.setStyleSheet(f"color:{COLORS['green']}")

    def _test_decode(self):
        sig = self._collect_form()
        mid = sig["message_id"]
        frames = self._state.get_frames_for_id(mid)
        if frames.empty:
            self.status_label.setText(tr("dbc.msg_no_frames"))
            return
        self._populate_preview_with_sig(sig, frames.tail(5))

    def _update_preview(self, idx: int):
        sig = self._state.dbc_signals[idx]
        mid = sig.get("message_id", "")
        frames = self._state.get_frames_for_id(mid)
        if not frames.empty:
            self._populate_preview_with_sig(sig, frames.tail(5))

    def _populate_preview_with_sig(self, sig: dict, frames: pd.DataFrame):
        self.preview_table.setRowCount(len(frames))
        for row_idx, (_, row) in enumerate(frames.iterrows()):
            byte_data = bytes(
                int(row[f"B{i}"]) if pd.notna(row.get(f"B{i}")) else 0
                for i in range(8)
            )
            decoded = decode_frame([sig], sig["message_id"], byte_data)
            sname = sig.get("signal_name", "")
            val_str = str(round(float(decoded[sname]), 4)) if sname in decoded else "?"
            raw_str = " ".join(f"{b:02X}" for b in byte_data)

            items = [
                QTableWidgetItem(f"{row.get('Timestamp',0):.3f}"),
                QTableWidgetItem(raw_str),
                QTableWidgetItem(val_str),
                QTableWidgetItem(sig.get("unit", "")),
            ]
            for ci, item in enumerate(items):
                item.setFont(mono_font())
                if ci == 2:
                    item.setForeground(QBrush(QColor(COLORS["green"])))
                self.preview_table.setItem(row_idx, ci, item)

    def _export_dbc(self):
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("dbc.title_export_dbc"), "decoded.dbc", "DBC (*.dbc)")
        if path:
            try:
                dbc_str = signals_to_dbc_string(self._state.dbc_signals)
                with open(path, "w") as f:
                    f.write(dbc_str)
                self.status_label.setText(tr("dbc.status_exported", path=path))
                self.status_label.setStyleSheet(f"color:{COLORS['green']}")
            except Exception as e:
                QMessageBox.critical(self, tr("dbc.title_export_error"), str(e))

    def _import_dbc(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("dbc.title_import_dbc"), "", "DBC (*.dbc)")
        if path:
            try:
                sigs = load_dbc(path)
                for sig in sigs:
                    self._state.add_dbc_signal(sig)
                self.status_label.setText(tr("dbc.status_imported", n=len(sigs)))
                self.status_label.setStyleSheet(f"color:{COLORS['green']}")
            except Exception as e:
                QMessageBox.critical(self, tr("dbc.title_import_error"), str(e))

    def _validate(self):
        errors = validate_signals(self._state.dbc_signals)
        if errors:
            QMessageBox.warning(self, tr("dbc.title_validation_errors"), "\n".join(errors))
        else:
            QMessageBox.information(self, tr("dbc.title_valid"), tr("dbc.msg_all_valid"))

    def _list_context_menu(self, pos):
        idx = self.sig_list.currentRow()
        if idx < 0:
            return
        menu = QMenu(self)
        menu.addAction(tr("dbc.menu_edit"),      lambda: self._on_list_select(idx))
        menu.addAction(tr("dbc.menu_duplicate"), lambda: self._duplicate(idx))
        menu.addAction(tr("dbc.menu_delete"),    lambda: self._delete(idx))
        menu.exec(self.sig_list.mapToGlobal(pos))

    def _duplicate(self, idx: int):
        if 0 <= idx < len(self._state.dbc_signals):
            import copy
            sig = copy.deepcopy(self._state.dbc_signals[idx])
            sig["signal_name"] += "_copy"
            self._state.add_dbc_signal(sig)

    def _delete(self, idx: int):
        self._state.remove_dbc_signal(idx)

    def _auto_build(self):
        from core.auto_dbc import build_from_analyzer
        if self._state.frames_df.empty:
            QMessageBox.information(self, tr("dbc.title_no_data"), tr("dbc.msg_load_can_log"))
            return
        signals = build_from_analyzer(self._state)
        existing_ids = {s.get("message_id") for s in self._state.dbc_signals}
        added = 0
        for sig in signals:
            if sig["message_id"] not in existing_ids:
                self._state.add_dbc_signal(sig)
                added += 1
        self.status_label.setText(tr("dbc.status_auto_built", n=added))
        self.status_label.setStyleSheet(f"color:{COLORS['green']}")

    def _note_key(self, sig: dict) -> str:
        return f"{sig.get('message_id','?')}/{sig.get('signal_name','?')}"

    def _update_bit_editor(self, sig: dict):
        mid = sig.get("message_id", "")
        frames = self._state.get_frames_for_id(mid)
        if not frames.empty:
            last = frames.iloc[-1]
            data = bytes(
                int(last.get(f"B{i}", 0) or 0) for i in range(8)
            )
            self.bit_editor.set_data(data)
        start = int(sig.get("start_bit", 0))
        length = int(sig.get("length", 8))
        self.bit_editor.set_selection(start, length)

    def _on_bit_selection(self, start_bit: int, length: int, little_endian: bool):
        self.f_start_bit.setText(str(start_bit))
        self.f_length.setText(str(length))
        self.f_byte_order.setCurrentText("little" if little_endian else "big")

    def _export_openpilot_dbc(self):
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dbc.title_export_openpilot"), "openpilot.dbc", "DBC (*.dbc)"
        )
        if not path:
            return
        try:
            from core.dbc_manager import export_opendbc
            from core.openpilot_export import HYUNDAI_MSG_META
            dbc_str = export_opendbc(self._state.dbc_signals, HYUNDAI_MSG_META)
            with open(path, "w") as f:
                f.write(dbc_str)
            self.status_label.setText(tr("dbc.status_export_openpilot", path=path))
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_export_error"), str(e))

    def _export_lua_dissector(self):
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dbc.title_export_lua"), "canlab_dbc.lua", "Lua (*.lua)"
        )
        if not path:
            return
        try:
            from core.lua_exporter import signals_to_lua_dissector
            lua_str = signals_to_lua_dissector(self._state.dbc_signals)
            with open(path, "w") as f:
                f.write(lua_str)
            self.status_label.setText(tr("dbc.status_export_lua", path=path))
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_export_error"), str(e))

    def _cross_ref(self):
        from core.opendbc_matcher import scan
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_cross_ref"))
            return
        repo_ctx = None
        if self._state.repo_info:
            repo_ctx = {**self._state.repo_info, "readme": self._state.repo_readme}
        matches = scan(self._state, repo_ctx)
        self._state.opendbc_matches = matches
        if matches:
            lines = [f"{k} → {v['file']} (msg:{v['msg']})" for k, v in matches.items()]
            QMessageBox.information(self, tr("dbc.title_opendbc_matches"), "\n".join(lines))
        else:
            QMessageBox.information(self, tr("dbc.title_opendbc"), tr("dbc.msg_no_matches"))

    def _import_can_matrix(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dbc.title_import_matrix"), "",
            tr("dbc.filter_spreadsheets") + ";;All Files (*)"
        )
        if not path:
            return
        try:
            from core.can_matrix_parser import parse_can_matrix
            signals = parse_can_matrix(path)
            if not signals:
                QMessageBox.warning(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals_file"))
                return
            for sig in signals:
                self._state.add_dbc_signal(sig)
            # Rebuild cantools cache
            from core.dbc_manager import build_db_from_signals
            build_db_from_signals(self._state.dbc_signals)
            self.status_label.setText(
                tr("dbc.status_imported_matrix", n=len(signals))
            )
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_import_error"), str(e))

    def _import_arxml(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dbc.title_import_arxml"), "",
            tr("dbc.filter_arxml") + ";;All Files (*)"
        )
        if not path:
            return
        try:
            from core.arxml_import import parse_arxml
            signals = parse_arxml(path)
            if not signals:
                QMessageBox.warning(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals_arxml"))
                return
            for sig in signals:
                self._state.add_dbc_signal(sig)
            from core.dbc_manager import build_db_from_signals
            build_db_from_signals(self._state.dbc_signals)
            self.status_label.setText(tr("dbc.status_imported_arxml", n=len(signals)))
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_import_error"), str(e))

    def _export_arxml(self):
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals_export"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dbc.title_export_arxml"), "canlab_export.arxml",
            tr("dbc.filter_arxml_export") + ";;XML (*.xml)"
        )
        if not path:
            return
        try:
            from core.arxml_export import to_arxml_string
            arxml = to_arxml_string(self._state.dbc_signals)
            with open(path, "w", encoding="utf-8") as f:
                f.write(arxml)
            self.status_label.setText(tr("dbc.status_export_arxml", path=path))
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_export_error"), str(e))

    def _export_candbpp(self):
        if not self._state.dbc_signals:
            QMessageBox.information(self, tr("dbc.title_empty"), tr("dbc.msg_no_signals_export"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dbc.title_export_candbpp"), "canlab_export.dbc", "DBC (*.dbc)"
        )
        if not path:
            return
        try:
            from core.candbpp_export import to_candbpp_string
            dbc_str = to_candbpp_string(self._state.dbc_signals)
            with open(path, "w", encoding="utf-8") as f:
                f.write(dbc_str)
            self.status_label.setText(tr("dbc.status_export_candbpp", path=path))
            self.status_label.setStyleSheet(f"color:{COLORS['green']}")
        except Exception as e:
            QMessageBox.critical(self, tr("dbc.title_export_error"), str(e))
