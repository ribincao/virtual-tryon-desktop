"""Decart realtime session.

The SDK is asyncio-based and Qt is not, so the session owns a private event
loop on its own thread. Everything crossing the boundary goes through Qt
signals (inbound) or ``call_soon_threadsafe`` / ``run_coroutine_threadsafe``
(outbound).
"""

from __future__ import annotations

import asyncio
import threading

import numpy as np
from livekit import rtc
from PySide6.QtCore import QObject, Signal

from decart import ModelState, Prompt, models
from decart.realtime import RealtimeClient, RealtimeConnectOptions

from . import garment
from .config import REALTIME_BASE_URL


class RealtimeSession(QObject):
    """Owns one try-on session and the asyncio loop that drives it."""

    connected = Signal()
    disconnected = Signal(str)  # reason; "" means the user asked for it
    remote_frame = Signal(object)  # np.ndarray (h, w, 3) uint8, RGB24
    error = Signal(str)
    note = Signal(str)  # transient status text

    def __init__(self, api_key: str, model_name: str, parent=None):
        super().__init__(parent)
        self._api_key = api_key
        self.model = models.realtime(model_name)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: RealtimeClient | None = None
        self._source: rtc.VideoSource | None = None
        self._stop: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, prompt: str, image_path: str | None) -> None:
        if self.is_running():
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(prompt, image_path),
            name="decart-realtime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the session to shut down. Safe to call from the Qt thread."""
        loop, stop = self._loop, self._stop
        if loop and stop and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)

    def _thread_main(self, prompt: str, image_path: str | None) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        reason = ""
        try:
            loop.run_until_complete(self._session(prompt, image_path))
        except Exception as exc:  # surfaced in the UI, not swallowed
            reason = str(exc)
            self.error.emit(reason)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None
            self._client = None
            self._source = None
            self._stop = None
            self.disconnected.emit(reason)

    async def _session(self, prompt: str, image_path: str | None) -> None:
        self._stop = asyncio.Event()
        model = self.model

        self._source = rtc.VideoSource(model.width, model.height)
        local_track = rtc.LocalVideoTrack.create_video_track("camera", self._source)

        def on_remote_stream(track: rtc.RemoteVideoTrack) -> None:
            asyncio.create_task(self._consume(track))

        initial_state = None
        if prompt:
            initial_state = ModelState(prompt=Prompt(text=prompt, enhance=False))

        self._client = await RealtimeClient.connect(
            base_url=REALTIME_BASE_URL,
            api_key=self._api_key,
            local_track=local_track,
            options=RealtimeConnectOptions(
                model=model,
                on_remote_stream=on_remote_stream,
                initial_state=initial_state,
                resolution=None,
                preferred_video_codec="h264",
            ),
        )
        self.connected.emit()

        if image_path:
            await self._apply(prompt, image_path)

        await self._stop.wait()

        try:
            await self._client.disconnect()
        except Exception:
            pass

    async def _consume(self, track: rtc.RemoteVideoTrack) -> None:
        async for event in rtc.VideoStream(track):
            frame = event.frame.convert(rtc.VideoBufferType.RGB24)
            # .copy() matters: the underlying buffer gets reused.
            arr = (
                np.frombuffer(frame.data, dtype=np.uint8)
                .reshape(frame.height, frame.width, 3)
                .copy()
            )
            self.remote_frame.emit(arr)

    # ------------------------------------------------------------------
    # inputs
    # ------------------------------------------------------------------
    def submit_frame(self, rgb: np.ndarray) -> None:
        """Push one camera frame. Called from the camera thread."""
        loop, source = self._loop, self._source
        if loop is None or source is None or loop.is_closed():
            return
        height, width = rgb.shape[:2]
        frame = rtc.VideoFrame(width, height, rtc.VideoBufferType.RGB24, rgb.tobytes())
        try:
            loop.call_soon_threadsafe(self._capture, frame)
        except RuntimeError:
            pass  # loop closed between the check and the call

    def _capture(self, frame: rtc.VideoFrame) -> None:
        source = self._source
        if source is not None:
            try:
                source.capture_frame(frame)
            except Exception:
                pass

    def apply(self, prompt: str, image_path: str | None) -> None:
        """Change the outfit mid-session, without reconnecting."""
        loop = self._loop
        if loop is None or self._client is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._apply(prompt, image_path), loop)

    async def _apply(self, prompt: str, image_path: str | None) -> None:
        client = self._client
        if client is None:
            return
        try:
            if image_path:
                # Shrink before sending; an oversized payload can take the
                # control channel down mid-session.
                data, note = garment.prepare(image_path)
                await client.set_image(data, prompt=prompt or None, enhance=False)
                self.note.emit(f"Garment applied ({note})")
            elif prompt:
                await client.set_prompt(prompt, enhance=False)
                self.note.emit("Prompt applied")
        except garment.GarmentError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"Could not apply outfit: {exc}")

    def connection_state(self) -> str | None:
        """Current SDK-reported state, or None when there's no session.

        The control channel can die while the video track keeps flowing, so
        the UI can't infer liveness from frames alone.
        """
        client = self._client
        if client is None:
            return None
        try:
            return client.get_connection_state()
        except Exception:
            return None
