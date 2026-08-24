"""Read LEVEL5's text tables out of the shipped .pak files.

The tables are cooked UDataTables serialised with unversioned properties, so
nothing in them is self-describing. The layout, recovered from the data, is:

    uint8[5]  zero
    int32     3
    uint8     zero
    int32     row_count
    row_count x {
        int32 name_index          index into the package name map
        int32 name_number         FName numeric suffix + 1 (0 = no suffix)
        uint8[2]  0x00 0x05
        int32 name_index          repeated
        int32 name_number         repeated
        bytes prefix_tail         table-specific, length auto-detected
        FString values[]          fixed count per table
    }

``GDSItemText`` holds one description per language. ``GDSItemText_Noun`` holds
eight grammatical forms per language (definite article, indefinite article,
prefix, noun -- then the same four in plural); the bare noun is form 3.

The language slot order differs between the two tables. Both orders below were
established from the data itself: Japanese by kana, Korean by hangul, the two
Chinese variants by simplified/traditional character pairs, and the European
languages by their article forms (``le/la/les`` vs ``el/la/los`` vs
``der/die/das`` vs ``il/lo/gli``).
"""
from __future__ import annotations

import collections
import re
import struct
from typing import Dict, List, Optional, Sequence, Tuple

from .uasset import UAsset

LANGUAGES = ["ja", "en", "fr", "it", "de", "es", "zh-Hans", "zh-Hant", "ko"]

# Slot order inside each table's row struct.
DESC_ORDER = ["ja", "en", "fr", "it", "de", "es", "zh-Hans", "zh-Hant", "ko"]
NOUN_ORDER = ["ja", "en", "fr", "es", "de", "it", "zh-Hant", "zh-Hans", "ko"]

NOUN_FORMS = 8                # grammatical forms stored per language
NOUN_FORM_SINGULAR = 3        # index of the bare noun inside a language group
NOUN_FORM_PLURAL = 7

HEADER = 14                   # bytes before the first row
ROW_TAG = b"\x00\x05"         # constant bytes at row_start + 8

ITEM_ID_RE = re.compile(r"^(ic[sf]|iwp|iam|imt|iky|ilt|ive|irp|ico|pac|kit)\d{6,}$")


class DataTableError(Exception):
    pass


def _i32(b: bytes, p: int) -> int:
    return struct.unpack_from("<i", b, p)[0]


def _fstring(b: bytes, p: int, limit: int) -> Tuple[str, int]:
    n = _i32(b, p)
    p += 4
    if n == 0:
        return "", p
    if n > 0:
        if n > 1 << 16 or p + n > limit:
            raise DataTableError("bad utf-8 string length %d at 0x%X" % (n, p - 4))
        return b[p:p + n - 1].decode("utf-8", "replace"), p + n
    n = -n
    if n > 1 << 16 or p + n * 2 > limit:
        raise DataTableError("bad utf-16 string length %d at 0x%X" % (-n, p - 4))
    return b[p:p + (n - 1) * 2].decode("utf-16le", "replace"), p + n * 2


def _fname(names: Sequence[str], index: int, number: int) -> str:
    base = names[index] if 0 <= index < len(names) else "<%d>" % index
    return base if number == 0 else "%s_%d" % (base, number - 1)


