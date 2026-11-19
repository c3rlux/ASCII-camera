"""so the frames go to obs camera for discord and other things and stuff"""

from __future__ import annotations

import threading
from typing import Optional

import cv2
import numpy as np


OUT_W = 1280
OUT_H = 720
BG = (10, 10, 12)


def letterbox(rgb: np.ndarray, width: int = OUT_W, height: int = OUT_H) -> np.ndarray:
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:, :] = BG
    src_h, src_w = rgb.shape[:2]
    scale = min(width / max(1, src_w), height / max(1, src_h))
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    fitted = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
    x = (width - new_w) // 2
    y = (height - new_h) // 2
    canvas[y : y + new_h, x : x + new_w] = fitted
    return canvas


class VirtualOut:
    def __init__(self) -> None:
        self._cam = None
        self._lock = threading.Lock()
        self.device_name = ""
        self.last_error = ""

    @property
    def active(self) -> bool:
        return self._cam is not None

    def start(self, fps: int = 30) -> str:
        try:
            import pyvirtualcam
        except Exception as exc:
            raise RuntimeError(
                "pyvirtualcam is not installed. Run: pip install pyvirtualcam"
            ) from exc

        with self._lock:
            self.stop_unlocked()
            last_err: Optional[Exception] = None
            for backend in (None, "obs", "unitycapture"):
                try:
                    opts = {
                        "width": OUT_W,
                        "height": OUT_H,
                        "fps": float(max(1, fps)),
                        "fmt": pyvirtualcam.PixelFormat.RGB,
                    }
                    if backend is not None:
                        opts["backend"] = backend
                    cam = pyvirtualcam.Camera(**opts)
                    self._cam = cam
                    self.device_name = str(cam.device)
                    self.last_error = ""
                    return self.device_name
                except Exception as exc:
                    last_err = exc
            detail = str(last_err) if last_err else "unknown error"
            raise RuntimeError(
                "Could not start a virtual webcam. Install OBS Studio once "
                "(the virtual camera driver is included; OBS does not need to stay open). "
                "Then pick OBS Virtual Camera in Discord or OBS. Details: " + detail
            )

    def send(self, rgb: np.ndarray) -> None:
        with self._lock:
            cam = self._cam
            if cam is None:
                return
            cam.send(letterbox(rgb))

    def stop_unlocked(self) -> None:
        cam = self._cam
        self._cam = None
        self.device_name = ""
        if cam is not None:
            try:
                cam.close()
            except Exception:
                pass

    def stop(self) -> None:
        with self._lock:
            self.stop_unlocked()
