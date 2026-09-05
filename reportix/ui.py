import os
import platform
import subprocess
import webbrowser
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QTextBrowser, QLabel, QMessageBox, QDialog, QDialogButtonBox,
    QFileDialog, QStatusBar, QComboBox,
)

from .version import (
    APP_NAME, APP_VERSION, GITHUB_REPO_URL, GITHUB_RELEASES_URL,
    GITHUB_ISSUES_URL, GITHUB_ISSUES_NEW_URL, DOWNLOAD_PAGE_URL,
)
from .hardware import gather_system_specs
from .pdf_report import generate_pdf
from .updater import UpdateCheckWorker, format_release_datetime
from .settings import AppSettings
from .i18n import translate, LANGUAGES, DEFAULT_LANGUAGE, is_rtl


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
# Theming
# --------------------------------------------------------------------------

def resolve_theme(theme):
    """
    "light"/"dark" pass straight through. "system" is resolved against the
    OS-reported color scheme (Qt 6.5+); if that API isn't available (older
    Qt) or reports "unknown", we fall back to dark, matching the app's
    original look.
    """
    if theme != "system":
        return theme
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme.name.lower() == "light":
            return "light"
        if scheme.name.lower() == "dark":
            return "dark"
    except Exception:
        pass
    return "dark"


_DARK_STYLESHEET = """
    QMainWindow, QDialog {
        background-color: #12151a; /* --bg */
    }
    QWidget {
        background-color: transparent;
        font-family: 'Segoe UI', sans-serif;
    }
    QWidget#centralWidget {
        background-color: #12151a; /* --bg */
    }
    QLabel {
        color: #e4e7eb; /* --text */
        font-family: 'Segoe UI', sans-serif;
    }
    QPushButton {
        background-color: #4fd1c5; /* --accent */
        color: #0b0f12; /* --accent-ink */
        border-radius: 3px; /* --radius */
        padding: 6px 16px;
        font-family: 'Segoe UI', sans-serif;
        font-weight: bold;
        font-size: 10pt;
        border: none;
    }
    QPushButton:hover {
        background-color: #2c7a72; /* --accent-dim */
    }
    QPushButton:disabled {
        background-color: #1a1f26; /* --bg-panel */
        color: #5b6472; /* --text-faint */
    }
    QComboBox {
        background-color: #1a1f26; /* --bg-panel */
        color: #e4e7eb; /* --text */
        border: 1px solid #262c35; /* --border */
        border-radius: 3px; /* --radius */
        padding: 4px 8px;
    }
    QComboBox QAbstractItemView {
        background-color: #1a1f26; /* --bg-panel */
        color: #e4e7eb; /* --text */
        selection-background-color: #4fd1c5; /* --accent */
        selection-color: #0b0f12; /* --accent-ink */
    }
    QTextEdit {
        background-color: #1a1f26; /* --bg-panel */
        color: #e4e7eb; /* --text */
        border: 1px solid #262c35; /* --border */
        border-radius: 3px; /* --radius */
        padding: 8px;
        selection-background-color: #4fd1c5; /* --accent */
        selection-color: #0b0f12; /* --accent-ink */
    }
    QMenuBar {
        background-color: #12151a; /* --bg */
        color: #e4e7eb; /* --text */
    }
    QMenuBar::item:selected {
        background-color: #1a1f26; /* --bg-panel */
    }
    QMenu {
        background-color: #1a1f26; /* --bg-panel */
        color: #e4e7eb; /* --text */
        border: 1px solid #262c35; /* --border */
    }
    QMenu::item:selected {
        background-color: #4fd1c5; /* --accent */
        color: #0b0f12; /* --accent-ink */
    }
    QStatusBar {
        background-color: #12151a; /* --bg */
        color: #8992a0; /* --text-dim */
    }
    QDialog {
        background-color: #12151a; /* --bg */
    }
"""

