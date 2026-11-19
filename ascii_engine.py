"""stuff happens here btw!"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


BANNED = chr(35)
FG = (228, 226, 220)
BG = (10, 10, 12)


def _candidate_characters() -> str:
    chars: list[str] = []
    for code in range(32, 127):
        glyph = chr(code)
        if glyph == BANNED:
            continue
        chars.append(glyph)
    return "".join(chars)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windir = Path(r"C:\Windows\Fonts")
    for name in ("consola.ttf", "cour.ttf", "lucon.ttf", "cascadia.ttf", "CascadiaMono.ttf"):
        path = windir / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


@dataclass
class Atlas:
    chars: np.ndarray
    tiles: np.ndarray
    cell_w: int
    cell_h: int
    count: int


class GlyphAtlas:
    def __init__(self, cell_w: int, cell_h: int) -> None:
        self.cell_w = max(4, int(cell_w))
        self.cell_h = max(8, int(cell_h))
        self.atlas = self._build()

    def _render_glyph(self, font: ImageFont.ImageFont, glyph: str) -> np.ndarray:
        image = Image.new("RGB", (self.cell_w, self.cell_h), BG)
        draw = ImageDraw.Draw(image)
        bbox = draw.textbbox((0, 0), glyph, font=font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        x = (self.cell_w - gw) // 2 - bbox[0]
        y = (self.cell_h - gh) // 2 - bbox[1]
        draw.text((x, y), glyph, font=font, fill=FG)
        return np.asarray(image, dtype=np.uint8)

    def _build(self) -> Atlas:
        font = _load_font(max(8, self.cell_h - 1))
        measured: list[tuple[float, str, np.ndarray]] = []
        for glyph in _candidate_characters():
            tile = self._render_glyph(font, glyph)
            measured.append((float(tile.mean()), glyph, tile))
        measured.sort(key=lambda item: item[0])

        compacted: list[tuple[str, np.ndarray]] = []
        last_weight = -1.0
        for weight, glyph, tile in measured:
            if compacted and abs(weight - last_weight) < 0.22 and glyph != " ":
                continue
            compacted.append((glyph, tile))
            last_weight = weight

        if compacted[0][0] != " ":
            compacted.insert(0, (" ", self._render_glyph(font, " ")))

        chars = np.array([item[0] for item in compacted])
        tiles = np.stack([item[1] for item in compacted], axis=0)
        palette = "".join(chars.tolist())
        if BANNED in palette:
            raise RuntimeError("Character palette contained a banned glyph.")
        return Atlas(chars=chars, tiles=tiles, cell_w=self.cell_w, cell_h=self.cell_h, count=len(chars))


class AsciiEngine:
    def __init__(self) -> None:
        self._atlas_key: tuple[int, int] | None = None
        self._atlas: Atlas | None = None
        self._clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
        self._lock = threading.Lock()
        self.last_indices: np.ndarray | None = None
        self.last_rgb: np.ndarray | None = None

    def atlas(self, cell_w: int, cell_h: int) -> Atlas:
        key = (cell_w, cell_h)
        if self._atlas is None or self._atlas_key != key:
            self._atlas = GlyphAtlas(cell_w, cell_h).atlas
            self._atlas_key = key
        return self._atlas

    def grid_size(self, frame: np.ndarray, columns: int, cell_w: int, cell_h: int) -> tuple[int, int]:
        height, width = frame.shape[:2]
        columns = max(40, int(columns))
        cell_aspect = float(cell_w) / float(cell_h)
        rows = int(round(columns * (height / max(1, width)) * cell_aspect))
        return columns, max(20, rows)

    def convert(
        self,
        frame_bgr: np.ndarray,
        columns: int,
        cell_w: int,
        cell_h: int,
        contrast: float,
        brightness: float,
        detail: float,
    ) -> np.ndarray:
        atlas = self.atlas(cell_w, cell_h)
        cols, rows = self.grid_size(frame_bgr, columns, atlas.cell_w, atlas.cell_h)

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        mid = cv2.resize(gray, (cols * 3, rows * 3), interpolation=cv2.INTER_AREA)
        mid = self._clahe.apply(mid)
        sampled = cv2.resize(mid, (cols, rows), interpolation=cv2.INTER_AREA)

        work = sampled.astype(np.float32)
        if detail > 0.01:
            blur = cv2.GaussianBlur(work, (0, 0), 0.65)
            work = work + detail * (work - blur)

        work = (work - 127.5) * contrast + 127.5 + brightness * 255.0
        np.clip(work, 0.0, 255.0, out=work)

        scale = (atlas.count - 1) / 255.0
        indices = (work * scale + 0.5).astype(np.int32)
        np.clip(indices, 0, atlas.count - 1, out=indices)

        tiles = atlas.tiles[indices]
        rgb = np.transpose(tiles, (0, 2, 1, 3, 4)).reshape(
            rows * atlas.cell_h,
            cols * atlas.cell_w,
            3,
        )
        rgb = np.ascontiguousarray(rgb)
        with self._lock:
            self.last_indices = indices
            self.last_rgb = rgb
        return rgb

    def snapshot_rgb(self) -> np.ndarray | None:
        with self._lock:
            if self.last_rgb is None:
                return None
            return self.last_rgb

    def current_text(self) -> str:
        with self._lock:
            if self.last_indices is None or self._atlas is None:
                return ""
            glyphs = self._atlas.chars[self.last_indices]
        lines = ["".join(row.tolist()) for row in glyphs]
        text = "\n".join(lines)
        if BANNED in text:
            text = text.replace(BANNED, "@")
        return text
