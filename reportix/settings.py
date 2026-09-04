"""
Thin wrapper around QSettings for the handful of preferences Reportix
persists across launches: theme, language, and last window geometry.

Kept in its own module (rather than scattered QSettings() calls in ui.py)
so there's exactly one place that knows the org/app name and the key
names, and so it's trivial to add another preference later.
"""

from PyQt6.QtCore import QSettings, QByteArray

from .i18n import DEFAULT_LANGUAGE

ORG_NAME = "Reportix"
APP_KEY = "Reportix"

VALID_THEMES = ("system", "light", "dark")


class AppSettings:
    def __init__(self):
        self._qs = QSettings(ORG_NAME, APP_KEY)

    # -- Theme ---------------------------------------------------------

    @property
    def theme(self):
        value = self._qs.value("preferences/theme", "dark")
        return value if value in VALID_THEMES else "dark"

    @theme.setter
    def theme(self, value):
        if value not in VALID_THEMES:
            value = "dark"
        self._qs.setValue("preferences/theme", value)

    # -- Language --------------------------------------------------------

    @property
    def language(self):
        return self._qs.value("preferences/language", DEFAULT_LANGUAGE)

    @language.setter
    def language(self, value):
        self._qs.setValue("preferences/language", value)

    # -- Window geometry (bonus: app now remembers size/position) -----------

    def save_geometry(self, widget):
        self._qs.setValue("window/geometry", widget.saveGeometry())

    def restore_geometry(self, widget):
        geometry = self._qs.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            widget.restoreGeometry(geometry)
            return True
        return False

    def sync(self):
        self._qs.sync()
