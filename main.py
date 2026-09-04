import os
import sys
import multiprocessing

# IMPORTANT (Linux theming): on distros where Qt integrates with the native
# desktop's theme (GNOME/GTK, KDE, etc.) via a platform theme plugin, that
# plugin can partially paint window/dialog backgrounds itself - fighting
# our own QSS colors and producing a half dark / half light mess (buttons
# following our theme, but the window chrome following the OS's). It also
# tries to reach the XDG desktop portal over DBus for things like the
# system color scheme, which is what the
#   qt.qpa.theme.gnome: dbus reply error ... "Could not activate remote
#   peer 'org.freedesktop.portal.Desktop'"
# warnings on startup are about (harmless, but noisy, on setups without a
# running portal service). Opting out of the native platform theme plugin
# and forcing Qt's built-in cross-platform "Fusion" style below means the
# app's own stylesheet is always the single source of truth for colors, on
# every OS. Respect an explicit user override if one is already set.
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from reportix.ui import MainWindow, apply_stylesheet, resolve_theme
from reportix.settings import AppSettings
from reportix.i18n import is_rtl

if __name__ == "__main__":
    # IMPORTANT: py-cpuinfo (and Python's multiprocessing in general) spawns a
    # separate worker process to safely read CPUID info. When this app is
    # frozen into a single .exe with PyInstaller, sys.executable IS the app
    # itself, so without freeze_support() that worker process re-launches the
    # entire GUI instead of just running the worker function. Calling
    # freeze_support() here lets frozen child processes detect they're a
    # multiprocessing worker and skip straight to doing their job instead of
    # opening a second window.
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)

    # Force a consistent, built-in style rather than whatever native style
    # the OS/desktop environment would otherwise inject. This is what makes
    # our stylesheet render identically (and fully) on Windows, macOS, and
    # every Linux desktop, instead of the OS theme bleeding through.
    app.setStyle("Fusion")

    # Give every widget a sane default UI font with generic fallbacks so Qt
    # never has to fall back to whatever the desktop's configured system
    # font is (which, on some Linux setups, triggers
    # "OpenType support missing for '<font>'" warnings for fonts with
    # incomplete/variable-font metadata). Widgets that want a specific look
    # (title, monospace output) still set their own QFont explicitly.
    default_font = QFont("Segoe UI")
    default_font.setStyleStrategy(QFont.StyleStrategy.PreferOutline)
    default_font.setFamilies(["Segoe UI", "Noto Sans", "DejaVu Sans", "Helvetica Neue", "Arial", "sans-serif"])
    app.setFont(default_font)

    # Apply the user's saved theme + language (both default sensibly on
    # first run) before the main window is built, so there's no visible
    # flash of the wrong theme/direction on startup.
    settings = AppSettings()
    apply_stylesheet(app, resolve_theme(settings.theme))
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if is_rtl(settings.language)
        else Qt.LayoutDirection.LeftToRight
    )

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
