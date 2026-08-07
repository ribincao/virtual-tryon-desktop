"""Qt front end."""

from __future__ import annotations

import sys
import time

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .camera import CameraThread
from .config import PRICE_PER_SEC_USD, Config
from .realtime import RealtimeSession

PROMPT_PLACEHOLDER = (
    "Substitute the current top with a navy blue wool blazer over a white shirt"
)

PROMPT_HINT = (
    "Prompts work best starting with <b>Substitute</b> or <b>Add</b>. "
    "A garment image plus a short description beats either alone."
)

# How long an error stays on the status bar before normal updates resume.
ERROR_DISPLAY_SEC = 8.0

# States where the session is billing but can no longer be driven.
DEAD_STATES = {"disconnected", "reconnecting"}


def to_pixmap(rgb: np.ndarray) -> QPixmap:
    """Frames arrive display-ready; mirroring happens at capture, not here.

    Flipping at display would also flip the provenance watermark Decart burns
    into the returned frames.
    """
    height, width, _ = rgb.shape
    image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class VideoView(QLabel):
    """Scales frames to fit while preserving aspect ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(544, 312)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#111; border-radius:6px; color:#666;")
        self.setText("Starting camera…")
        self._pixmap: QPixmap | None = None

    def show_frame(self, rgb: np.ndarray) -> None:
        self._pixmap = to_pixmap(rgb)
        self._rescale()

    def clear_frame(self, message: str) -> None:
        self._pixmap = None
        self.setText(message)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        """Scale against *device* pixels, not logical points.

        QWidget.size() is in points. On a 2x display, scaling a 1088px frame
        to a ~670pt widget shrank it to 670 real pixels, and Qt then drew
        that across 1340 device pixels: a downscale immediately followed by
        an upscale, discarding roughly half the detail the model produced
        before it ever reached the screen.

        Targeting device pixels resamples once instead of twice. The frame
        keeps the same physical size on screen; it just stops being blurred
        on the way there.
        """
        if self._pixmap is None:
            return

        ratio = self.devicePixelRatioF()
        available = QSize(
            max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio))
        )
        scaled = self._pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.setPixmap(scaled)


class MainWindow(QWidget):
    request_quit = Signal()

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.session = RealtimeSession(config.api_key, config.model)
        model = self.session.model

        self.setWindowTitle("Virtual Try-On")
        self.resize(1180, 700)

        self._garment_path: str | None = None
        self._connected = False
        self._started_at: float | None = None
        self._last_interaction = time.monotonic()
        self._error_text = ""
        self._error_until = 0.0

        self._build_ui(model)
        self._wire()

        # Without this, the buttons keep Qt's default enabled state until the
        # user happens to touch an input — which means Connect is clickable at
        # launch with no garment and no prompt, opening a billed session that
        # can't apply anything.
        self._refresh_buttons()

        self.camera = CameraThread(
            config.device_index, model.width, model.height, model.fps
        )
        self.camera.frame_ready.connect(self._on_camera_frame)
        self.camera.failed.connect(self._on_camera_failed)
        self.camera.set_mirror(self.mirror_check.isChecked())
        self.mirror_check.toggled.connect(self.camera.set_mirror)
        self.camera.start()

        self._meter = QTimer(self)
        self._meter.setInterval(250)
        self._meter.timeout.connect(self._tick)
        self._meter.start()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_ui(self, model) -> None:
        # ---- left column ---------------------------------------------
        self.garment_view = QLabel("No garment selected")
        self.garment_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.garment_view.setFixedSize(300, 300)
        self.garment_view.setStyleSheet(
            "background:#181818; border:1px solid #2c2c2c; "
            "border-radius:6px; color:#666;"
        )

        self.upload_button = QPushButton("Upload garment image…")
        self.clear_button = QPushButton("Clear")
        self.clear_button.setEnabled(False)

        image_row = QHBoxLayout()
        image_row.addWidget(self.upload_button, 1)
        image_row.addWidget(self.clear_button)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(PROMPT_PLACEHOLDER)
        self.prompt_edit.setFixedHeight(90)

        hint = QLabel(PROMPT_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777; font-size:11px;")

        self.apply_button = QPushButton("Apply outfit")
        self.apply_button.setEnabled(False)

        left = QVBoxLayout()
        left.addWidget(self._section("Garment"))
        left.addWidget(self.garment_view)
        left.addLayout(image_row)
        left.addSpacing(12)
        left.addWidget(self._section("Description"))
        left.addWidget(self.prompt_edit)
        left.addWidget(hint)
        left.addSpacing(8)
        left.addWidget(self.apply_button)
        left.addStretch(1)

        left_panel = QWidget()
        left_panel.setLayout(left)
        left_panel.setFixedWidth(320)

        # ---- right column --------------------------------------------
        self.video = VideoView()

        self.connect_button = QPushButton("Connect")
        self.connect_button.setMinimumWidth(120)
        self.mirror_check = QCheckBox("Mirror")
        self.mirror_check.setChecked(True)

        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("color:#888;")
        self.cost_label = QLabel("00:00   $0.00")
        self.cost_label.setStyleSheet("color:#888; font-family:monospace;")

        model_label = QLabel(f"{model.name} · {model.width}×{model.height} · {model.fps}fps")
        model_label.setStyleSheet("color:#555; font-size:11px;")

        bar = QHBoxLayout()
        bar.addWidget(self.connect_button)
        bar.addWidget(self.mirror_check)
        bar.addSpacing(16)
        bar.addWidget(self.status_label)
        bar.addStretch(1)
        bar.addWidget(model_label)
        bar.addSpacing(16)
        bar.addWidget(self.cost_label)

        right = QVBoxLayout()
        right.addWidget(self.video, 1)
        right.addLayout(bar)

        root = QHBoxLayout(self)
        root.addWidget(left_panel)
        root.addWidget(self._divider())
        root.addLayout(right, 1)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600; color:#ccc;")
        return label

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color:#2c2c2c;")
        return line

    def _wire(self) -> None:
        self.upload_button.clicked.connect(self._choose_garment)
        self.clear_button.clicked.connect(self._clear_garment)
        self.apply_button.clicked.connect(self._apply_outfit)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.prompt_edit.textChanged.connect(self._on_input_changed)

        self.session.connected.connect(self._on_connected)
        self.session.disconnected.connect(self._on_disconnected)
        self.session.remote_frame.connect(self._on_remote_frame)
        self.session.error.connect(self._on_error)
        self.session.note.connect(self._set_status)

    # ------------------------------------------------------------------
    # inputs
    # ------------------------------------------------------------------
    def _touch(self) -> None:
        self._last_interaction = time.monotonic()

    def _on_input_changed(self) -> None:
        self._touch()
        self._refresh_buttons()

    def _choose_garment(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a garment image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        self._garment_path = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._on_error(f"Could not read image: {path}")
            self._garment_path = None
            return
        self.garment_view.setPixmap(
            pixmap.scaled(
                self.garment_view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.clear_button.setEnabled(True)
        self._touch()
        self._refresh_buttons()

    def _clear_garment(self) -> None:
        self._garment_path = None
        self.garment_view.clear()
        self.garment_view.setText("No garment selected")
        self.clear_button.setEnabled(False)
        self._touch()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_input = bool(self._garment_path) or bool(self._prompt())
        self.connect_button.setEnabled(has_input or self._connected)
        self.apply_button.setEnabled(self._connected and has_input)

    def _prompt(self) -> str:
        return self.prompt_edit.toPlainText().strip()

    def _apply_outfit(self) -> None:
        self._touch()
        self.session.apply(self._prompt(), self._garment_path)

    # ------------------------------------------------------------------
    # session
    # ------------------------------------------------------------------
    def _toggle_connection(self) -> None:
        if self._connected or self.session.is_running():
            self.session.stop()
            self._set_status("Disconnecting…")
        else:
            self._touch()
            self._set_status("Connecting…")
            self.connect_button.setEnabled(False)
            self.session.start(self._prompt(), self._garment_path)

    def _on_connected(self) -> None:
        self._connected = True
        self._started_at = time.monotonic()
        self._touch()
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self._set_status("Live")
        self._refresh_buttons()

    def _on_disconnected(self, reason: str) -> None:
        was_connected = self._connected
        self._connected = False
        self._started_at = None
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self._refresh_buttons()

        if reason:
            self._set_status("Disconnected")
            self._on_error(reason)
        elif was_connected:
            self._set_status(f"Session ended · {self._cost_text()}")
        else:
            self._set_status("Idle")

    def _on_remote_frame(self, rgb: np.ndarray) -> None:
        if self._connected:
            self.video.show_frame(rgb)

    def _on_camera_frame(self, rgb: np.ndarray) -> None:
        if self._connected:
            self.session.submit_frame(rgb)
        else:
            # Free local preview, so you can frame yourself before paying.
            self.video.show_frame(rgb)

    def _on_camera_failed(self, message: str) -> None:
        self.video.clear_frame("Camera unavailable")
        QMessageBox.critical(self, "Camera", message)

    def _on_error(self, message: str) -> None:
        """Show session errors inline, never in a modal.

        A modal blocks on a click while the session keeps generating, so an
        error dialog left on screen bills at $0.02/sec until someone notices
        it. The status bar costs nothing to leave up.
        """
        print(f"[try-on] {message}", file=sys.stderr)
        self._error_text = message
        self._error_until = time.monotonic() + ERROR_DISPLAY_SEC
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color:#e06c5a;")

    def _set_status(self, text: str) -> None:
        if time.monotonic() < self._error_until:
            return  # don't paper over an error the user hasn't had time to read
        self.status_label.setStyleSheet("color:#888;")
        self.status_label.setText(text)

    # ------------------------------------------------------------------
    # cost meter and idle guard
    # ------------------------------------------------------------------
    def _elapsed(self) -> float:
        return 0.0 if self._started_at is None else time.monotonic() - self._started_at

    def _cost_text(self) -> str:
        seconds = self._elapsed()
        return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}   ${seconds * PRICE_PER_SEC_USD:.2f}"

    def _tick(self) -> None:
        if not self._connected:
            return

        self.cost_label.setText(self._cost_text())

        # The control channel can drop while video keeps arriving, leaving a
        # session that looks Live, refuses every command, and bills the whole
        # time. Frames alone don't prove the session is healthy.
        state = self.session.connection_state()
        if state in DEAD_STATES:
            self.session.stop()
            self._on_error(f"Session ended by the server ({state}) · {self._cost_text()}")
            return

        cap = self.config.max_session_cost_usd
        if cap > 0 and self._elapsed() * PRICE_PER_SEC_USD >= cap:
            self.session.stop()
            self._set_status(f"Stopped at the ${cap:.2f} cap")
            return

        idle = time.monotonic() - self._last_interaction
        remaining = self.config.idle_timeout_sec - idle
        if remaining <= 0:
            self.session.stop()
            self._set_status("Stopped after idle timeout")
        elif remaining <= 15:
            self._set_status(f"Live · idle disconnect in {int(remaining)}s")
        else:
            self._set_status("Live")

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt naming
        self._meter.stop()
        self.session.stop()
        self.camera.stop()
        super().closeEvent(event)
