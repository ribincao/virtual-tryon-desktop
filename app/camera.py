"""Webcam capture, emitting RGB24 frames already sized for the model."""

from __future__ import annotations

import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal


def fit_to(bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Center-crop to the target aspect ratio, then resize.

    A plain resize would squash a 16:9 webcam into the model's 1088x624
    (~1.74:1) frame. Cropping first keeps proportions honest, which matters
    when the whole point is judging how something looks on you.
    """
    h, w = bgr.shape[:2]
    target = width / height

    if w / h > target:
        new_w = int(round(h * target))
        x0 = (w - new_w) // 2
        bgr = bgr[:, x0 : x0 + new_w]
    else:
        new_h = int(round(w / target))
        y0 = (h - new_h) // 2
        bgr = bgr[y0 : y0 + new_h, :]

    return cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)


class CameraThread(QThread):
    """Reads the webcam at the model's frame rate."""

    frame_ready = Signal(object)  # np.ndarray (h, w, 3) uint8, RGB24
    failed = Signal(str)

    def __init__(self, device_index: int, width: int, height: int, fps: int, parent=None):
        super().__init__(parent)
        self._device_index = device_index
        self._width = width
        self._height = height
        self._fps = max(1, fps)
        self._running = False
        self._mirror = True

    def set_mirror(self, enabled: bool) -> None:
        """Mirror at capture, not at display.

        Flipping the returned frames instead would also flip the provenance
        watermark Decart burns into them, leaving it printed backwards.
        Mirroring the input keeps the output mirror-like and the watermark
        the right way round.
        """
        self._mirror = enabled

    def run(self) -> None:
        cap = cv2.VideoCapture(self._device_index)
        if not cap.isOpened():
            self.failed.emit(
                f"Could not open camera {self._device_index}.\n\n"
                "On macOS, camera permission is granted to the process that launched "
                "this app — usually Terminal. Check System Settings › Privacy & "
                "Security › Camera, then try again."
            )
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_FPS, self._fps)

        interval = 1.0 / self._fps
        self._running = True
        try:
            while self._running:
                started = time.perf_counter()
                ok, bgr = cap.read()
                if not ok:
                    time.sleep(interval)
                    continue

                # LiveKit expects RGB24; OpenCV hands back BGR. Skip this and
                # everything comes out blue.
                rgb = cv2.cvtColor(
                    fit_to(bgr, self._width, self._height), cv2.COLOR_BGR2RGB
                )
                if self._mirror:
                    rgb = np.ascontiguousarray(rgb[:, ::-1])
                self.frame_ready.emit(rgb)

                elapsed = time.perf_counter() - started
                if elapsed < interval:
                    time.sleep(interval - elapsed)
        finally:
            cap.release()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
