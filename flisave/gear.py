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

* **the Aging Altar's own roll.**  The Altar picks a piece's equipment
  skills from one lot table per kind of gear; the head of that table is what
  the editor offers as the suggestion for a piece.

* **which ``iam`` ids are shields.**  Shields are a separate inventory
  category from armour, and an item dropped in the wrong bag never shows up.

* **every material and recipe id**, for the bulk fills.  The name database is
  keyed by things that have a name, and recipes have none.  The other bags a
  bulk fill can reach -- weapons, Life tools, shields, armour, craft items --
  have no list here and are read off the name database instead; see
  :data:`EVERY_KINDS`.
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
SENTINEL = 1                  # "this item does not exist at this grade"

# What a bulk fill is made of, one entry per bag worth filling.  Materials and
# recipes come out of the shipped database, which was built from the game's own
# item tables.  Nothing built a list for the equipment bags or the craft bag, so
# those ids come from the *name* database instead: it is keyed by everything the
# game has a word for, and an item with no name is a table row a player can
# never see, which makes it both the widest list available without the pak and
# the safest one to drop into a save.
EVERY_KINDS = ("materials", "recipes", "weapons", "tools", "shields",
               "armour", "crafts")
_EVERY_ALIAS = {"armor": "armour", "craft": "crafts", "life tools": "tools"}

# The id prefixes each kind is made of.  ``iam`` appears twice because the game
# splits it across two bags, and :meth:`GearDB.every` splits it the same way.
_EVERY_PREFIXES = {
    "materials": ("imt",),
    "weapons": ("iwp",),
    "tools": ("ilt",),
    "shields": ("iam",),
    "armour": ("iam",),
    "crafts": ("icf", "ico"),
}

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
        self.ripening = payload.get("ripening_skills") or {}
        self.shields = frozenset(payload.get("shields") or _FALLBACK_SHIELDS)
        self.materials: List[str] = payload.get("materials") or []
        self.recipes: List[str] = payload.get("recipes") or []
        # every() answers the same question for a whole bag at a time, and the
        # derived lists cost a scan of the name database, so they are kept.
        self._every: Dict[str, List[str]] = {}

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

    def ripening_skills(self, item_id: str) -> List[str]:
        """The top of the Aging Altar's own lot table for this piece.

        Three ids, the head of the table the Altar rolls this kind of gear
        from, so they are what it can put on the piece rather than a guess.
        Empty for anything the Altar does not take -- body armour, consumables
        -- so a caller can leave those alone rather than invent skills for them.
        """
        return list(self.ripening.get(item_id) or ())

    def named_ids(self, prefixes) -> List[str]:
        """Every id the *fallback* language names, whose prefix is in *prefixes*.

        One language rather than the union of all nine, and that language is
        :data:`flisave.names.FALLBACK` -- the one the game itself falls back to
        and the only one the browser build is guaranteed to have loaded, so
        both editors derive the same list from the same table.  It is also the
        better data: the rows English leaves out are the untranslated
        placeholders, ``ico01070200`` and ``ico01080200`` being two prison
        tiles the Japanese table still marks ``(仮)`` -- provisional.

        Empty when there is no name database, which is what makes the callers
        below fall back rather than answer with a short list.
        """
        from . import names as _names
        want = re.compile(r"^(%s)\d{6,}$" % "|".join(prefixes))
        table = _names.get().names.get(_names.FALLBACK) or {}
        return sorted(k for k in table if want.match(k))

    def every(self, kind: str) -> List[str]:
        """Every id of one kind, for the bulk fills -- see :data:`EVERY_KINDS`.

        Materials and recipes come from this database, built from the game's own
        item tables.  It carries no list for the equipment bags or the craft
        bag, so those are read off the name database and ``iam`` is split into
        shields and armour the way the game splits the two bags -- an armour id
        dropped in the shield bag never appears in game.  Weapons and Life tools
        fall back to the stat lists here when there is no name database at all,
        and materials to the ids the name database knows.
        """
        kind = _EVERY_ALIAS.get(kind, kind)
        if kind not in EVERY_KINDS:
            raise KeyError("no such id list: %r" % kind)
        found = self._every.get(kind)
        if found is None:
            found = self._build_every(kind)
            # An empty answer means a database that has not loaded rather than
            # a kind with nothing in it, so it is not worth remembering.
            if found:
                self._every[kind] = found
        return list(found)

    def _build_every(self, kind: str) -> List[str]:
        if kind == "recipes":
            return list(self.recipes)     # recipes have no name to fall back on
        if kind == "materials" and self.materials:
            return list(self.materials)
        found = self.named_ids(_EVERY_PREFIXES[kind])
        if kind == "shields":
            return [i for i in found if self.is_shield(i)] or sorted(self.shields)
        if kind == "armour":
            return [i for i in found if not self.is_shield(i)]
        if not found and kind == "weapons":
            return sorted(k for k in self.weapons if not self.is_tool(k))
        if not found and kind == "tools":
            return sorted(self.tools)
        return found


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


def ripening_skills(item_id: str) -> List[str]:
    return get().ripening_skills(item_id)


def every(kind: str) -> List[str]:
    return get().every(kind)
