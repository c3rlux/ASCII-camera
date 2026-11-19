"""ascii camera"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

from ascii_engine import AsciiEngine, BANNED
from camera import CameraError, CameraService
from clipboard_io import save_text
from virtual_out import VirtualOut


class CaptureLoop(threading.Thread):
    def __init__(self, app: "AsciiCameraApp") -> None:
        super().__init__(name="ascii-capture", daemon=True)
        self.app = app
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.perf_counter()
            try:
                self.app.process_frame()
            except Exception as exc:
                self.app._process_error = str(exc)
                self.stop_event.wait(0.25)
                continue
            fps = max(1.0, float(self.app._opts["fps"]))
            remain = (1.0 / fps) - (time.perf_counter() - started)
            if remain > 0:
                self.stop_event.wait(remain)


class AsciiCameraApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ASCII Camera")
        self.root.geometry("1280x800")
        self.root.minsize(900, 600)
        self.root.configure(bg="gray4")
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.settings = {
            "columns": tk.DoubleVar(value=210),
            "density": tk.DoubleVar(value=1.0),
            "contrast": tk.DoubleVar(value=1.28),
            "brightness": tk.DoubleVar(value=0.04),
            "fps": tk.DoubleVar(value=30),
        }
        self.running = False
        self.fullscreen = False
        self.camera_index = 0
        self.devices = []
        self.status_text = tk.StringVar(value="Looking for cameras...")
        self.error_text = tk.StringVar(value="")
        self.fps_text = tk.StringVar(value="FPS 0")
        self.camera_choice = tk.StringVar(value="No camera")

        self.camera = CameraService()
        self.engine = AsciiEngine()
        self.virtual = VirtualOut()
        self._photo: ImageTk.PhotoImage | None = None
        self._stream_fps = 0.0
        self._last_convert = 0.0
        self._last_shown = -1.0
        self._opening = False
        self._worker = CaptureLoop(self)
        self._closed = False
        self._drop_camera = False
        self._process_error = ""
        self._opts = {
            "columns": 210.0,
            "density": 1.0,
            "contrast": 1.28,
            "brightness": 0.04,
            "fps": 30.0,
        }

        self._build_style()
        self._build_ui()
        self.root.bind("<space>", lambda _e: self.toggle_camera())
        self.root.bind("<F>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<f>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<c>", lambda _e: self.copy_frame())
        self.root.bind("<C>", lambda _e: self.copy_frame())
        self.root.bind("<s>", lambda _e: self.save_frame())
        self.root.bind("<S>", lambda _e: self.save_frame())
        self.root.bind("<Escape>", self._on_escape)

        self.root.after(80, self._discover_and_start)
        self.root.after(16, self._refresh_view)
        self._worker.start()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background="gray8", foreground="gray90", fieldbackground="gray12")
        style.configure("TFrame", background="gray8")
        style.configure("TLabel", background="gray8", foreground="gray70")
        style.configure("Title.TLabel", background="gray8", foreground="gray90")
        style.configure("Error.TLabel", background="gray8", foreground="tomato")
        style.configure("TButton", background="gray17", foreground="gray90", padding=6, borderwidth=1)
        style.map("TButton", background=[("active", "gray25")])
        style.configure("TCombobox", fieldbackground="gray12", background="gray12", foreground="gray90")
        style.configure("Horizontal.TScale", background="gray8", troughcolor="gray20")

    def _build_ui(self) -> None:
        self.view = tk.Label(self.root, bg="gray4", fg="gray80", text="Start the camera to begin.", anchor="center")
        self.view.pack(side="top", fill="both", expand=True)

        self.panel = ttk.Frame(self.root, padding=(14, 10, 14, 10))
        self.panel.pack(side="bottom", fill="x")

        row = ttk.Frame(self.panel)
        row.pack(fill="x")

        self.start_btn = ttk.Button(row, text="Start", command=self.toggle_camera, width=12)
        self.start_btn.pack(side="left", padx=(0, 8))

        self.camera_box = ttk.Combobox(row, textvariable=self.camera_choice, state="readonly", width=28)
        self.camera_box.pack(side="left", padx=(0, 8))
        self.camera_box.bind("<<ComboboxSelected>>", lambda _e: self._on_camera_selected())

        ttk.Button(row, text="Copy", command=self.copy_frame, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Save", command=self.save_frame, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Fullscreen", command=self.toggle_fullscreen, width=12).pack(side="left", padx=(0, 8))
        self.virtual_btn = ttk.Button(row, text="Virtual cam", command=self.toggle_virtual, width=14)
        self.virtual_btn.pack(side="left", padx=(0, 8))
        ttk.Label(row, textvariable=self.fps_text, style="Title.TLabel").pack(side="right")

        sliders = ttk.Frame(self.panel)
        sliders.pack(fill="x", pady=(10, 4))
        specs = (
            ("columns", "Resolution", 80, 320, 1),
            ("density", "Density", 0.70, 1.45, 0.01),
            ("contrast", "Contrast", 0.60, 2.40, 0.01),
            ("brightness", "Brightness", -0.45, 0.45, 0.01),
            ("fps", "Frame rate", 10, 60, 1),
        )
        for index, spec in enumerate(specs):
            cell = ttk.Frame(sliders)
            cell.grid(row=0, column=index, sticky="ew", padx=(0, 12))
            sliders.columnconfigure(index, weight=1)
            header = ttk.Frame(cell)
            header.pack(fill="x")
            ttk.Label(header, text=spec[1]).pack(side="left")
            value_label = ttk.Label(header, text="")
            value_label.pack(side="right")
            integer = spec[4] == 1 and spec[0] in ("columns", "fps")
            var = self.settings[spec[0]]

            def refresh(lbl=value_label, source=var, whole=integer) -> None:
                raw = float(source.get())
                lbl.configure(text=str(int(round(raw))) if whole else "{:.2f}".format(raw))

            var.trace_add("write", lambda *_args, fn=refresh: fn())
            refresh()
            ttk.Scale(cell, variable=var, from_=spec[2], to=spec[3], orient="horizontal").pack(fill="x")

        ttk.Label(self.panel, textvariable=self.status_text).pack(anchor="w")
        ttk.Label(self.panel, textvariable=self.error_text, style="Error.TLabel").pack(anchor="w")
        ttk.Label(
            self.panel,
            text="Space start/stop    F fullscreen    C copy    S save    Esc quit fullscreen    Virtual cam shares to Discord/OBS",
        ).pack(anchor="w", pady=(4, 0))

    def _discover_and_start(self) -> None:
        def work() -> None:
            err = ""
            found = []
            try:
                found = self.camera.list_devices()
            except Exception as exc:
                err = str(exc)
            self.root.after(0, lambda: self._apply_devices(found, err))

        threading.Thread(target=work, name="camera-discover", daemon=True).start()

    def _apply_devices(self, found: list, err: str) -> None:
        self.devices = found
        if err:
            self.error_text.set("Camera discovery failed: " + err)
            self.status_text.set("Idle")
            return
        if not self.devices:
            self.error_text.set(
                "No webcam was found. Connect a camera, close other apps using it, "
                "and allow desktop apps to use the camera in Windows privacy settings."
            )
            self.status_text.set("Idle")
            self.camera_box["values"] = ("No camera",)
            self.camera_choice.set("No camera")
            return
        labels = [device.label for device in self.devices]
        self.camera_box["values"] = labels
        self.camera_choice.set(labels[0])
        self.camera_index = 0
        self.error_text.set("")
        self.status_text.set("Ready")
        self.root.after(250, self.toggle_camera)

    def _selected_device(self):
        if not self.devices:
            return None
        label = self.camera_choice.get()
        for index, device in enumerate(self.devices):
            if device.label == label:
                self.camera_index = index
                return device
        return self.devices[self.camera_index]

    def _on_camera_selected(self) -> None:
        if not self.running:
            device = self._selected_device()
            if device:
                self.status_text.set("Selected " + device.label)
            return
        self.running = False
        self.camera.stop()
        self._open_selected_camera()

    def _open_selected_camera(self) -> None:
        device = self._selected_device()
        if device is None:
            self.error_text.set("No webcam is available to start.")
            self.status_text.set("Idle")
            self.start_btn.configure(text="Start")
            return
        if self._opening:
            return
        self._opening = True
        self.start_btn.configure(state="disabled")
        self.status_text.set("Opening " + device.label + "...")
        fps = int(self._opts["fps"])

        def work() -> None:
            err = ""
            try:
                self.camera.start(device, fps)
            except CameraError as exc:
                err = exc.message
            except Exception as exc:
                err = str(exc)
            self.root.after(0, lambda: self._finish_open(err))

        threading.Thread(target=work, name="camera-open", daemon=True).start()

    def _finish_open(self, err: str) -> None:
        self._opening = False
        self.start_btn.configure(state="normal")
        if self._closed:
            self.camera.stop()
            return
        if err:
            self.running = False
            self.start_btn.configure(text="Start")
            self.error_text.set(err)
            self.status_text.set("Camera unavailable.")
            return
        self.running = True
        self.start_btn.configure(text="Stop")
        self.error_text.set("")
        self.status_text.set("Live")
        self._last_convert = 0.0
        self._stream_fps = 0.0

    def toggle_camera(self) -> None:
        if self._opening:
            return
        if self.running:
            self.running = False
            self.camera.stop()
            self.start_btn.configure(text="Start")
            self.status_text.set("Camera stopped.")
            self.error_text.set("")
            return
        self._open_selected_camera()

    def copy_frame(self) -> None:
        try:
            text = self.engine.current_text()
            if not text:
                raise RuntimeError("There is no ASCII frame to copy yet.")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            self.status_text.set("Copied ASCII frame to clipboard.")
            self.error_text.set("")
        except Exception as exc:
            self.error_text.set(str(exc))

    def save_frame(self) -> None:
        try:
            path = save_text(self.engine.current_text(), self.root)
            if path:
                self.status_text.set("Saved " + path)
                self.error_text.set("")
        except Exception as exc:
            self.error_text.set(str(exc))

    def toggle_virtual(self) -> None:
        if self.virtual.active:
            self.virtual.stop()
            self.virtual_btn.configure(text="Virtual cam")
            self.status_text.set("Virtual camera stopped.")
            self.error_text.set("")
            return
        try:
            name = self.virtual.start(int(self._opts["fps"]))
        except Exception as exc:
            self.error_text.set(str(exc))
            return
        self.virtual_btn.configure(text="Stop virtual")
        self.error_text.set("")
        self.status_text.set("Sharing as " + name + ". Select it as the camera in Discord or OBS.")

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        if self.fullscreen:
            self.panel.pack_forget()
        else:
            self.panel.pack(side="bottom", fill="x")

    def _on_escape(self, _event: tk.Event) -> None:
        if self.fullscreen:
            self.toggle_fullscreen()
        else:
            self.shutdown()

    def _cell_size(self) -> tuple[int, int]:
        density = float(self._opts["density"])
        cell_w = int(round(7 * density))
        cell_h = int(round(14 * density))
        return max(5, cell_w), max(10, cell_h)

    def process_frame(self) -> None:
        if self._closed or not self.running:
            return
        frame = self.camera.read()
        if frame is None:
            if self.camera.last_error:
                self._drop_camera = True
            return
        cell_w, cell_h = self._cell_size()
        self.engine.convert(
            frame,
            columns=int(self._opts["columns"]),
            cell_w=cell_w,
            cell_h=cell_h,
            contrast=float(self._opts["contrast"]),
            brightness=float(self._opts["brightness"]),
            detail=0.62,
        )
        rgb = self.engine.snapshot_rgb()
        if rgb is not None and self.virtual.active:
            self.virtual.send(rgb)
        now = time.perf_counter()
        if self._last_convert > 0:
            dt = now - self._last_convert
            if dt > 0:
                inst = 1.0 / dt
                self._stream_fps = inst if self._stream_fps == 0 else self._stream_fps * 0.82 + inst * 0.18
        self._last_convert = now

    def _refresh_view(self) -> None:
        if self._closed:
            return
        for key, var in self.settings.items():
            self._opts[key] = float(var.get())
        if self._process_error:
            self.error_text.set(self._process_error)
            self._process_error = ""
        if self._drop_camera:
            self._drop_camera = False
            self.running = False
            self.camera.stop()
            self.start_btn.configure(text="Start")
            self.error_text.set(self.camera.last_error or "Lost the camera stream.")
            self.status_text.set("Camera unavailable.")
        elif self.running and self.camera.frame_size != (0, 0):
            width, height = self.camera.frame_size
            current = self.status_text.get()
            if current.startswith("Live") or current in ("Ready", ""):
                self.status_text.set("Live  " + str(width) + "x" + str(height))
        try:
            rgb = self.engine.snapshot_rgb()
            if rgb is not None and self._last_shown != self._last_convert:
                image = Image.fromarray(rgb, mode="RGB")
                vw = max(2, self.view.winfo_width())
                vh = max(2, self.view.winfo_height())
                if vw > 4 and vh > 4:
                    scale = min(vw / max(1, image.width), vh / max(1, image.height))
                    dest = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                    if dest != image.size:
                        image = image.resize(dest, Image.Resampling.NEAREST)
                    self._photo = ImageTk.PhotoImage(image)
                    self.view.configure(image=self._photo, text="")
                    self._last_shown = self._last_convert
        except Exception as exc:
            self.error_text.set("Display error: " + str(exc))
        self.fps_text.set("FPS " + str(int(round(self._stream_fps))))
        self.root.after(16, self._refresh_view)

    def shutdown(self) -> None:
        self._closed = True
        self.running = False
        self._worker.stop_event.set()
        self.virtual.stop()
        self.camera.stop()
        self._worker.join(timeout=1.0)
        self.root.destroy()


def self_test() -> int:
    engine = AsciiEngine()
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:180, 0:320]
    frame[:, :, 0] = (xx * 255 / 319).astype(np.uint8)
    frame[:, :, 1] = (yy * 255 / 179).astype(np.uint8)
    frame[:, :, 2] = 90
    face = ((((xx - 160) ** 2) / 1400 + ((yy - 70) ** 2) / 900) < 1).astype(np.uint8) * 200
    frame[:, :, 1] = np.maximum(frame[:, :, 1], face)
    rgb = engine.convert(frame, 120, 7, 14, 1.3, 0.0, 0.6)
    text = engine.current_text()
    assert rgb.ndim == 3
    assert engine._atlas is not None and engine._atlas.count > 20
    assert BANNED not in text
    assert len(text.splitlines()) >= 20

    camera = CameraService()
    devices = camera.list_devices()
    fps = 0.0
    count = 0
    if devices:
        camera.start(devices[0], 30)
        start = time.perf_counter()
        while count < 45:
            grabbed = camera.read()
            if grabbed is None:
                break
            engine.convert(grabbed, 200, 7, 14, 1.28, 0.04, 0.62)
            count += 1
        elapsed = time.perf_counter() - start
        camera.stop()
        fps = count / elapsed if elapsed else 0.0
    print("camera_devices", len(devices))
    print("camera_frames", count)
    print("convert_fps", round(fps, 2))
    print("palette_chars", engine._atlas.count if engine._atlas else 0)
    print("self_test_ok", True)
    return 0


if __name__ == "__main__":
    if BANNED in " .:-=+*MW@":
        raise RuntimeError("Palette construction failed.")
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    window = tk.Tk()
    AsciiCameraApp(window)
    window.mainloop()
