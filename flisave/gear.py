"""Equipment stats and the shield/armour split -- the read side of the gear database.

``tools/build_geardb.py`` pulls the game's own equipment tables out of the pak
and writes them to ``data/fli_gear.json.gz``; this module reads that file.  Like
:mod:`flisave.names` it loads once, lazily, and never raises: with the database
missing, stat lookups answer ``None`` and the editor keeps working.

Four things live here that the save format alone cannot tell you:

* **the stat list.**  A weapon's attack is not stored in the save.  The record
  carries an ``EItemTitleType`` and the game reads
  ``physicalOffenseList[title - 1]`` from its data table, so a weapon spawned at
  a title the item has no entry for reads as 0 in game.  ``1`` is the table's
  filler for "this item does not exist at this grade".  Life tools are graded
  the same way out of their own table, and read 0 power for the same reason.

* **the Aging Altar's best roll.**  An aged piece carries three ``es_*``
  equipment skills, and which three depends on the kind of gear it is.

* **which ``iam`` ids are shields.**  Shields are a separate inventory
  category from armour, and an item dropped in the wrong bag never shows up.

* **every material and recipe id**, for the bulk fills.  The name database is
  keyed by things that have a name, and recipes have none.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = (os.environ.get("FLI_GEAR_DB")
             or os.path.join(_ROOT, "data", "fli_gear.json.gz"))

TITLES = ["None", "Rag", "Normal", "Masterpiece", "Supreme", "Legend"]
_MATERIAL_ID = re.compile(r"^imt\d{6,}$")
SENTINEL = 1                  # "this item does not exist at this grade"

# The shipped database is the source of truth; this is what it held when the
# module was written, so the shield bag is still picked correctly when the
# database is missing.  Twenty ids, so it costs nothing to carry.
_FALLBACK_SHIELDS = frozenset((
    "iam00000007", "iam01003420", "iam01003430", "iam01003440", "iam01003450",
    "iam01003460", "iam01003470", "iam01003480", "iam01003490", "iam01003500",
    "iam01003510", "iam01004950", "iam01007000", "iam01007010", "iam01007020",
    "iam01007030", "iam01007040", "iam01007050", "iam01007060", "iam01007070",
))


class GearDB:
    """Per-title equipment stats, or an empty stand-in when the file is missing."""

    def __init__(self, path: str, payload: Optional[dict] = None,
                 error: Optional[str] = None):
        self.path = path
        self.error = error
        self.loaded = payload is not None
        payload = payload or {}
        self.source: str = payload.get("source", "")
        self.titles: List[str] = payload.get("titles") or list(TITLES)
        self.sentinel: int = payload.get("sentinel", SENTINEL)
        self.weapons: Dict[str, dict] = payload.get("weapons") or {}
        self.tools = frozenset(payload.get("tools") or ())
        self.op = payload.get("op_skills") or {}
        self.shields = frozenset(payload.get("shields") or _FALLBACK_SHIELDS)
        self.materials: List[str] = payload.get("materials") or []
        self.recipes: List[str] = payload.get("recipes") or []

    # --------------------------------------------------------------- lookups
    def stats(self, item_id: str) -> Optional[dict]:
        """``{"phys": [...5], "mag": [...5]}`` indexed by title - 1, or None."""
        return self.weapons.get(item_id)

    def attack(self, item_id: str, title: int) -> Optional[int]:
        """Physical attack at *title*, or None when the item has no stat list.

        Title 0 has no entry of its own; the game only hands out untitled gear
        whose entries are all equal, so the first one stands in for it.
        """
        row = self.stats(item_id)
        if row is None:
            return None
        values = row.get("phys") or []
        index = max(0, min(len(values) - 1, title - 1))
        return values[index] if values else None

    def best_title(self, item_id: str) -> int:
        """The title with the most attack, or 0 for anything with no stat list.

        Untitled is what the game itself writes on gear it grants, so it is the
        safe answer when there is nothing to choose between.
        """
        row = self.stats(item_id)
        if row is None:
            return 0
        values = row.get("phys") or []
        if not values or len(set(values)) == 1:
            return 0
        best = max(range(len(values)), key=lambda i: values[i])
        return best + 1

    def title_choices(self, item_id: str):
        """``[(title, name, attack), ...]`` for a picker.  Empty without stats."""
        row = self.stats(item_id)
        if row is None:
            return []
        values = row.get("phys") or []
        return [(i + 1, self.titles[i + 1], v) for i, v in enumerate(values)]

    def is_shield(self, item_id: str) -> bool:
        return item_id in self.shields

    def is_tool(self, item_id: str) -> bool:
        """True for a Life tool, whose stat list is power rather than attack."""
        return item_id in self.tools

    def stat_label(self, item_id: str) -> str:
        return "power" if self.is_tool(item_id) else "attack"

    def op_skills(self, item_id: str) -> List[str]:
        """The three equipment skills the Aging Altar's best roll would give.

        Empty for anything the Altar does not take -- body armour, consumables
        -- so a caller can leave those alone rather than invent skills for them.
        """
        return list(self.op.get(item_id) or ())

    def every(self, kind: str) -> List[str]:
        """Every id of one kind: "materials" or "recipes".

        Materials fall back to the name database, which knows all but the
        handful of unnamed ones, so the bulk fill still works without this file.
        """
        if kind == "materials":
            if self.materials:
                return list(self.materials)
            from . import names as _names
            db = _names.get()
            found = set()
            for table in db.names.values():
                found.update(k for k in table if _MATERIAL_ID.match(k))
            return sorted(found)
        if kind == "recipes":
            return list(self.recipes)
        raise KeyError("no such id list: %r" % kind)


_cache: Optional[GearDB] = None


def get(path: Optional[str] = None) -> GearDB:
    """The gear database, loaded once."""
    global _cache
    if path is None and _cache is not None:
        return _cache
    target = path or DATA_FILE
    try:
        with gzip.open(target, "rb") as fh:
            db = GearDB(target, json.loads(fh.read().decode("utf-8")))
    except Exception as exc:
        db = GearDB(target, None, "%s: %s" % (type(exc).__name__, exc))
    if path is None:
        _cache = db
    return db


def stats(item_id: str) -> Optional[dict]:
    return get().stats(item_id)


def attack(item_id: str, title: int) -> Optional[int]:
    return get().attack(item_id, title)


def best_title(item_id: str) -> int:
    return get().best_title(item_id)


def title_choices(item_id: str):
    return get().title_choices(item_id)


def is_shield(item_id: str) -> bool:
    return get().is_shield(item_id)


def is_tool(item_id: str) -> bool:
    return get().is_tool(item_id)


def stat_label(item_id: str) -> str:
    return get().stat_label(item_id)


def op_skills(item_id: str) -> List[str]:
    return get().op_skills(item_id)


def every(kind: str) -> List[str]:
    return get().every(kind)
