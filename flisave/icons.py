"""The editor's icon set: the game's own art, loaded lazily as Tk images.

``tools/build_icons.py`` writes ``data/icons/<size>/...`` as plain PNGs, which
Tk 8.6 reads by itself - nothing here needs Pillow, and with the folder missing
every lookup simply answers ``None`` and the editor falls back to text.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.environ.get("FLI_ICONS") or os.path.join(_ROOT, "data", "icons")

SMALL, LARGE = 24, 48


class IconSet:
    """Icons by item id, Life id, category prefix or currency name."""

    def __init__(self, directory: str = ICON_DIR):
        self.directory = directory
        self.error: Optional[str] = None
        self.index: Dict[str, dict] = {}
        self._cache: Dict[Tuple[str, int], object] = {}
        try:
            with open(os.path.join(directory, "index.json"), encoding="utf-8") as fh:
                self.index = json.load(fh)
        except FileNotFoundError:
            self.error = ("no icons in %s - build them with "
                          "tools/build_icons.py <apk>" % directory)
        except Exception as exc:
            self.error = "cannot read the icon index: %s" % exc

    @property
    def loaded(self) -> bool:
        return bool(self.index)

    # ---------------------------------------------------------------- images
    def _photo(self, stem: Optional[str], size: int):
        """A cached PhotoImage for *stem*, or None if it is not there."""
        if not stem:
            return None
        key = (stem, size)
        if key not in self._cache:
            import tkinter as tk
            path = os.path.join(self.directory, str(size), stem + ".png")
            try:
                self._cache[key] = tk.PhotoImage(file=path)
            except Exception:
                self._cache[key] = None
        return self._cache[key]

    def category(self, prefix: str, size: int = SMALL):
        cats = self.index.get("categories", {})
        return self._photo(cats.get(prefix) or cats.get("?"), size)

    def item(self, item_id: str, size: int = SMALL):
        """The item's own icon, or its category chip when it has none."""
        if not item_id or item_id == "None":
            return None
        stem = self.index.get("items", {}).get(item_id)
        return self._photo(stem, size) if stem else self.category(item_id[:3], size)

    def has_art(self, item_id: str) -> bool:
        """True when this item really does have game art of its own."""
        return item_id in self.index.get("items", {})

    def life(self, life_id: str, size: int = SMALL):
        return self._photo(self.index.get("lives", {}).get(life_id), size)

    def currency(self, key: str = "coin", size: int = SMALL):
        return self._photo(self.index.get("currency", {}).get(key), size)

    def stats(self) -> str:
        if not self.loaded:
            return self.error or "no icons loaded"
        return ("icons: %d item, %d Life, %d currency, %d category (%s)"
                % (len(self.index.get("items", {})),
                   len(self.index.get("lives", {})),
                   len(self.index.get("currency", {})),
                   len(self.index.get("categories", {})), self.directory))


_SET: Optional[IconSet] = None


def get() -> IconSet:
    """The shared icon set, read from disk on first use."""
    global _SET
    if _SET is None:
        _SET = IconSet()
    return _SET
