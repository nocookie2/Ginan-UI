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
        """Call backend model to generate outputs; then visualise as needed."""

        if not self.rnx_file:
            self.ui.terminalTextEdit.append("Please select a RNX file first.")
            return
        if not self.output_dir:
            self.ui.terminalTextEdit.append("Please select an output directory first.")
            return

        # === CDDIS (HTTPS) 预处理 —— 失败则立即终止；成功才继续旧流程 ===
        # 1) Earthdata 凭据校验；无则弹你们现有的 Credentials 对话框
        ok, where = gui_validate_netrc()
        if not ok and hasattr(self.ui, "cddisCredentialsButton"):
            self.ui.terminalTextEdit.append("No Earthdata credentials. Opening CDDIS Credentials dialog…")
            self.ui.cddisCredentialsButton.click()
            ok, where = gui_validate_netrc()
        if not ok:
            self.ui.terminalTextEdit.append(f" Credentials invalid: {where}")
            return
        self.ui.terminalTextEdit.append(f" Credentials OK: {where}")

        # 2) 从 .netrc 读取用户名（团队约定：username == email；此时不落盘）
        ok_user, email_candidate = get_username_from_netrc()
        if not ok_user:
            self.ui.terminalTextEdit.append(f" Cannot read username from .netrc: {email_candidate}")
            return

        # 3) 连通性 + 鉴权测试（requests.Session 双阶段）
        ok_conn, why = test_cddis_connection()
        if not ok_conn:
            self.ui.terminalTextEdit.append(
                f" CDDIS connectivity check failed: {why}. Please verify Earthdata credentials via the CDDIS Credentials dialog."
            )
            return
        self.ui.terminalTextEdit.append(" CDDIS connectivity check passed.")

        # 通过测试后，才“接受/落盘” EMAIL
        write_email(email_candidate)
        self.ui.terminalTextEdit.append(f" EMAIL set to: {email_candidate}")

        # === 预处理全部成功；后续继续执行你们“原有的 Process 流程” ===

        # —— ignore the PEA processing and jump to the plot generation directly —— #
        self.ui.terminalTextEdit.append("Skipping PEA processing due to configuration issues")
        self.ui.terminalTextEdit.append("Testing plot generation directly instead...")

        # 【original PEA processing code】- TODO:need to be fixed by backend team
        # # —— Launch the backend —— #
        # try:
        #     # directly call execution to process
        #     # temporarily skip configuration application, directly execute
        #     # self.execution.apply_ui_config(self.inputCtrl.get_inputs())
        #     self.execution.execute_config()
        #     self.ui.terminalTextEdit.append("Processing finished.")
        # except Exception as err:
        #     self.ui.terminalTextEdit.append(f"Processing failed: {err}")
        #     return

        # # after the processing is finished, automatically generate the visualizations
        # try:
        #     self.ui.terminalTextEdit.append("Generating visualizations...")
        #     html_files = self.execution.build_pos_plots()
        #     if html_files:
        #         self.ui.terminalTextEdit.append(f"Generated {len(html_files)} visualization(s)")
        #         self.visCtrl.set_html_files(html_files)
        #     else:
        #         self.ui.terminalTextEdit.append("No visualizations generated")
        # except Exception as err:
        #     self.ui.terminalTextEdit.append(f"Visualization generation failed: {err}")
        # directly call the plot generation function

        try:
            self.ui.terminalTextEdit.append("Testing plot generation directly...")

            # use the test data directory
            test_output_dir = Path(__file__).resolve().parents[1] / "tests" / "resources" / "outputData"
            test_visual_dir = test_output_dir / "visual"

            self.ui.terminalTextEdit.append(f"Looking for POS files in: {test_output_dir}")

            test_visual_dir.mkdir(parents=True, exist_ok=True)

            self.visCtrl.build_from_execution()

            self.ui.terminalTextEdit.append("Plot generation completed. Check the visualization panel above.")

        except Exception as err:
            self.ui.terminalTextEdit.append(f"Test plot generation failed: {err}")
            import traceback
            self.ui.terminalTextEdit.append(f"Details: {traceback.format_exc()}")

        # # ── Minimal version: manually use example/visual/fig1.html ── #
        # fig1 = os.path.join(EXAMPLE_DIR, "visual", "fig1.html")
        # if not os.path.exists(fig1):
        #    self.ui.terminalTextEdit.append(f"Cannot find fig1.html at: {fig1}")
        #    return

        # self.ui.terminalTextEdit.append(f"Displaying visualisation: {fig1}")
        # # Register & show via visualisation controller
        # self.visCtrl.set_html_files([fig1])

        # # ── Replace with real backend call when ready:
        # html_paths = backend.process(self.rnx_file, self.output_dir, **extractor.get_params())
        # self.visCtrl.set_html_files(html_paths)

    # endregion