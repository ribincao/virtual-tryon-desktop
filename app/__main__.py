"""Entry point: ``python -m app`` (or ``python run.py``)."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigError, load
from .ui import MainWindow


def _install_excepthook() -> None:
    """Make crashes legible.

    PySide6 aborts the process on an unhandled exception inside a slot and
    prints nothing useful, so a bug in a signal handler just looks like the
    window vanishing. Print the traceback and keep running instead.
    """

    def hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        sys.stderr.flush()

    sys.excepthook = hook

STYLESHEET = """
QWidget { background:#141414; color:#ddd;
          font-family:-apple-system, "SF Pro Text", sans-serif; font-size:13px; }
QPushButton { background:#2a2a2a; border:1px solid #3a3a3a; border-radius:5px;
              padding:7px 14px; }
QPushButton:hover:enabled { background:#333; }
QPushButton:disabled { color:#555; border-color:#262626; }
QPlainTextEdit { background:#181818; border:1px solid #2c2c2c; border-radius:5px;
                 padding:6px; }
QCheckBox { color:#999; }
"""


def main() -> int:
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("Virtual Try-On")
    app.setStyleSheet(STYLESHEET)

    try:
        config = load()
    except ConfigError as exc:
        QMessageBox.critical(None, "Configuration", str(exc))
        return 1

    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
