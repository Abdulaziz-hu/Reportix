import sys
import multiprocessing

from PyQt6.QtWidgets import QApplication

from reportix.ui import MainWindow, apply_stylesheet

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
    apply_stylesheet(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
