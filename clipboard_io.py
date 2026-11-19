"""clipboard thing so you can export and stuff"""

from __future__ import annotations

from tkinter import filedialog
from typing import Optional


def save_text(text: str, parent) -> Optional[str]:
    if not text:
        raise RuntimeError("There is no ASCII frame to save yet.")
    path = filedialog.asksaveasfilename(
        parent=parent,
        title="Save ASCII frame",
        defaultextension=".txt",
        filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
    )
    if not path:
        return None
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.write("\n")
    return path