_LIGHT_STYLESHEET = """
    QMainWindow, QDialog {
        background-color: #f6f7f9; /* --bg */
    }
    QWidget {
        background-color: transparent;
        font-family: 'Segoe UI', sans-serif;
    }
    QWidget#centralWidget {
        background-color: #f6f7f9; /* --bg */
    }
    QLabel {
        color: #171a1f; /* --text */
        font-family: 'Segoe UI', sans-serif;
    }
    QPushButton {
        background-color: #0f9c8f; /* --accent */
        color: #ffffff; /* --accent-ink */
        border-radius: 3px; /* --radius */
        padding: 6px 16px;
        font-family: 'Segoe UI', sans-serif;
        font-weight: bold;
        font-size: 10pt;
        border: none;
    }
    QPushButton:hover {
        background-color: #0c7e73; /* --accent-dim */
    }
    QPushButton:disabled {
        background-color: #eef0f3; /* --bg-panel-2 */
        color: #838c98; /* --text-faint */
    }
    QComboBox {
        background-color: #ffffff; /* --bg-panel */
        color: #171a1f; /* --text */
        border: 1px solid #dde1e7; /* --border */
        border-radius: 3px; /* --radius */
        padding: 4px 8px;
    }
    QComboBox QAbstractItemView {
        background-color: #ffffff; /* --bg-panel */
        color: #171a1f; /* --text */
        selection-background-color: #0f9c8f; /* --accent */
        selection-color: #ffffff; /* --accent-ink */
    }
    QTextEdit {
        background-color: #ffffff; /* --bg-panel */
        color: #171a1f; /* --text */
        border: 1px solid #dde1e7; /* --border */
        border-radius: 3px; /* --radius */
        padding: 8px;
        selection-background-color: #0f9c8f; /* --accent */
        selection-color: #ffffff; /* --accent-ink */
    }
    QMenuBar {
        background-color: #f6f7f9; /* --bg */
        color: #171a1f; /* --text */
    }
    QMenuBar::item:selected {
        background-color: #eef0f3; /* --bg-panel-2 */
    }
    QMenu {
        background-color: #ffffff; /* --bg-panel */
        color: #171a1f; /* --text */
        border: 1px solid #dde1e7; /* --border */
    }
    QMenu::item:selected {
        background-color: #0f9c8f; /* --accent */
        color: #ffffff; /* --accent-ink */
    }
    QStatusBar {
        background-color: #f6f7f9; /* --bg */
        color: #565e6b; /* --text-dim */
    }
    QDialog {
        background-color: #f6f7f9; /* --bg */
    }
"""


def apply_stylesheet(app, theme="dark"):
    """`theme` should already be resolved ("light" or "dark") - see
    resolve_theme() for turning the user's "system" preference into one
    of those two."""
    app.setStyleSheet(_LIGHT_STYLESHEET if theme == "light" else _DARK_STYLESHEET)


# --------------------------------------------------------------------------
# Preferences dialog - theme + language, with an honest note about the
# AI-generated translations.
# --------------------------------------------------------------------------

class PreferencesDialog(QDialog):
    def __init__(self, settings, lang, parent=None):
        super().__init__(parent)
        self.settings = settings

        self._theme_keys = ["system", "light", "dark"]
        self._lang_codes = list(LANGUAGES.keys())

        self.result_theme = settings.theme
        self.result_language = settings.language

        self.setWindowTitle(translate("prefs_title", lang))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        theme_row = QHBoxLayout()
        theme_label = QLabel(translate("prefs_theme_label", lang))
        theme_row.addWidget(theme_label)
        self.theme_combo = QComboBox()
        for key in self._theme_keys:
            self.theme_combo.addItem(translate(f"prefs_theme_{key}", lang))
        current_theme = settings.theme if settings.theme in self._theme_keys else "dark"
        self.theme_combo.setCurrentIndex(self._theme_keys.index(current_theme))
        theme_row.addWidget(self.theme_combo, 1)
        layout.addLayout(theme_row)

        lang_row = QHBoxLayout()
        lang_label = QLabel(translate("prefs_language_label", lang))
        lang_row.addWidget(lang_label)
        self.lang_combo = QComboBox()
        for code in self._lang_codes:
            self.lang_combo.addItem(LANGUAGES[code])
        current_lang = lang if lang in self._lang_codes else DEFAULT_LANGUAGE
        self.lang_combo.setCurrentIndex(self._lang_codes.index(current_lang))
        lang_row.addWidget(self.lang_combo, 1)
        layout.addLayout(lang_row)

        notice = QLabel(translate("prefs_ai_notice", lang))
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #94A3B8; font-size: 9pt; margin-top: 4px;")
        layout.addWidget(notice)

        issue_link = QLabel(
            f'<a href="{GITHUB_ISSUES_NEW_URL}">{translate("prefs_report_issue_link", lang)}</a>'
        )
        issue_link.setOpenExternalLinks(True)
        issue_link.setStyleSheet("font-size: 9pt;")
        layout.addWidget(issue_link)

        restart_note = QLabel(translate("prefs_restart_note", lang))
        restart_note.setWordWrap(True)
        restart_note.setStyleSheet("color: #64748B; font-size: 8.5pt; margin-top: 6px;")
        layout.addWidget(restart_note)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        self.result_theme = self._theme_keys[self.theme_combo.currentIndex()]
        self.result_language = self._lang_codes[self.lang_combo.currentIndex()]
        self.accept()


