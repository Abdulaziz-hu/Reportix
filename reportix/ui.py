import os
import platform
import subprocess
import webbrowser
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QMessageBox, QDialog, QDialogButtonBox,
    QFileDialog, QStatusBar,
)

from .version import APP_NAME, APP_VERSION, GITHUB_REPO_URL, GITHUB_RELEASES_URL
from .hardware import gather_system_specs
from .pdf_report import generate_pdf
from .updater import UpdateCheckWorker


# --------------------------------------------------------------------------
# Background workers
# --------------------------------------------------------------------------

class ScanWorker(QThread):
    finished = pyqtSignal(dict, list, list)
    error = pyqtSignal(str)

    def run(self):
        try:
            specs, disks, ram_modules = gather_system_specs()
            self.finished.emit(specs, disks, ram_modules)
        except Exception as e:
            self.error.emit(str(e))


class PdfWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, specs, disks, ram_modules, filepath):
        super().__init__()
        self.specs = specs
        self.disks = disks
        self.ram_modules = ram_modules
        self.filepath = filepath

    def run(self):
        try:
            path = generate_pdf(self.specs, self.disks, self.ram_modules, self.filepath)
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


# --------------------------------------------------------------------------
# Update dialog - shows formatted release notes, "Update" opens the browser
# --------------------------------------------------------------------------

