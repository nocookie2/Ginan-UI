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
from app.utils.cddis_email import get_username_from_netrc, write_email, test_cddis_connection


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
        """Generate CDDIS.list via HTTPS; test connectivity BEFORE accepting EMAIL."""

        # 0) 基本校验
        if not getattr(self, "rnx_file", None):
            self.ui.terminalTextEdit.append("Please select a RNX file first.")
            return
        if not getattr(self, "output_dir", None):
            self.ui.terminalTextEdit.append("Please select an output directory first.")
            return

        # 1) Earthdata 凭据校验（.netrc/_netrc），无则弹出现有的 Credentials 弹窗
        ok, where = gui_validate_netrc()
        if not ok:
            self.ui.terminalTextEdit.append("No Earthdata credentials. Opening CDDIS Credentials dialog…")
            self.ui.cddisCredentialsButton.click()
            ok, where = gui_validate_netrc()
            if not ok:
                self.ui.terminalTextEdit.append(f"❌ Credentials still invalid: {where}")
                return
        self.ui.terminalTextEdit.append(f"✅ Credentials OK: {where}")

        # 2) 从 .netrc 读取用户名（作为 email 候选；此时不写 env）
        ok_user, email_candidate = get_username_from_netrc()
        if not ok_user:
            self.ui.terminalTextEdit.append(f"❌ Cannot read username from .netrc: {email_candidate}")
            return

        # 3) 连通性 + 鉴权测试（通过后才“接受”邮箱）
        ok_conn, why = test_cddis_connection()
        if not ok_conn:
            self.ui.terminalTextEdit.append(
                f"❌ CDDIS connectivity check failed: {why}. Please verify Earthdata credentials via the CDDIS Credentials dialog."
            )
            return
        self.ui.terminalTextEdit.append("🔌 CDDIS connectivity check passed.")
        write_email(email_candidate)  # 通过后再写入 utils/CDDIS.env，并设置环境变量 EMAIL
        self.ui.terminalTextEdit.append(f"📧 EMAIL set to: {email_candidate}")


        # 4) 取时间窗（extract_ui_values 需要 rnx 路径；可能返回 dataclass 或 dict）
        inputs = self.inputCtrl.extract_ui_values(self.rnx_file)
        try:
            start_s = inputs.start_epoch
            end_s = inputs.end_epoch
        except AttributeError:
            start_s = inputs["start_epoch"]
            end_s = inputs["end_epoch"]

        # 防零长度时间窗
        if str(start_s) == str(end_s):
            self.ui.terminalTextEdit.append(
                "❌ Time window is zero-length. Click 'Time Window' and choose a start/end range (e.g., a full day)."
            )
            return

        # 5) 转成 GPSDate（把空格/下划线替换成 'T' 供 numpy 识别）
        start_s = str(start_s);
        end_s = str(end_s)
        start_gps = GPSDate(np.datetime64(start_s.replace('_', ' ').replace(' ', 'T')))
        end_gps = GPSDate(np.datetime64(end_s.replace('_', ' ').replace(' ', 'T')))

        # 6) 目标目录：app/models
        target_dir = Path(__file__).resolve().parent / "models"
        target_dir.mkdir(parents=True, exist_ok=True)

        # 7) 生成清单（HTTPS）——注意：函数不返回路径！
        self.ui.terminalTextEdit.append(f"Generating CDDIS.list for {start_s} ~ {end_s} …")
        create_cddis_file(target_dir, start_gps, end_gps)

        # 8) 正确地统计文件行数并反馈
        out_file = target_dir / "CDDIS.list"
        try:
            n_lines = sum(1 for _ in open(out_file, "r", encoding="utf-8"))
        except Exception:
            n_lines = "?"
        self.ui.terminalTextEdit.append(f"✅ CDDIS.list generated: {out_file} (lines: {n_lines})")
        return