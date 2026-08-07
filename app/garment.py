"""Garment image preparation.

The SDK base64-encodes whatever file you hand it and pushes the result down
the control WebSocket, with no resizing and no size ceiling of its own. A
phone photo or a desktop wallpaper inflates by a third on the way out and can
take the control channel down with it — which surfaces later, and confusingly,
as "Control channel disconnected" on a session that still looks live.

Shrinking here keeps the payload small enough to be uninteresting.
"""

from __future__ import annotations

from pathlib import Path

import cv2

# Decart documents 512x512 as the minimum useful reference size. 1024 leaves
# generous headroom above that while keeping the encoded payload well under a
# megabyte for ordinary photos.
MAX_SIDE = 1024
JPEG_QUALITY = 90
MIN_USEFUL_SIDE = 512


class GarmentError(RuntimeError):
    """Raised when an image can't be read or is unusably small."""


def prepare(path: str | Path) -> tuple[bytes, str]:
    """Return (jpeg_bytes, human_readable_note) for a garment image."""
    path = Path(path)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise GarmentError(
            f"Could not read {path.name}. Supported: PNG, JPEG, WebP."
        )

    original_bytes = path.stat().st_size
    height, width = image.shape[:2]

    if min(height, width) < MIN_USEFUL_SIDE:
        raise GarmentError(
            f"{path.name} is {width}x{height}. Decart wants at least "
            f"{MIN_USEFUL_SIDE}px on the short side for a usable reference."
        )

    scale = MAX_SIDE / max(height, width)
    if scale < 1:
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    ok, buffer = cv2.imencode(
        ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
    )
    if not ok:
        raise GarmentError(f"Could not encode {path.name}.")

    data = buffer.tobytes()
    out_h, out_w = image.shape[:2]
    note = (
        f"{width}x{height} {original_bytes / 1024:.0f}KB "
        f"-> {out_w}x{out_h} {len(data) / 1024:.0f}KB"
    )
    return data, note