class UpdateDialog(QDialog):
    def __init__(self, release_info, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.setWindowTitle("Update Available - Reportix")
        self.resize(520, 420)
        self.setMinimumSize(420, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        tag = release_info.get("tag_name", "")
        headline = QLabel(f"A new version of Reportix is available: {tag}")
        headline.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        headline.setWordWrap(True)
        layout.addWidget(headline)

        current_label = QLabel(f"You're currently running v{APP_VERSION}.")
        current_label.setStyleSheet("color: #94A3B8;")
        layout.addWidget(current_label)

        notes_label = QLabel("Release notes:")
        notes_label.setStyleSheet("color: #E2E8F0; font-weight: bold; margin-top: 6px;")
        layout.addWidget(notes_label)

        self.notes_view = QTextEdit()
        self.notes_view.setReadOnly(True)
        # setMarkdown renders the GitHub-flavoured markdown release body
        # (headings, lists, bold, code, links, ...) instead of dumping raw
        # markdown syntax at the user.
        self.notes_view.setMarkdown(release_info.get("body", "") or "_No release notes were provided._")
        layout.addWidget(self.notes_view, stretch=1)

        button_box = QDialogButtonBox()
        self.later_btn = button_box.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        self.update_btn = button_box.addButton("Update Now", QDialogButtonBox.ButtonRole.AcceptRole)
        self.update_btn.setDefault(True)
        self.later_btn.clicked.connect(self.reject)
        self.update_btn.clicked.connect(self.on_update_clicked)
        layout.addWidget(button_box)

    def on_update_clicked(self):
        url = self.release_info.get("html_url") or GITHUB_RELEASES_URL
        webbrowser.open(url)
        self.accept()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - System Specifications & PDF Reporter")
        self.resize(800, 580)
        self.setMinimumSize(620, 460)

        self.specs_data = None
        self.disk_data = None
        self.ram_modules = None
        self.pdf_path = None

        self.scan_worker = None
        self.pdf_worker = None
        self.update_worker = None
        self._manual_update_check = False

        self.init_ui()
        self.init_menu()

        # Check for updates shortly after the window appears, every time
        # the app is opened, without blocking startup or nagging when the
        # network is unavailable.
        QTimer.singleShot(600, lambda: self.check_for_updates(silent=True))

    # -- UI construction ---------------------------------------------------

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel(f"{APP_NAME} - System Specifications & PDF Reporter")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #E2E8F0;")
        layout.addWidget(title_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_scan = QPushButton("Grab Specs")
        self.btn_scan.setMinimumHeight(38)
        self.btn_scan.clicked.connect(self.start_scan)
        btn_layout.addWidget(self.btn_scan)

        self.btn_pdf = QPushButton("Generate PDF Report")
        self.btn_pdf.setMinimumHeight(38)
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.clicked.connect(self.start_pdf_generation)
        btn_layout.addWidget(self.btn_pdf)

        self.btn_copy = QPushButton("Copy Report")
        self.btn_copy.setMinimumHeight(38)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_report)
        btn_layout.addWidget(self.btn_copy)

        layout.addLayout(btn_layout)

        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setFont(QFont("JetBrains Mono", 10))
        layout.addWidget(self.text_output)

        status = QStatusBar()
        status.showMessage(f"{APP_NAME} v{APP_VERSION}")
        self.setStatusBar(status)

        self.log("Click 'Grab Specs' to begin hardware scan.")

    def init_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        export_action = QAction("Export PDF Report...", self)
        export_action.setEnabled(False)
        export_action.triggered.connect(self.start_pdf_generation)
        self.export_action = export_action
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menu_bar.addMenu("&Help")
        check_update_action = QAction("Check for Updates...", self)
        check_update_action.triggered.connect(lambda: self.check_for_updates(silent=False))
        help_menu.addAction(check_update_action)

        repo_action = QAction("View on GitHub", self)
        repo_action.triggered.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        help_menu.addAction(repo_action)

        help_menu.addSeparator()
        about_action = QAction("About Reportix", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def log(self, message):
        self.text_output.append(message)

    # -- Scan ---------------------------------------------------------------

    def start_scan(self):
        self.text_output.clear()
        self.log("Scanning hardware topology (CPU, Motherboard, BIOS, GPU, RAM, Disks)...")
        self.btn_scan.setEnabled(False)
        self.btn_pdf.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.export_action.setEnabled(False)

        self.scan_worker = ScanWorker()
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_scan_error)
        self.scan_worker.start()

    def on_scan_finished(self, specs, disks, ram_modules):
        self.specs_data = specs
        self.disk_data = disks
        self.ram_modules = ram_modules
        self.btn_scan.setEnabled(True)
        self.btn_pdf.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.export_action.setEnabled(True)

        self.log("=== SYSTEM HARDWARE OVERVIEW ===")
        for k, v in specs.items():
            self.log(f"• <b>{k}:</b> {v}")

        self.log("\n=== MEMORY (RAM) MODULES ===")
        if ram_modules:
            for m in ram_modules:
                self.log(
                    f"• <b>{m.get('Slot', 'N/A')}:</b> "
                    f"{m.get('Manufacturer', 'Unknown')} {m.get('Part Number', 'Unknown')} "
                    f"— {m.get('Capacity', 'Unknown')} @ {m.get('Speed', 'Unknown')}"
                )
        else:
            self.log(
                "• Per-module details unavailable on this system "
                "(on Linux this usually needs 'sudo' since it relies on dmidecode)."
            )

        self.log("\n=== STORAGE PARTITIONS ===")
        for d in disks:
            self.log(f"• <b>{d['Device']}</b> ({d['Mountpoint']}) — Total: {d['Total']}, Free: {d['Free']} ({d['Percentage']} used)")

        self.log("\nReady to compile report.")

    def on_scan_error(self, err_msg):
        self.btn_scan.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to gather specs:\n{err_msg}")

    # -- Copy to clipboard ----------------------------------------------------

    def copy_report(self):
        QApplication.clipboard().setText(self.text_output.toPlainText())
        self.statusBar().showMessage("Report copied to clipboard.", 4000)

    # -- PDF ------------------------------------------------------------------

    def start_pdf_generation(self):
        if not self.specs_data:
            return

        default_name = f"Reportix_System_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save PDF Report", default_name, "PDF Files (*.pdf)"
        )
        if not filepath:
            return

        self.btn_pdf.setEnabled(False)
        self.export_action.setEnabled(False)
        self.log("\nCompiling PDF document...")

        self.pdf_worker = PdfWorker(self.specs_data, self.disk_data, self.ram_modules, filepath)
        self.pdf_worker.finished.connect(self.on_pdf_finished)
        self.pdf_worker.error.connect(self.on_pdf_error)
        self.pdf_worker.start()

    def on_pdf_finished(self, path):
        self.pdf_path = path
        self.btn_pdf.setEnabled(True)
        self.export_action.setEnabled(True)
        self.log(f"PDF successfully compiled and saved to: {path}")
        self.open_pdf_file()

    def on_pdf_error(self, err_msg):
        self.btn_pdf.setEnabled(True)
        self.export_action.setEnabled(True)
        QMessageBox.critical(self, "Error", f"PDF compilation failed:\n{err_msg}")

    def open_pdf_file(self):
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            return
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(self.pdf_path)
            elif system == "Darwin":
                subprocess.run(["open", self.pdf_path])
            else:
                subprocess.run(["xdg-open", self.pdf_path])
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not open file automatically: {e}")

    # -- Update checker ---------------------------------------------------------

    def check_for_updates(self, silent=True):
        if self.update_worker and self.update_worker.isRunning():
            return
        self._manual_update_check = not silent

        self.update_worker = UpdateCheckWorker()
        self.update_worker.update_available.connect(self.on_update_available)
        self.update_worker.no_update.connect(self.on_no_update)
        self.update_worker.error.connect(self.on_update_error)
        self.update_worker.start()

    def on_update_available(self, release_info):
        dialog = UpdateDialog(release_info, parent=self)
        dialog.exec()

    def on_no_update(self):
        if self._manual_update_check:
            QMessageBox.information(
                self, "No Updates Available",
                f"You're already running the latest version (v{APP_VERSION})."
            )

    def on_update_error(self, err_msg):
        # Never nag on the automatic startup check if e.g. the user has no
        # internet connection - only surface errors from a manual check.
        if self._manual_update_check:
            QMessageBox.warning(
                self, "Update Check Failed",
                f"Couldn't check for updates:\n{err_msg}"
            )

    # -- About ------------------------------------------------------------------

    def show_about(self):
        QMessageBox.about(
            self, "About Reportix",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>An effortless way to generate a clean, detailed PDF report of "
            f"your computer's hardware and system specifications.</p>"
            f'<p><a href="{GITHUB_REPO_URL}">{GITHUB_REPO_URL}</a></p>'
        )


def apply_stylesheet(app):
    stylesheet = """
        QMainWindow {
            background-color: #0F172A;
        }
        QLabel {
            color: #F8FAFC;
            font-family: 'Segoe UI', sans-serif;
        }
        QPushButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border-radius: 6px;
            padding: 6px 16px;
            font-family: 'Segoe UI', sans-serif;
            font-weight: bold;
            font-size: 10pt;
            border: none;
        }
        QPushButton:hover {
            background-color: #1D4ED8;
        }
        QPushButton:disabled {
            background-color: #334155;
            color: #64748B;
        }
        QTextEdit {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 8px;
            selection-background-color: #3B82F6;
        }
        QMenuBar {
            background-color: #0F172A;
            color: #E2E8F0;
        }
        QMenuBar::item:selected {
            background-color: #1E293B;
        }
        QMenu {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
        }
        QMenu::item:selected {
            background-color: #2563EB;
        }
        QStatusBar {
            background-color: #0F172A;
            color: #64748B;
        }
        QDialog {
            background-color: #0F172A;
        }
    """
    app.setStyleSheet(stylesheet)