# --------------------------------------------------------------------------
# Update dialog - shows formatted release notes, "Update" opens the browser
# --------------------------------------------------------------------------

class UpdateDialog(QDialog):
    def __init__(self, release_info, lang=DEFAULT_LANGUAGE, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.setWindowTitle(translate("update_dialog_title", lang))
        self.resize(520, 420)
        self.setMinimumSize(420, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        tag = release_info.get("tag_name", "")
        headline = QLabel(translate("update_headline", lang, tag=tag))
        headline.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        headline.setWordWrap(True)
        layout.addWidget(headline)

        current_label = QLabel(translate("update_current_running", lang, version=APP_VERSION))
        current_label.setStyleSheet("color: #94A3B8;")
        layout.addWidget(current_label)

        released_at = format_release_datetime(release_info.get("published_at"))
        if released_at:
            released_label = QLabel(translate("update_released_on", lang, date=released_at))
            released_label.setStyleSheet("color: #94A3B8;")
            layout.addWidget(released_label)

        notes_label = QLabel(translate("update_release_notes", lang))
        notes_label.setStyleSheet("color: #E2E8F0; font-weight: bold; margin-top: 6px;")
        layout.addWidget(notes_label)

        # QTextBrowser (rather than QTextEdit) so links in the release
        # body are clickable and open in the system browser.
        self.notes_view = QTextBrowser()
        self.notes_view.setOpenExternalLinks(True)
        # setMarkdown renders the GitHub-flavoured markdown release body
        # (headings, lists, bold, code, links, ...) instead of dumping raw
        # markdown syntax at the user.
        self.notes_view.setMarkdown(
            release_info.get("body", "") or f'_{translate("update_no_notes", lang)}_'
        )
        layout.addWidget(self.notes_view, stretch=1)

        button_box = QDialogButtonBox()
        self.later_btn = button_box.addButton(
            translate("btn_later", lang), QDialogButtonBox.ButtonRole.RejectRole
        )
        # Secondary path for anyone who specifically wants the raw GitHub
        # release (assets, source tarball, changelog on GitHub itself)
        # instead of the download page. Doesn't close the dialog, since
        # someone might open that page for reference and still want to
        # click "Update Now" afterwards.
        self.github_btn = button_box.addButton(
            translate("btn_view_on_github", lang), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.update_btn = button_box.addButton(
            translate("btn_update_now", lang), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.update_btn.setDefault(True)
        self.later_btn.clicked.connect(self.reject)
        self.github_btn.clicked.connect(self.on_view_on_github_clicked)
        self.update_btn.clicked.connect(self.on_update_clicked)
        layout.addWidget(button_box)

    def on_update_clicked(self):
        # Send people to the download page - it's the friendlier, easier
        # place for most users to grab the new build from. The release
        # notes above are still pulled live from GitHub either way.
        webbrowser.open(DOWNLOAD_PAGE_URL)
        self.accept()

    def on_view_on_github_clicked(self):
        # For anyone who specifically wants the GitHub release itself
        # (assets, source tarball, ...) rather than the download page.
        url = self.release_info.get("html_url") or GITHUB_RELEASES_URL
        webbrowser.open(url)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = AppSettings()
        self.lang = self.settings.language if self.settings.language in LANGUAGES else DEFAULT_LANGUAGE

        self.specs_data = None
        self.disk_data = None
        self.ram_modules = None
        self.pdf_path = None

        self.scan_worker = None
        self.pdf_worker = None
        self.update_worker = None
        self._manual_update_check = False

        self.resize(800, 580)
        self.setMinimumSize(620, 460)

        self.init_ui()
        self.init_menu()
        self.retranslate_ui()

        if not self.settings.restore_geometry(self):
            self.resize(800, 580)

        # Check for updates shortly after the window appears, every time
        # the app is opened, without blocking startup or nagging when the
        # network is unavailable.
        QTimer.singleShot(600, lambda: self.check_for_updates(silent=True))

    # -- Translation helper --------------------------------------------------

    def t(self, key, **kwargs):
        return translate(key, self.lang, **kwargs)

    # -- UI construction ---------------------------------------------------

    def init_ui(self):
        central_widget = QWidget()
        # Named so the "QWidget#centralWidget" rule in the stylesheet can
        # give it (and therefore the whole window's visible client area) an
        # explicit, opaque background instead of "transparent" - see the
        # comment above _DARK_STYLESHEET / _LIGHT_STYLESHEET for why that
        # matters.
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(self.title_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_scan = QPushButton()
        self.btn_scan.setMinimumHeight(38)
        self.btn_scan.clicked.connect(self.start_scan)
        btn_layout.addWidget(self.btn_scan)

        self.btn_pdf = QPushButton()
        self.btn_pdf.setMinimumHeight(38)
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.clicked.connect(self.start_pdf_generation)
        btn_layout.addWidget(self.btn_pdf)

        self.btn_copy = QPushButton()
        self.btn_copy.setMinimumHeight(38)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_report)
        btn_layout.addWidget(self.btn_copy)

        layout.addLayout(btn_layout)

        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setFont(QFont("JetBrains Mono", 10))
        layout.addWidget(self.text_output)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

    def init_menu(self):
        menu_bar = self.menuBar()

        self.file_menu = menu_bar.addMenu("")
        self.export_action = QAction(self)
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.start_pdf_generation)
        self.file_menu.addAction(self.export_action)
        self.file_menu.addSeparator()
        self.exit_action = QAction(self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # Edit menu - houses Preferences (theme + language), as requested.
        self.edit_menu = menu_bar.addMenu("")
        self.preferences_action = QAction(self)
        self.preferences_action.setShortcut("Ctrl+,")
        self.preferences_action.triggered.connect(self.open_preferences)
        self.edit_menu.addAction(self.preferences_action)

        self.help_menu = menu_bar.addMenu("")
        self.check_update_action = QAction(self)
        self.check_update_action.triggered.connect(lambda: self.check_for_updates(silent=False))
        self.help_menu.addAction(self.check_update_action)

        self.repo_action = QAction(self)
        self.repo_action.triggered.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        self.help_menu.addAction(self.repo_action)

        self.report_issue_action = QAction(self)
        self.report_issue_action.triggered.connect(lambda: webbrowser.open(GITHUB_ISSUES_URL))
        self.help_menu.addAction(self.report_issue_action)

        self.help_menu.addSeparator()
        self.about_action = QAction(self)
        self.about_action.triggered.connect(self.show_about)
        self.help_menu.addAction(self.about_action)

    # -- Translation application --------------------------------------------

    def retranslate_ui(self):
        self.setWindowTitle(self.t("window_title", app=APP_NAME, version=APP_VERSION))
        self.title_label.setText(self.t("title_label", app=APP_NAME))

        self.btn_scan.setText(self.t("btn_grab_specs"))
        self.btn_pdf.setText(self.t("btn_generate_pdf"))
        self.btn_copy.setText(self.t("btn_copy_report"))

        self.file_menu.setTitle(self.t("menu_file"))
        self.export_action.setText(self.t("action_export_pdf"))
        self.exit_action.setText(self.t("action_exit"))

        self.edit_menu.setTitle(self.t("menu_edit"))
        self.preferences_action.setText(self.t("action_preferences"))

        self.help_menu.setTitle(self.t("menu_help"))
        self.check_update_action.setText(self.t("action_check_updates"))
        self.repo_action.setText(self.t("action_view_github"))
        self.report_issue_action.setText(self.t("action_report_issue"))
        self.about_action.setText(self.t("action_about"))

        self.status.showMessage(self.t("status_ready", app=APP_NAME, version=APP_VERSION))

        if self.text_output.toPlainText().strip() == "" and self.specs_data is None:
            self.log(self.t("log_click_to_begin"))

    def log(self, message):
        self.text_output.append(message)

    # -- Preferences ---------------------------------------------------------

    def open_preferences(self):
        dialog = PreferencesDialog(self.settings, self.lang, parent=self)
        if not dialog.exec():
            return

        theme_changed = dialog.result_theme != self.settings.theme
        lang_changed = dialog.result_language != self.settings.language

        self.settings.theme = dialog.result_theme
        self.settings.language = dialog.result_language
        self.settings.sync()

        if theme_changed:
            app = QApplication.instance()
            if app is not None:
                apply_stylesheet(app, resolve_theme(self.settings.theme))

        if lang_changed:
            self.lang = self.settings.language
            app = QApplication.instance()
            if app is not None:
                app.setLayoutDirection(
                    Qt.LayoutDirection.RightToLeft if is_rtl(self.lang)
                    else Qt.LayoutDirection.LeftToRight
                )
            self.retranslate_ui()

    # -- Scan ---------------------------------------------------------------

    def start_scan(self):
        self.text_output.clear()
        self.log(self.t("log_scanning"))
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

        self.log(self.t("log_hw_overview_header"))
        for k, v in specs.items():
            self.log(f"• <b>{k}:</b> {v}")

        self.log("\n" + self.t("log_ram_header"))
        if ram_modules:
            for m in ram_modules:
                self.log(
                    f"• <b>{m.get('Slot', 'N/A')}:</b> "
                    f"{m.get('Manufacturer', 'Unknown')} {m.get('Part Number', 'Unknown')} "
                    f"— {m.get('Capacity', 'Unknown')} @ {m.get('Speed', 'Unknown')}"
                )
        else:
            self.log(f"• {self.t('log_ram_unavailable')}")

        self.log("\n" + self.t("log_storage_header"))
        for d in disks:
            self.log(f"• <b>{d['Device']}</b> ({d['Mountpoint']}) — Total: {d['Total']}, Free: {d['Free']} ({d['Percentage']} used)")

        self.log("\n" + self.t("log_ready_to_compile"))

    def on_scan_error(self, err_msg):
        self.btn_scan.setEnabled(True)
        QMessageBox.critical(self, self.t("msg_error_title"), self.t("msg_scan_failed", err=err_msg))

    # -- Copy to clipboard ----------------------------------------------------

    def copy_report(self):
        QApplication.clipboard().setText(self.text_output.toPlainText())
        self.statusBar().showMessage(self.t("status_report_copied"), 4000)

    # -- PDF ------------------------------------------------------------------

    def start_pdf_generation(self):
        if not self.specs_data:
            return

        default_name = f"Reportix_System_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath, _ = QFileDialog.getSaveFileName(
            self, self.t("dlg_save_pdf_title"), default_name, self.t("pdf_filter")
        )
        if not filepath:
            return

        self.btn_pdf.setEnabled(False)
        self.export_action.setEnabled(False)
        self.log("\n" + self.t("log_compiling_pdf"))

        self.pdf_worker = PdfWorker(self.specs_data, self.disk_data, self.ram_modules, filepath)
        self.pdf_worker.finished.connect(self.on_pdf_finished)
        self.pdf_worker.error.connect(self.on_pdf_error)
        self.pdf_worker.start()

    def on_pdf_finished(self, path):
        self.pdf_path = path
        self.btn_pdf.setEnabled(True)
        self.export_action.setEnabled(True)
        self.log(self.t("log_pdf_saved", path=path))
        self.open_pdf_file()

    def on_pdf_error(self, err_msg):
        self.btn_pdf.setEnabled(True)
        self.export_action.setEnabled(True)
        QMessageBox.critical(self, self.t("msg_error_title"), self.t("msg_pdf_failed", err=err_msg))

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
            QMessageBox.warning(self, self.t("msg_warning_title"), self.t("msg_could_not_open", err=e))

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
        dialog = UpdateDialog(release_info, lang=self.lang, parent=self)
        dialog.exec()

    def on_no_update(self):
        if self._manual_update_check:
            QMessageBox.information(
                self, self.t("no_updates_title"),
                self.t("no_updates_body", version=APP_VERSION),
            )

    def on_update_error(self, err_msg):
        # Never nag on the automatic startup check if e.g. the user has no
        # internet connection - only surface errors from a manual check.
        if self._manual_update_check:
            QMessageBox.warning(
                self, self.t("update_check_failed_title"),
                self.t("update_check_failed_body", err=err_msg),
            )

    # -- About ------------------------------------------------------------------

    def show_about(self):
        QMessageBox.about(
            self, self.t("about_title"),
            self.t("about_body", app=APP_NAME, version=APP_VERSION, url=GITHUB_REPO_URL),
        )

    # -- Window lifecycle ---------------------------------------------------

    def closeEvent(self, event):
        self.settings.save_geometry(self)
        self.settings.sync()
        super().closeEvent(event)
