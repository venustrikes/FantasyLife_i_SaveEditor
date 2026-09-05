"""Equipment abilities -- the ``es_*`` ids in a piece's ``grantSkillId`` slots.

A weapon, Life tool, shield or piece of armour carries up to three of these,
and they are what the item card's second page lists.  The save stores only the
id; the name and the description come from the shipped text tables, and this
module is the read side of ``data/fli_abilities.json.gz``, which says **which
ids exist**.

That list cannot come from the game's data tables the way stats do: the PC
release ships an encrypted pak index and the ability table is not in the
executable.  ``tools/build_abilities.py`` gathers the ids from the three places
that are left, and every entry says which it came from -- :meth:`AbilityDB.origin`:

* ``save``  -- the game wrote this id into a real equipment record.
* ``altar`` -- it is in an Aging Altar lot table.
* ``text``  -- the game's own text tables name it, but no save here carries it.

The first two are the ids the editor leads with, because a save has been seen
holding them; the third is the rest of what the game has a word for.

Three things the text tables do not do on their own, and this module does:

* **an id is a family and a level.**  ``es_attack_up06`` is the sixth *Attack
  +*, and the tables name only the family, usually under its first level.  The
  database records which key names each id so the lookup is a dictionary hit
  rather than a rule.

* **fourteen families the tables do not name at all.**  Real saves carry them,
  so the database carries the editor's own words for them, flagged as such --
  see :meth:`AbilityDB.is_glossed`.

* **which gear an ability belongs on.**  Recorded per bag from the saves it was
  read from, which is what lets the picker lead with the abilities that
  actually turn up on the kind of piece being edited.  The field is empty for
  an ability no save here has on a piece, which is not the same as saying it
  cannot go there -- the game puts no such restriction on the record.

Like :mod:`flisave.names` and :mod:`flisave.gear` it loads once, lazily, and
never raises: with the file missing every list comes back empty and the editor
keeps working.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from typing import Dict, List, Optional, Sequence

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = (os.environ.get("FLI_ABILITY_DB")
             or os.path.join(_ROOT, "data", "fli_abilities.json.gz"))

#: ``grantSkillId`` is three slots wide.  Every save the game wrote fills at
#: most the first two; the third is the one the game's card marks with the
#: Aging Altar's leaf, and no save here has a piece the Altar has finished, so
#: the editor offers all three and says which is which rather than guessing.
SLOTS = 3
ABILITY_SLOTS = 2             # the two the game itself writes
NO_ABILITY = "None"           # what an empty slot holds, the game's own word

#: The bags an ability can be seen on, in the order a picker should show them.
BAGS = ("weapon", "tool", "shield", "armour", "mount")

_LEVEL = re.compile(r"_?(\d+)$")


class AbilityDB:
    """The ability catalogue, or an empty stand-in when the file is missing."""

    def __init__(self, path: str, payload: Optional[dict] = None,
                 error: Optional[str] = None):
        self.path = path
        self.error = error
        self.loaded = payload is not None
        payload = payload or {}
        self.source: str = payload.get("source", "")
        self.builds: List[str] = list(payload.get("builds") or ())
        self.entries: Dict[str, dict] = payload.get("abilities") or {}
        self._by_bag: Dict[str, List[str]] = {}

    # --------------------------------------------------------------- lookups
    def __contains__(self, ability: str) -> bool:
        return ability in self.entries

    def ids(self) -> List[str]:
        """Every ability the catalogue knows, sorted."""
        return sorted(self.entries)

    def family(self, ability: str) -> str:
        """The ability without its level -- ``es_attack_up`` for any *Attack +*."""
        entry = self.entries.get(ability)
        if entry:
            return entry.get("family") or ability
        m = _LEVEL.search(ability)
        return ability[:m.start()] if m else ability

    def level(self, ability: str) -> int:
        """Which step of its family this is.  0 for a family with only one."""
        entry = self.entries.get(ability)
        if entry:
            return int(entry.get("level") or 0)
        m = _LEVEL.search(ability)
        return int(m.group(1)) if m else 0

    def origin(self, ability: str) -> str:
        """Where this id was found: ``save``, ``altar``, ``text`` or ``""``."""
        return (self.entries.get(ability) or {}).get("from", "")

    def seen(self, ability: str) -> bool:
        """True when a real save has carried this ability on a piece of gear."""
        return self.origin(ability) == "save"

    def is_glossed(self, ability: str) -> bool:
        """True when the name below is the editor's own, not the game's.

        Fourteen families are in no shipped text table at any spelling.  A
        caller that shows a name to someone should say so for these.
        """
        return "gloss" in (self.entries.get(ability) or {})

    def name(self, ability: str, language: str = "en") -> str:
        """What to call this ability.  The id itself if nothing names it.

        The game's own name where the text tables have one -- in *language*,
        falling back the way :mod:`flisave.names` does -- then the editor's
        gloss, then the raw id.  The level is not in the name: the game does
        not show it either, and :meth:`level` is there for a caller that wants
        to put it in a column of its own.
        """
        from . import names as _names
        entry = self.entries.get(ability) or {}
        key = entry.get("text")
        if key:
            # Some rows are padded with an ideographic space the game's own
            # layout swallowed; a list widget does not.
            found = (_names.get().resolve(key, language) or "").strip("　 ")
            if found:
                return found
        return entry.get("gloss") or ability

    def description(self, ability: str, language: str = "en") -> str:
        """The line under the name on the item card, or ``""``.

        The tables describe about a fifth of the families, and the text they do
        carry is the template with ``<SKILL_PARAM_1>`` still in it -- the game
        fills those from a table that is not in the save or the executable, so
        the placeholder is left standing rather than invented over.
        """
        from . import names as _names
        key = (self.entries.get(ability) or {}).get("text")
        if not key:
            return ""
        return _names.get().description(key, language) or ""

    def bags(self, ability: str) -> List[str]:
        """The kinds of gear this ability has been seen on, commonest first."""
        counts = (self.entries.get(ability) or {}).get("bags") or {}
        return [b for b, _n in sorted(counts.items(),
                                      key=lambda kv: (-kv[1], kv[0]))]

    def for_bag(self, bag: str) -> List[str]:
        """Every ability seen on *bag*, commonest there first.

        Empty for a bag no save here had gear in, which a caller should read as
        "nothing to lead with" rather than "nothing allowed": the game puts no
        such restriction on the field, so the picker still offers the rest.
        """
        found = self._by_bag.get(bag)
        if found is None:
            found = sorted(
                (a for a, e in self.entries.items() if bag in (e.get("bags") or {})),
                key=lambda a: (-self.entries[a]["bags"][bag], a))
            self._by_bag[bag] = found
        return list(found)

    def search(self, query: str, language: str = "en",
               bag: Optional[str] = None) -> List[str]:
        """Abilities whose name or id matches *query*, best-placed first.

        The match is case-insensitive and on either the shown name or the id,
        because someone reading a save is as likely to have the id in front of
        them as the name.  With *bag* given, the ones that belong on that kind
        of gear come first rather than the rest being dropped.
        """
        want = (query or "").strip().lower()
        found = [a for a in self.entries
                 if not want or want in a.lower()
                 or want in self.name(a, language).lower()]
        lead = set(self.for_bag(bag)) if bag else set()
        return sorted(found, key=lambda a: (a not in lead,
                                            self.origin(a) == "text",
                                            self.name(a, language).lower(),
                                            self.level(a)))

    def suggest(self, item_id: str, bag: Optional[str] = None,
                limit: int = SLOTS) -> List[str]:
        """The abilities worth putting on this piece, best first.

        The Aging Altar's own lot table where the game has one for this kind of
        gear -- weapons, Life tools and shields -- because that is the game's
        answer to the same question.  Body armour has no Altar category at all,
        so it falls back to what the saves show on armour, which is the next
        best thing to the game's own opinion and is marked differently by the
        callers that show it.
        """
        from . import gear as _gear
        picks = [a for a in _gear.ripening_skills(item_id) if a in self.entries]
        if not picks and bag:
            picks = self.for_bag(bag)
        return picks[:limit]

    def suggestion_source(self, item_id: str) -> str:
        """``"altar"`` when :meth:`suggest` had the game's own table, else ``"seen"``."""
        from . import gear as _gear
        return "altar" if _gear.ripening_skills(item_id) else "seen"

    def normalise(self, values: Sequence[str]) -> List[str]:
        """*values* as the three slots a record wants, ``"None"`` for empty."""
        out = [str(v) if v and str(v) != NO_ABILITY else NO_ABILITY
               for v in values][:SLOTS]
        return out + [NO_ABILITY] * (SLOTS - len(out))


_cache: Optional[AbilityDB] = None


def get(path: Optional[str] = None) -> AbilityDB:
    """The catalogue, loaded once.  Never raises -- see the module docstring."""
    global _cache
    if _cache is not None and path is None:
        return _cache
    target = path or DATA_FILE
    try:
        with gzip.open(target, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
        db = AbilityDB(target, payload)
    except Exception as exc:                       # a missing file is not fatal
        db = AbilityDB(target, None, "%s: %s" % (type(exc).__name__, exc))
    if path is None:
        _cache = db
    return db


def ids() -> List[str]:
    return get().ids()


def name(ability: str, language: str = "en") -> str:
    return get().name(ability, language)


def description(ability: str, language: str = "en") -> str:
    return get().description(ability, language)


def search(query: str, language: str = "en", bag: Optional[str] = None):
    return get().search(query, language, bag)


def suggest(item_id: str, bag: Optional[str] = None, limit: int = SLOTS):
    return get().suggest(item_id, bag, limit)