class DataTable:
    """A parsed text DataTable: row name -> list of raw string values."""

    def __init__(self, uasset: bytes, uexp: bytes):
        self.names = UAsset(uasset).names
        self.uexp = uexp
        self.declared_rows = _i32(uexp, 10)
        self._starts = self._find_row_starts()
        self.prefix, self.value_count = self._detect_layout()
        self.rows = self._parse()

    # ------------------------------------------------------------ scanning
    def _row_start(self, q: int) -> bool:
        u, n = self.uexp, len(self.names)
        if q + 26 > len(u) or u[q + 8:q + 10] != ROW_TAG:
            return False
        return (_i32(u, q) == _i32(u, q + 10)
                and _i32(u, q + 4) == _i32(u, q + 14)
                and 0 <= _i32(u, q) < n
                and 0 <= _i32(u, q + 4) < 1 << 24)

    def _find_row_starts(self) -> List[int]:
        return [q for q in range(HEADER, len(self.uexp) - 26) if self._row_start(q)]

    def _detect_layout(self) -> Tuple[int, int]:
        """Find the prefix length and value count that make rows tile exactly."""
        votes: collections.Counter = collections.Counter()
        pairs = list(zip(self._starts, self._starts[1:]))[:40]
        for a, b in pairs:
            for prefix in range(18, 160):
                q, count = a + prefix, 0
                try:
                    while q < b:
                        _, q = _fstring(self.uexp, q, b)
                        count += 1
                        if count > 256:
                            raise DataTableError("too many values")
                except DataTableError:
                    continue
                if q == b and count >= 1:
                    votes[(prefix, count)] += 1
                    break
        if not votes:
            raise DataTableError("could not work out the row layout")
        return votes.most_common(1)[0][0]

    # ------------------------------------------------------------- parsing
    def _read_values(self, a: int, end: int, prefix: int) -> Optional[List[str]]:
        """Parse a row's values with *prefix*, or None if they do not tile it."""
        u = self.uexp
        q, values = a + prefix, []
        try:
            while q < end:
                s, q = _fstring(u, q, end)
                values.append(s)
                if len(values) > self.value_count:
                    return None
        except DataTableError:
            return None
        return values if q == end and len(values) == self.value_count else None

    def layout(self) -> Tuple[int, int, int]:
        """(leading fields, forms per language, index of the bare noun)."""
        n = self.value_count
        if n >= NOUN_FORMS * len(NOUN_ORDER):
            forms = NOUN_FORMS
            lead = n - forms * len(NOUN_ORDER)
            return lead, forms, NOUN_FORM_SINGULAR
        forms = max(1, n // len(NOUN_ORDER))
        return 0, forms, 0

    def value_for(self, values: List[str], slot: int) -> str:
        lead, forms, pick = self.layout()
        j = lead + slot * forms + pick
        return values[j] if 0 <= j < len(values) else ""

    def _score(self, values: List[str]) -> int:
        """How much the parse looks like real per-language text."""
        def slot(i):
            return self.value_for(values, i)
        s = 0
        if re.search(r"[぀-ヿ]", slot(0)):
            s += 3
        if re.search(r"[가-힯]", slot(8)):
            s += 3
        en = slot(1)
        if en and re.fullmatch(r"[\x20-\x7e]+", en):
            s += 2
        if re.search(r"[一-鿿]", slot(6)) and re.search(r"[一-鿿]", slot(7)):
            s += 2
        return s

    def _parse(self) -> List[Tuple[str, List[str]]]:
        """Rows carry a variable-length prefix, so resolve it per row.

        The modal prefix fits most rows; the rest are recovered by trying every
        prefix that makes the row's values tile it exactly and keeping the one
        whose language slots actually look like Japanese/English/Korean.
        """
        out: List[Tuple[str, List[str]]] = []
        u = self.uexp
        for i, a in enumerate(self._starts):
            end = self._starts[i + 1] if i + 1 < len(self._starts) else len(u) - 4
            name = _fname(self.names, _i32(u, a), _i32(u, a + 4))
            values = self._read_values(a, end, self.prefix)
            if values is None:
                best, best_score = None, -1
                for p in range(18, 200):
                    if p == self.prefix:
                        continue
                    cand = self._read_values(a, end, p)
                    if cand is None:
                        continue
                    sc = self._score(cand) * 100 - abs(p - self.prefix)
                    if sc > best_score:
                        best, best_score = cand, sc
                values = best
            if values is None:                       # keep whatever we can read
                values = []
                q = a + self.prefix
                try:
                    while len(values) < self.value_count and q < end:
                        s, q = _fstring(u, q, end)
                        values.append(s)
                except DataTableError:
                    pass
            out.append((name, values))
        return out


GD = "Game/Content/GameData/"

NAME_TABLES = [
    GD + "Item/GDSItemText_Noun",
    GD + "Life/GDSLifeText_Noun",
    GD + "Skill/GDSSkillText_Noun",
    GD + "Map/GDSMapText_Noun",
    GD + "Chara/GDSCharaText_Noun",
    GD + "Menu/GDSMenuText_Noun",
    GD + "PlantDungeon/GDSPlantDungeonText_Noun",
]

DESC_TABLES = [
    GD + "Item/GDSItemText",
    GD + "Life/GDSLifeText",
    GD + "Skill/GDSSkillText",
]


class GameText:
    """Names and descriptions for every language the game ships."""

    def __init__(self, pak, name_tables: Sequence[str] = NAME_TABLES,
                 desc_tables: Sequence[str] = DESC_TABLES, on_error=None):
        self.names_by_lang: Dict[str, Dict[str, str]] = {l: {} for l in LANGUAGES}
        self.descs_by_lang: Dict[str, Dict[str, str]] = {l: {} for l in LANGUAGES}
        for t in name_tables:
            try:
                self._load_names(pak, t)
            except Exception as exc:
                if on_error:
                    on_error(t, exc)
        for t in desc_tables:
            try:
                self._load_descs(pak, t)
            except Exception as exc:
                if on_error:
                    on_error(t, exc)

    @staticmethod
    def _table(pak, base: str) -> DataTable:
        return DataTable(pak.read(base + ".uasset"), pak.read(base + ".uexp"))

    def _load_names(self, pak, base: str) -> None:
        t = self._table(pak, base)
        for row, values in t.rows:
            if not row.startswith("name_"):
                continue
            key = row[len("name_"):]
            for slot, lang in enumerate(NOUN_ORDER):
                v = t.value_for(values, slot)
                if v:
                    self.names_by_lang[lang].setdefault(key, v)

    def _load_descs(self, pak, base: str) -> None:
        t = self._table(pak, base)
        for row, values in t.rows:
            key = None
            if row.startswith("desc_itm_"):
                key = row[len("desc_itm_"):]
            elif row.startswith("desc_"):
                key = row[len("desc_"):]
            if not key:
                continue
            for slot, lang in enumerate(DESC_ORDER):
                if slot < len(values) and values[slot]:
                    self.descs_by_lang[lang].setdefault(key, values[slot])

    # --------------------------------------------------------------- query
    def name(self, item_id: str, language: str = "en") -> Optional[str]:
        return self.names_by_lang.get(language, {}).get(item_id)

    def description(self, item_id: str, language: str = "en") -> Optional[str]:
        return self.descs_by_lang.get(language, {}).get(item_id)

    def item_ids(self) -> List[str]:
        ids = set()
        for table in self.names_by_lang.values():
            ids.update(k for k in table if ITEM_ID_RE.match(k))
        return sorted(ids)

    def to_json(self) -> dict:
        return {
            "languages": LANGUAGES,
            "names": self.names_by_lang,
            "descriptions": self.descs_by_lang,
        }
