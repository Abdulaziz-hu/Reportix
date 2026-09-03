"""
Checks GitHub Releases for a newer Reportix build.

Runs on a QThread so it never blocks the UI - both on the automatic,
silent startup check and on a manual "Check for Updates" click from the
Help menu.
"""

import json
import urllib.request
import urllib.error

from PyQt6.QtCore import QThread, pyqtSignal

from .version import APP_VERSION, GITHUB_API_LATEST_RELEASE, GITHUB_RELEASES_URL

REQUEST_TIMEOUT = 8  # seconds


def _parse_version(v):
    """'v1.12.3-beta' -> (1, 12, 3). Non-numeric trailing bits are ignored
    so pre-release suffixes don't blow up the comparison."""
    v = (v or "").strip()
    if v.lower().startswith("v"):
        v = v[1:]
    parts = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(remote_version, local_version=APP_VERSION):
    return _parse_version(remote_version) > _parse_version(local_version)


class UpdateCheckWorker(QThread):
    """Emits exactly one of: update_available(dict), no_update(), error(str)."""

    update_available = pyqtSignal(dict)
    no_update = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        try:
            request = urllib.request.Request(
                GITHUB_API_LATEST_RELEASE,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"Reportix/{APP_VERSION}",
                },
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))

            tag = payload.get("tag_name", "")
            if tag and is_newer(tag):
                self.update_available.emit({
                    "tag_name": tag,
                    "name": payload.get("name") or tag,
                    "body": payload.get("body") or "_No release notes were provided._",
                    "html_url": payload.get("html_url") or GITHUB_RELEASES_URL,
                    "published_at": payload.get("published_at", ""),
                })
            else:
                self.no_update.emit()
        except urllib.error.URLError as e:
            self.error.emit(f"Could not reach GitHub: {e}")
        except Exception as e:
            self.error.emit(str(e))
