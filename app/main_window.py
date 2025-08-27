import os
import glob
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QMainWindow, QDialog, QVBoxLayout, QPushButton, QComboBox
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.models.execution import Execution, GENERATED_YAML
from app.utils.find_executable import get_pea_exec
from app.utils.ui_compilation import compile_ui
from app.controllers.input_controller import InputController
from app.controllers.visualisation_controller import VisualisationController
from pathlib import Path
import numpy as np
from app.utils.gn_functions import GPSDate
from app.utils.cddis_credentials import validate_netrc as gui_validate_netrc
from app.utils.download_products_https import create_cddis_file


def setup_main_window():
    # Whilst developing, we compile every time :)
    # try :
    #    from app.views.main_window_ui import Ui_MainWindow
    # except ModuleNotFoundError:
    compile_ui()
    from app.views.main_window_ui import Ui_MainWindow
    window = Ui_MainWindow()
    return window


class FullHtmlDialog(QDialog):
    def __init__(self, file_path: str):
        super().__init__()
        self.setWindowTitle("Full HTML View")
        layout = QVBoxLayout(self)
        webview = QWebEngineView(self)
        webview.setUrl(QUrl.fromLocalFile(file_path))
        layout.addWidget(webview)
        self.resize(800, 600)


class MainWindow(QMainWindow):
    """
    Top-level QMainWindow that is essential for the app to run. It:
        - Builds the UI
        - Composes InputController and VisualisationController
        - Owns the Process action to start PEA
        - Listens for InputController.ready(rnx_path, output_path)
        - Invokes InputController to generate PPP outputs and drive visualisation.
    """

    def __init__(self):
        super().__init__()

        # —— UI Initialization —— #
        self.ui = setup_main_window()
        self.ui.setupUi(self)

        # —— Controllers —— #
        self.execution = Execution(executable=get_pea_exec())
        self.inputCtrl = InputController(self.ui, self, self.execution)
        self.visCtrl = VisualisationController(self.ui, self)

        # Can remove?: external base URL for live server previews
        # self.visCtrl.set_external_base_url("http://127.0.0.1:5501/")

        # Keep a simple list if you need to iterate or manage controllers
        self.controllers = [self.inputCtrl, self.visCtrl]

        # RNX/Output selection readiness
        self.inputCtrl.ready.connect(self.on_files_ready)

        # PEA processing readiness
        self.inputCtrl.pea_ready.connect(self._on_process_clicked)

        # —— State variables —— #
        self.rnx_file: str | None = None
        self.output_dir: str | None = None

        # —— Signal connections —— #
        # Note: processButton.clicked is now handled by InputController for basic validation
        # MainWindow will handle the actual PEA processing through a different mechanism

        # —— Visualisation helpers —— #
        self.openInBrowserBtn = QPushButton("Open in Browser", self)
        self.ui.rightLayout.addWidget(self.openInBrowserBtn)
        self.visCtrl.bind_open_button(self.openInBrowserBtn)

        self.visSelector = QComboBox(self)
        self.ui.rightLayout.addWidget(self.visSelector)
        self.visCtrl.bind_selector(self.visSelector)

    def on_files_ready(self, rnx_path: str, out_path: str):
        """Store file paths received from InputController."""
        self.rnx_file = rnx_path
        self.output_dir = out_path

    # region Processing / Visualisation
    def _on_process_clicked(self):
        """Generate CDDIS.list via HTTPS, then stop (skip legacy test/visualisation path)."""

        # 基本校验
        if not getattr(self, "rnx_file", None):
            self.ui.terminalTextEdit.append("Please select a RNX file first.")
            return
        if not getattr(self, "output_dir", None):
            self.ui.terminalTextEdit.append("Please select an output directory first.")
            return

        # === [用 HTTPS 生成 CDDIS.list] 开始 ===
        try:
            # 1) 校验 Earthdata 凭据；若缺失则弹出你们已有的“CDDIS Credentials”对话框
            ok, where = gui_validate_netrc()
            if not ok:
                self.ui.terminalTextEdit.append("No Earthdata credentials. Opening CDDIS Credentials dialog…")
                self.ui.cddisCredentialsButton.click()  # 打开现有凭据弹窗
                ok, where = gui_validate_netrc()  # 用户保存后再校验
                if not ok:
                    self.ui.terminalTextEdit.append(f"❌ Credentials still invalid: {where}")
                    return
            self.ui.terminalTextEdit.append(f"✅ Credentials OK: {where}")

            # 2) 取时间窗（extract_ui_values 需要 rnx 路径；返回 dataclass）
            inputs = self.inputCtrl.extract_ui_values(self.rnx_file)
            try:
                start_s = inputs.start_epoch
                end_s = inputs.end_epoch
            except AttributeError:
                # 少数分支若返回 dict 也兼容
                start_s = inputs["start_epoch"]
                end_s = inputs["end_epoch"]

            # 3) 统一成字符串并转为 GPSDate（把空格/下划线替换成 'T' 供 numpy 识别）
            start_s = str(start_s)
            end_s = str(end_s)
            start_gps = GPSDate(np.datetime64(start_s.replace('_', ' ').replace(' ', 'T')))
            end_gps = GPSDate(np.datetime64(end_s.replace('_', ' ').replace(' ', 'T')))

            # 4) 目标目录：app/models
            target_dir = Path(__file__).resolve().parent / "models"
            target_dir.mkdir(parents=True, exist_ok=True)

            # 5) 生成清单（HTTPS）
            self.ui.terminalTextEdit.append(f"Generating CDDIS.list for {start_s} ~ {end_s} …")
            create_cddis_file(target_dir, start_gps, end_gps)

            # 6) 反馈并**提前结束**（不再执行下面旧的“Skipping PEA/Testing plot …”分支）
            out_file = target_dir / "CDDIS.list"
            try:
                n_lines = sum(1 for _ in open(out_file, "r", encoding="utf-8"))
            except Exception:
                n_lines = "?"
            self.ui.terminalTextEdit.append(f"✅ CDDIS.list generated: {out_file} (lines: {n_lines})")
            return

        except Exception as e:
            self.ui.terminalTextEdit.append(f"❌ Failed to generate CDDIS.list: {e}")
            return
        # === [用 HTTPS 生成 CDDIS.list] 结束 ===