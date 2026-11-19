"""ASCII webcam streamer discord and obs."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ascii_engine import AsciiEngine
from camera import CameraError, CameraService
from virtual_out import OUT_H, OUT_W, VirtualOut, letterbox


class StreamApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ASCII Cam Output")
        self.root.geometry(str(OUT_W) + "x" + str(OUT_H + 72))
        self.root.minsize(960, 580)
        self.root.configure(bg="gray4")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.camera = CameraService()
        self.engine = AsciiEngine()
        self.virtual = VirtualOut()
        self.running = False
        self._closed = False
        self._drop = False
        self._photo = None
        self._last_shown = -1.0
        self._last_convert = 0.0
        self._stream_fps = 0.0
        self._process_error = ""
        self.status_text = tk.StringVar(value="Starting...")
        self.error_text = tk.StringVar(value="")
        self.fps_text = tk.StringVar(value="FPS 0")

        self.view = tk.Label(self.root, bg="gray4", fg="gray80", text="Opening camera...", anchor="center")
        self.view.pack(side="top", fill="both", expand=True)

        bar = ttk.Frame(self.root, padding=(12, 8, 12, 10))
        bar.pack(side="bottom", fill="x")
        ttk.Label(bar, textvariable=self.status_text).pack(anchor="w")
        ttk.Label(bar, textvariable=self.error_text, foreground="tomato").pack(anchor="w")
        ttk.Label(bar, textvariable=self.fps_text).pack(anchor="w")
        ttk.Label(
            bar,
            text="Discord: Settings > Voice and Video > Camera > OBS Virtual Camera.   "
            "OBS: Sources > Video Capture Device > OBS Virtual Camera, or Window Capture this window.",
        ).pack(anchor="w", pady=(4, 0))

        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="ascii-stream", daemon=True)
        self._worker.start()
        self.root.after(120, self._boot)
        self.root.after(16, self._refresh)

    def _boot(self) -> None:
        def work() -> None:
            err = ""
            label = ""
            try:
                devices = self.camera.list_devices()
                if not devices:
                    raise RuntimeError(
                        "No webcam found. Close other apps using it and allow desktop apps "
                        "to use the camera in Windows privacy settings."
                    )
                self.camera.start(devices[0], 30)
                label = self.virtual.start(30)
                self.running = True
            except CameraError as exc:
                err = exc.message
            except Exception as exc:
                err = str(exc)
            self.root.after(0, lambda: self._booted(label, err))

        threading.Thread(target=work, name="stream-boot", daemon=True).start()

    def _booted(self, label: str, err: str) -> None:
        if err:
            self.running = False
            self.camera.stop()
            self.virtual.stop()
            self.error_text.set(err)
            self.status_text.set("Idle")
            return
        self.error_text.set("")
        self.status_text.set("Live as " + label)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.perf_counter()
            try:
                if self.running and not self._closed:
                    frame = self.camera.read()
                    if frame is None:
                        if self.camera.last_error:
                            self._drop = True
                    else:
                        self.engine.convert(frame, 210, 7, 14, 1.28, 0.04, 0.62)
                        rgb = self.engine.snapshot_rgb()
                        if rgb is not None:
                            self.virtual.send(rgb)
                        now = time.perf_counter()
                        if self._last_convert > 0:
                            dt = now - self._last_convert
                            if dt > 0:
                                inst = 1.0 / dt
                                self._stream_fps = inst if self._stream_fps == 0 else self._stream_fps * 0.82 + inst * 0.18
                        self._last_convert = now
            except Exception as exc:
                self._process_error = str(exc)
                self._stop_event.wait(0.25)
                continue
            remain = (1.0 / 30.0) - (time.perf_counter() - started)
            if remain > 0:
                self._stop_event.wait(remain)

    def _refresh(self) -> None:
        if self._closed:
            return
        if self._process_error:
            self.error_text.set(self._process_error)
            self._process_error = ""
        if self._drop:
            self._drop = False
            self.running = False
            self.camera.stop()
            self.virtual.stop()
            self.error_text.set(self.camera.last_error or "Lost the camera stream.")
            self.status_text.set("Idle")
        try:
            rgb = self.engine.snapshot_rgb()
            if rgb is not None and self._last_shown != self._last_convert:
                framed = letterbox(rgb)
                image = Image.fromarray(framed, mode="RGB")
                vw = max(2, self.view.winfo_width())
                vh = max(2, self.view.winfo_height())
                if vw > 4 and vh > 4:
                    scale = min(vw / OUT_W, vh / OUT_H)
                    dest = (max(1, int(OUT_W * scale)), max(1, int(OUT_H * scale)))
                    if dest != image.size:
                        image = image.resize(dest, Image.Resampling.NEAREST)
                    self._photo = ImageTk.PhotoImage(image)
                    self.view.configure(image=self._photo, text="")
                    self._last_shown = self._last_convert
        except Exception as exc:
            self.error_text.set("Display error: " + str(exc))
        self.fps_text.set("FPS " + str(int(round(self._stream_fps))))
        self.root.after(16, self._refresh)

    def shutdown(self) -> None:
        self._closed = True
        self.running = False
        self._stop_event.set()
        self.virtual.stop()
        self.camera.stop()
        self._worker.join(timeout=1.0)
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    StreamApp(window)
    window.mainloop()
