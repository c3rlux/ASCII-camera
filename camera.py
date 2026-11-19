"""webcam capture"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2
import numpy as np

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass


class CameraError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class CameraDevice:
    index: int
    backend: int
    label: str


def _backend_name(backend: int) -> str:
    if backend == cv2.CAP_DSHOW:
        return "DirectShow"
    if backend == cv2.CAP_MSMF:
        return "Media Foundation"
    return "Default"


def _make_capture(index: int, backend: int) -> Optional[cv2.VideoCapture]:
    cap = cv2.VideoCapture()
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2500)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1500)
    except Exception:
        pass
    if not cap.open(index, backend):
        cap.release()
        return None
    if not cap.isOpened():
        cap.release()
        return None
    return cap


def _warmup_read(cap: cv2.VideoCapture, tries: int = 8) -> Optional[np.ndarray]:
    frame = None
    for _ in range(tries):
        ok, grabbed = cap.read()
        if ok and grabbed is not None:
            frame = grabbed
            break
        time.sleep(0.03)
    return frame


class CameraService:
    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self.device: Optional[CameraDevice] = None
        self.last_error: str = ""
        self.frame_size: tuple[int, int] = (0, 0)

    def list_devices(self) -> list[CameraDevice]:
        found: list[CameraDevice] = []
        seen: set[int] = set()
        backends = (cv2.CAP_DSHOW, cv2.CAP_MSMF)
        misses = 0
        for index in range(0, 6):
            opened_here = False
            for backend in backends:
                cap = _make_capture(index, backend)
                if cap is None:
                    continue
                frame = _warmup_read(cap, tries=5)
                cap.release()
                time.sleep(0.05)
                if frame is None:
                    continue
                if index not in seen:
                    seen.add(index)
                    label = "Camera " + str(index) + " (" + _backend_name(backend) + ")"
                    found.append(CameraDevice(index, backend, label))
                opened_here = True
                break
            if opened_here:
                misses = 0
            else:
                misses += 1
                if misses >= 2 and found:
                    break
        return found

    def _configure(self, cap: cv2.VideoCapture, fps: int, width: int, height: int) -> None:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FPS, float(max(1, min(60, fps))))
        if width > 0 and height > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

    def _open_capture(
        self, device: CameraDevice, fps: int, width: int, height: int
    ) -> tuple[Optional[cv2.VideoCapture], Optional[np.ndarray]]:
        cap = _make_capture(device.index, device.backend)
        if cap is None:
            return None, None
        self._configure(cap, fps, width, height)
        frame = _warmup_read(cap)
        if frame is None:
            cap.release()
            return None, None
        return cap, frame

    def start(self, device: CameraDevice, fps: int) -> None:
        with self._lock:
            self._stop_unlocked()
            attempts = (
                (1280, 720),
                (960, 540),
                (640, 480),
                (0, 0),
            )
            cap = None
            frame = None
            for width, height in attempts:
                cap, frame = self._open_capture(device, fps, width, height)
                if cap is not None and frame is not None:
                    break
            if cap is None or frame is None:
                fallback = CameraDevice(device.index, cv2.CAP_MSMF if device.backend == cv2.CAP_DSHOW else cv2.CAP_DSHOW, device.label)
                cap, frame = self._open_capture(fallback, fps, 640, 480)
                if cap is not None:
                    device = fallback
            if cap is None or frame is None:
                raise CameraError(
                    "Could not open "
                    + device.label
                    + ". Close other apps using the webcam and allow desktop apps "
                    + "to use the camera in Windows Privacy settings."
                )
            self._cap = cap
            self.device = device
            self.last_error = ""
            self.frame_size = (int(frame.shape[1]), int(frame.shape[0]))

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            cap = self._cap
            if cap is None:
                return None
            ok, frame = cap.read()
            if not ok or frame is None:
                self.last_error = "Lost the camera stream. It may have been disconnected or claimed by another app."
                return None
            self.frame_size = (int(frame.shape[1]), int(frame.shape[0]))
            return frame

    def _stop_unlocked(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.device = None
        self.frame_size = (0, 0)

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()

    @property
    def is_running(self) -> bool:
        return self._cap is not None
