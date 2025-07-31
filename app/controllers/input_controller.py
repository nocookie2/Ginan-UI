# app/controllers/input_controller.py

from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, List

from PySide6.QtCore import QObject, Signal, Qt, QDateTime
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QFormLayout,
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QDateTimeEdit,
    QInputDialog,
    QMessageBox,
    QComboBox,
)

from app.models.rinex_extractor import RinexExtractor

class InputController(QObject):
    """
    Front-end controller

    Owns all UI input flows:
        - Select RNX file and Output directory
        - Extract RINEX metadata and apply to UI
        - Populate / handle config widgets (Mode, Constellations, etc.)
        - Open small dialogs for selecting some values
        - Show config file and run PEA processing

    Emits:
        ready(rnx_path: str, output_path: str)

        when both RNX and output dir are set.
    """

    ready = Signal(str, str) # rnx_path, output_path
    pea_ready = Signal() # emitted when PEA processing should start

    def __init__(self, ui, parent_window):
        super().__init__()
        self.ui = ui
        self.parent = parent_window

        self.rnx_file: str = ""
        self.output_dir: str = ""
        
        # Config file path
        self.default_config_path = "app/resources/Yaml/default_config.yaml"
        self.config_path = None

        ### Wire: file selection buttons ###
        self.ui.observationsButton.clicked.connect(self.load_rnx_file)
        self.ui.outputButton.clicked.connect(self.load_output_dir)

        # Initial states
        self.ui.outputButton.setEnabled(False) # output disabled until RNX chosen
        self.ui.processButton.setEnabled(False) # process enabled later by MainWindow

        ### Bind: configuration drop-downs / UIs ###

        # Single-choice combos (populated on open)
        self._bind_combo(self.ui.Mode, self._get_mode_items)
        self._bind_combo(self.ui.PPP_provider, self._get_ppp_provider_items)
        self._bind_combo(self.ui.PPP_series, self._get_ppp_series_items)

        # Constellations: multi-select with checkboxes, mirror to constellationsValue label
        self._bind_multiselect_combo(
            self.ui.Constellations_2,
            self._get_constellations_items,
            self.ui.constellationsValue,
            placeholder="Constellations",
        )

        # On selection of single-choice combos, mirror value to right-side labels
        self.ui.Mode.activated.connect(
            lambda idx: self._on_select(self.ui.Mode, self.ui.modeValue, "Mode", idx)
        )
        self.ui.Antenna_type.activated.connect(
            lambda idx: self._on_select(self.ui.Antenna_type, self.ui.antennaTypeValue, "Antenna type", idx)
        )
        self.ui.PPP_provider.activated.connect(
            lambda idx: self._on_select(self.ui.PPP_provider, self.ui.pppProviderValue, "PPP provider", idx)
        )
        self.ui.PPP_series.activated.connect(
            lambda idx: self._on_select(self.ui.PPP_series, self.ui.pppSeriesValue, "PPP series", idx)
        )

        # Receiver/Antenna types: allow free-text via popup prompts
        self._enable_free_text_for_receiver_and_antenna()

        # Antenna offset dialog
        self.ui.antennaOffsetButton.clicked.connect(self._open_antenna_offset_dialog)
        self.ui.antennaOffsetButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ui.antennaOffsetValue.setText("0.0, 0.0, 0.0")

        # Time window & Data interval dialogs
        self.ui.timeWindowButton.clicked.connect(self._open_time_window_dialog)
        self.ui.timeWindowButton.setCursor(Qt.CursorShape.PointingHandCursor)

        self.ui.dataIntervalButton.clicked.connect(self._open_data_interval_dialog)
        self.ui.dataIntervalButton.setCursor(Qt.CursorShape.PointingHandCursor)

        # Show config and Run PEA buttons
        self.ui.showConfigButton.clicked.connect(self.on_show_config)
        self.ui.showConfigButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ui.processButton.clicked.connect(self.on_run_pea)

    #region File Selection + Metadata Extraction

    def load_rnx_file(self):
        """Pick an RNX file, extract metadata, apply to UI, and enable next steps."""
        path = self._select_rnx_file(self.parent)
        if not path:
            return

        self.rnx_file = path
        self.ui.terminalTextEdit.append(f"RNX selected: {path}")
        self.ui.outputButton.setEnabled(True)  # allow choosing output dir next

        # Extract information from submitted .RNX file and reflect it in the UI
        try:
            extractor = RinexExtractor(path)
            result = extractor.extract_rinex_data(path)

            # Update UI fields directly
            self.ui.constellationsValue.setText(result["constellations"])
            self.ui.timeWindowValue.setText(f"{result['start_epoch']} to {result['end_epoch']}")
            self.ui.dataIntervalValue.setText(f"{result['epoch_interval']} s")
            self.ui.receiverTypeValue.setText(result["receiver_type"])
            self.ui.antennaTypeValue.setText(result["antenna_type"])
            self.ui.antennaOffsetValue.setText(", ".join(map(str, result["antenna_offset"])))

            # Align left-side combos to extracted values where applicable
            self._set_combobox_by_value(self.ui.Receiver_type, result["receiver_type"])
            self._set_combobox_by_value(self.ui.Antenna_type, result["antenna_type"])

            self.ui.terminalTextEdit.append(".RNX file metadata extracted and applied to UI fields")
        except Exception as e:
            self.ui.terminalTextEdit.append(f"Error extracting RNX metadata: {e}")
            print(f"Error extracting RNX metadata: {e}")

        # If both are available already (user might have chosen output first), emit
        if self.rnx_file and self.output_dir:
            self.ready.emit(self.rnx_file, self.output_dir)

    def load_output_dir(self):
        """Pick an output directory; if RNX is also set, emit ready."""
        path = self._select_output_dir(self.parent)
        if not path:
            return

        self.output_dir = path
        self.ui.terminalTextEdit.append(f"Output directory selected: {path}")

        # MainWindow owns when to enable processButton. This controller exposes a helper if needed.
        self.enable_process_button()

        if self.rnx_file:
            self.ready.emit(self.rnx_file, self.output_dir)

    def enable_process_button(self):
        """Public helper so other components can enable the Process button without knowing UI internals."""
        self.ui.processButton.setEnabled(True)

    #endregion

    #region Multi-Selectors Assigning (A.K.A. Combo Plumbing)

    def _on_select(self, combo: QComboBox, label, title: str, index: int):
        """Mirror combo selection to label and reset combo's placeholder text."""
        value = combo.itemText(index)
        label.setText(value)

        combo.clear()
        combo.addItem(title)

    def _bind_combo(self, combo: QComboBox, items_func: Callable[[], List[str]]):
        """
        Populate a single-choice QComboBox each time it opens.
        Keeps the left combo visually clean while moving the chosen value to the right label.
        """
        combo._old_showPopup = combo.showPopup

        def new_showPopup():
            combo.clear()
            combo.setEditable(True)
            combo.lineEdit().setAlignment(Qt.AlignCenter)
            for item in items_func():
                combo.addItem(item)
            combo.setEditable(False)
            combo._old_showPopup()

        combo.showPopup = new_showPopup

    def _bind_multiselect_combo(
            self,
            combo: QComboBox,
            items_func: Callable[[], List[str]],
            mirror_label,
            placeholder: str,
    ):
        """
        On open, replace the combo's model with checkbox items and mirror all checked items
        as comma-separated text to mirror_label.
        """
        combo._old_showPopup = combo.showPopup

        def show_popup():
            model = QStandardItemModel(combo)
            for txt in items_func():
                it = QStandardItem(txt)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setData(Qt.Unchecked, Qt.CheckStateRole)
                model.appendRow(it)

            def on_item_changed(_item: QStandardItem):
                selected = [
                    model.item(r, 0).text()
                    for r in range(model.rowCount())
                    if model.item(r, 0).checkState() == Qt.Checked
                ]
                mirror_label.setText(", ".join(selected) if selected else placeholder)

            model.itemChanged.connect(on_item_changed)
            combo.setModel(model)
            combo._old_showPopup()

        combo.showPopup = show_popup
        combo.clear()
        combo.addItem(placeholder)
        mirror_label.setText(placeholder)

    def _enable_free_text_for_receiver_and_antenna(self):
        """Allow entering custom Receiver/Antenna types via popup prompt."""

        # Receiver type free text
        def _ask_receiver_type():
            text, ok = QInputDialog.getText(self.ui.Receiver_type, "Receiver Type", "Enter receiver type:")
            if ok and text:
                self.ui.Receiver_type.clear()
                self.ui.Receiver_type.addItem(text)
                self.ui.receiverTypeValue.setText(text)

        self.ui.Receiver_type.showPopup = _ask_receiver_type
        self.ui.receiverTypeValue.setText("")

        # Antenna type free text
        def _ask_antenna_type():
            text, ok = QInputDialog.getText(self.ui.Antenna_type, "Antenna Type", "Enter antenna type:")
            if ok and text:
                self.ui.Antenna_type.clear()
                self.ui.Antenna_type.addItem(text)
                self.ui.antennaTypeValue.setText(text)

        self.ui.Antenna_type.showPopup = _ask_antenna_type
        self.ui.antennaTypeValue.setText("")

    #endregion

    #region Small Dialogs

    def _open_antenna_offset_dialog(self):
        dlg = QDialog(self.ui.antennaOffsetButton)
        dlg.setWindowTitle("Antenna Offset")

        # Try to parse existing U, N, E values
        try:
            u0, n0, e0 = [float(x.strip()) for x in self.ui.antennaOffsetValue.text().split(",")]
        except Exception:
            u0 = n0 = e0 = 0.0

        form = QFormLayout(dlg)

        sb_u = QDoubleSpinBox(dlg)
        sb_u.setRange(-9999, 9999)
        sb_u.setDecimals(1)
        sb_u.setValue(u0)
        sb_n = QDoubleSpinBox(dlg)
        sb_n.setRange(-9999, 9999)
        sb_n.setDecimals(1)
        sb_n.setValue(n0)
        sb_e = QDoubleSpinBox(dlg)
        sb_e.setRange(-9999, 9999)
        sb_e.setDecimals(1)
        sb_e.setValue(e0)

        form.addRow("U:", sb_u)
        form.addRow("N:", sb_n)
        form.addRow("E:", sb_e)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK", dlg)
        cancel_btn = QPushButton("Cancel", dlg)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        form.addRow(btn_row)

        ok_btn.clicked.connect(lambda: self._set_antenna_offset(sb_u, sb_n, sb_e, dlg))
        cancel_btn.clicked.connect(dlg.reject)

        dlg.exec()

    def _set_antenna_offset(self, sb_u: QDoubleSpinBox, sb_n: QDoubleSpinBox, sb_e: QDoubleSpinBox, dlg: QDialog):
        u, n, e = sb_u.value(), sb_n.value(), sb_e.value()
        self.ui.antennaOffsetValue.setText(f"{u}, {n}, {e}")
        dlg.accept()

    def _open_time_window_dialog(self):
        dlg = QDialog(self.ui.timeWindowValue)
        dlg.setWindowTitle("Select start / end time")

        vbox = QVBoxLayout(dlg)
        start_edit = QDateTimeEdit(QDateTime.currentDateTime(), dlg)
        end_edit = QDateTimeEdit(QDateTime.currentDateTime(), dlg)

        start_edit.setCalendarPopup(True)
        end_edit.setCalendarPopup(True)
        start_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        end_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        vbox.addWidget(start_edit)
        vbox.addWidget(end_edit)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK", dlg)
        cancel_btn = QPushButton("Cancel", dlg)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        vbox.addLayout(btn_row)

        ok_btn.clicked.connect(lambda: self._set_time_window(start_edit, end_edit, dlg))
        cancel_btn.clicked.connect(dlg.reject)

        dlg.exec()

    def _set_time_window(self, start_edit: QDateTimeEdit, end_edit: QDateTimeEdit, dlg: QDialog):
        if end_edit.dateTime() < start_edit.dateTime():
            QMessageBox.warning(dlg, "Time error", "End time cannot be earlier than start time.\nPlease select again.")
            return

        s = start_edit.dateTime().toString("yyyy-MM-dd_HH:mm:ss")
        e = end_edit.dateTime().toString("yyyy-MM-dd_HH:mm:ss")
        self.ui.timeWindowValue.setText(f"{s} to {e}")
        dlg.accept()

    def _open_data_interval_dialog(self):
        val, ok = QInputDialog.getInt(
            self.ui.dataIntervalValue,
            "Data interval",
            "Input interval (seconds):",
            1,
            1,
            999_999,
        )
        if ok:
            # Keep "X s" to match RNX metadata format and existing parsing in MainController
            self.ui.dataIntervalValue.setText(f"{val} s")

    #endregion

    #region Config and PEA Processing

    def _generate_modified_config_yaml(self, config_parameters):
        """
        Args:
            config_parameters (dict): modified config parameters directory
                example: {
                    'setting1': 'value1',
                    'setting2': 'value2',
                    'nested_config': {
                        'subsetting1': 'subvalue1'
                    }
                }
        
        Returns:
            str: generated YAML file path, should return the path in the format of /resources/Yaml/xxxx.yaml
        
        TODO: backend please implement the following functions:
        1. receive config_parameters parameter
        2. convert the parameters to YAML format
        3. save to /resources/Yaml/ directory
        4. file name format can be: timestamp.yaml, config_v1.yaml, etc.
        5. return the complete file path
        
        Note: the current UI version uses the hardcode path /resources/Yaml/default_config.yaml
        """
        # TODO: backend please implement functions here.
        return self.default_config_path

    def on_show_config(self):
        """
        Show config file
        Open the fixed path YAML config file: /resources/Yaml/default_config.yaml
        No longer need to manually select files
        """
        print("opening default config file...")

        file_path = self.default_config_path
        
        if not os.path.exists(file_path):
            QMessageBox.warning(
                None,
                "File not found",
                f"The file {file_path} does not exist."
            )
            return
        
        if not (file_path.endswith(".yml") or file_path.endswith(".yaml")):
            QMessageBox.warning(
                None,
                "File Format Error",
                f"The file is not a valid YAML file:\n{file_path}"
            )
            return

        self.config_path = file_path
        self.on_open_config_in_editor(self.config_path)

    def on_open_config_in_editor(self, file_path):
        """
        Open the config file in an external editor
        
        Args:
            file_path (str): the complete path of the YAML config file
        """
        import subprocess
        import platform

        if not file_path:
            QMessageBox.warning(
                None,
                "No File Path",
                "No config file path specified."
            )
            return
        
        if not os.path.exists(file_path):
            QMessageBox.critical(
                None,
                "File Not Found",
                f"Config file not found:\n{file_path}"
            )
            return
        
        try:
            abs_path = os.path.abspath(file_path)
            print(f"Opening config file: {abs_path}")
            
            # Open the file with the appropriate method for the operating system
            if platform.system() == "Windows":
                os.startfile(abs_path)
                print("Opened with default Windows application")
                
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", abs_path])
                print("Opened with default macOS application")
                
            else:  # Linux and other Unix-like systems
                subprocess.run(["xdg-open", abs_path])
                print("Opened with default Linux application")
                
        except Exception as e:
            error_message = f"Cannot open config file:\n{file_path}\n\nError: {str(e)}"
            print(f"Error: {error_message}")
            QMessageBox.critical(
                None,
                "Error Opening File",
                error_message
            )

    def on_run_pea(self):
        """Run PEA processing with validation"""
        raw = self.ui.timeWindowValue.text()
        print(raw)
        try:
            start_str, end_str = raw.split("to")
            start = datetime.strptime(start_str.strip(), "%Y-%m-%d_%H:%M:%S")
            end = datetime.strptime(end_str.strip(), "%Y-%m-%d_%H:%M:%S")
        except ValueError:
            QMessageBox.warning(
                None,
                "Format error",
                "Time window must be in the format:\n"
                "YYYY-MM-DD_HH:MM:SS to YYYY-MM-DD_HH:MM:SS"
            )
            return

        if start > end:
            QMessageBox.warning(
                None,
                "Time error",
                "Start time cannot be later than end time."
            )
            return

        if not getattr(self, "config_path", None):
            QMessageBox.warning(
                None,
                "No config file",
                "Please click Show config and select a YAML file first."
            )
            return

        self.ui.terminalTextEdit.clear()
        self.ui.terminalTextEdit.append("Basic validation passed, starting PEA execution...")
        self.pea_ready.emit()

    #endregion

    #region Utility Functions

    @staticmethod
    def _set_combobox_by_value(combo: QComboBox, value: str):
        """Find 'value' in a combo and set it if present."""
        if value is None:
            return
        idx = combo.findText(value)
        if idx != -1:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _select_rnx_file(parent) -> str:
        """Select RINEX file using file dialog"""
        path, _ = QFileDialog.getOpenFileName(
            parent, 
            "Select RINEX Observation File", 
            "", 
            "RINEX Observation Files (*.rnx *.rnx.gz);;All Files (*.*)"
        )
        return path or ""

    @staticmethod
    def _select_output_dir(parent) -> str:
        """Select output directory using file dialog"""
        path = QFileDialog.getExistingDirectory(parent, "Select Output Directory")
        return path or ""

    #endregion

    #region Statics

    @staticmethod
    def _get_mode_items() -> List[str]:
        return ["Static", "Kinematic", "Dynamic"]

    @staticmethod
    def _get_constellations_items() -> List[str]:
        return ["GPS", "GAL", "GLO", "BDS", "QZS"]

    @staticmethod
    def _get_ppp_provider_items() -> List[str]:
        return ["COD", "GFZ", "JPL", "ESA", "IGS", "WUH"]

    @staticmethod
    def _get_ppp_series_items() -> List[str]:
        return ["RAP", "ULT", "FIN"]

    #endregion