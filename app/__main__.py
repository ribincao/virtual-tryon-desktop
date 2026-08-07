"""Entry point: ``python -m app`` (or ``python run.py``)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigError, load
from .ui import MainWindow

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
