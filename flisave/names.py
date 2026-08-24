"""Item, Life and rank names in every language the game ships.

``tools/build_textdb.py`` pulls the game's own text tables out of the pak and
writes them to ``data/fli_text.json.gz``; this module is the read side of that
file.  It loads once, lazily, and never raises: with the database missing every
lookup answers ``None`` and :attr:`NameDB.error` says why, so the rest of the
editor keeps working without names.

Keys are the ids the save itself stores - ``ics01000780`` for an item,
``life0003`` for a Life, ``life_rank_0004`` for a rank.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

LANGUAGES = ["ja", "en", "fr", "it", "de", "es", "zh-Hans", "zh-Hant", "ko"]
FALLBACK = "en"          # stands in when the wanted language has no entry

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = (os.environ.get("FLI_TEXT_DB")
             or os.path.join(_ROOT, "data", "fli_text.json.gz"))

# Ids shaped like this are the ones you can actually drop into a slot, so search
# floats them above Lives, characters, maps and menu strings.  It is a ranking
# hint only - gamedata.ITEM_ID_RE is the authoritative list of item prefixes.
_PLACEABLE = re.compile(r"^[a-z]{2,4}\d{6,}$")


def _fold(text: str) -> str:
    """Casefolded and stripped of accents, so 'elisir' finds 'Elisìr'."""
    n = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in n if not unicodedata.combining(c))


class NameDB:
    """The shipped name tables, or an empty stand-in when they are missing."""

    def __init__(self, path: str, payload: Optional[dict] = None,
                 error: Optional[str] = None):
        self.path = path
        self.error = error
        self.loaded = payload is not None
        payload = payload or {}
        self.source: str = payload.get("source", "")
        self.languages: List[str] = payload.get("languages") or list(LANGUAGES)
        self.names: Dict[str, Dict[str, str]] = payload.get("names") or {}
        self.descriptions: Dict[str, Dict[str, str]] = payload.get("descriptions") or {}
        self._display: Dict[str, Dict[str, str]] = {}

    # --------------------------------------------------------------- lookups
    def name(self, key: str, language: str = "en") -> Optional[str]:
        """The name in exactly *language*, or None if that language lacks it.

        Use :meth:`resolve` to display a name; this one is the strict form, for
        measuring how much of a save the database actually covers.
        """
        return self.names.get(language, {}).get(key) or None

    def resolve(self, key: str, language: str = "en") -> Optional[str]:
        """The best name to show: *language*, else English, else any language."""
        return self._display_table(language).get(key)

    def description(self, key: str, language: str = "en") -> Optional[str]:
        """Flavour text, falling back the same way :meth:`resolve` does."""
        for lang in self._chain(language):
            hit = self.descriptions.get(lang, {}).get(key)
            if hit:
                return hit
        return None

    def life_name(self, life_id: str, language: str = "en") -> Optional[str]:
        return self.resolve(life_id, language)

    def life_rank_name(self, rank: int, language: str = "en") -> Optional[str]:
        """Name of the rank a save stores as *rank*.

        The stored number is a 0-based index into the ``life_rank_XXXX`` rows,
        so 0 is ``life_rank_0001`` ("None", the Life has not been started) and 2
        is ``life_rank_0003`` ("Fledgling").  Confirmed against the game: a save
        holding 2 shows "Principiante" - the Italian for Fledgling.
        """
        if rank < 0:
            return None
        return self.resolve("life_rank_%04d" % (rank + 1), language)

    def search(self, text: str, language: str = "en", limit: int = 40
               ) -> List[Tuple[str, str]]:
        """``(key, name)`` pairs whose name - or id - contains *text*.

        Ids you can actually put in a slot come first - a search here is nearly
        always looking for one - then Lives, characters and menu strings; within
        each group exact matches lead, then names starting with the text.
        """
        needle = _fold(text.strip())
        if not needle:
            return []
        hits = []
        for key, name in self._display_table(language).items():
            folded = _fold(name)
            if folded == needle:
                rank = 0
            elif folded.startswith(needle):
                rank = 1
            elif needle in folded:
                rank = 2
            elif needle in key.casefold():
                rank = 3
            else:
                continue
            hits.append((0 if _PLACEABLE.match(key) else 1, rank, folded, key, name))
        hits.sort()
        return [(key, name) for _p, _r, _f, key, name in hits[:limit]]

    def stats(self) -> str:
        if not self.loaded:
            return self.error or "name database not loaded"
        size = os.path.getsize(self.path) / 1024.0 if os.path.exists(self.path) else 0.0
        out = ["name database : %s (%.0f KB)" % (self.path, size)]
        if self.source:
            out.append("built from    : %s" % self.source)
        out.append("")
        out.append("  %-8s %8s %14s" % ("language", "names", "descriptions"))
        for lang in self.languages:
            out.append("  %-8s %8d %14d"
                       % (lang, len(self.names.get(lang, {})),
                          len(self.descriptions.get(lang, {}))))
        return "\n".join(out)

    # ---------------------------------------------------------------- innards
    def _chain(self, language: str) -> List[str]:
        """Languages to try, in order, for one lookup."""
        out: List[str] = []
        for lang in [language, FALLBACK] + self.languages:
            if lang and lang not in out:
                out.append(lang)
        return out

    def _display_table(self, language: str) -> Dict[str, str]:
        """Every key that is named anywhere, in *language* where possible."""
        table = self._display.get(language)
        if table is None:
            table = {}
            for lang in self._chain(language):
                for key, value in self.names.get(lang, {}).items():
                    if value:
                        table.setdefault(key, value)
            self._display[language] = table
        return table


def load(path: Optional[str] = None) -> NameDB:
    """Read a database off disk.  Never raises - failures land in ``error``."""
    path = path or DATA_FILE
    try:
        with gzip.open(path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        return NameDB(path, error="no name database at %s - build one with "
                                  "tools/build_textdb.py <pak-or-apk>" % path)
    except Exception as exc:
        return NameDB(path, error="cannot read %s: %s" % (path, exc))
    if not isinstance(payload, dict) or not isinstance(payload.get("names"), dict):
        return NameDB(path, error="%s is not a name database" % path)
    return NameDB(path, payload)


_CACHE: Optional[NameDB] = None


def get(path: Optional[str] = None) -> NameDB:
    """The shared database, loaded on first use."""
    global _CACHE
    if _CACHE is None or (path is not None and path != _CACHE.path):
        _CACHE = load(path)
    return _CACHE
