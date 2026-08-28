"""Which recipes the player knows -- the list a crafting bench reads.

A recipe is **two** things in this save, and an editor that writes only one of
them produces exactly the symptom that led here: every recipe listed in the
smartphone's recipe app, and a crafting bench that still shows almost nothing.

    1. an ``irp*`` item in bag 8 (``EInventoryCategory::RECIPE``) -- the scroll
       itself, which is what the inventory and the phone list show, and
    2. a bit in ``FRecipeStatusP.recipeInfoMap``, the block parsed here, which
       is what the *bench* reads.

The game writes both at the same moment and they stay in lockstep: on a played
Switch save 837 of the 839 recipe items in the bag have their bit set and not
one bit is set without its item.  On a save whose bag was filled by an editor
they come apart, and it is the bit -- not the item -- that decides whether a
recipe appears in the bench list.

The block
---------

One flat, fixed-length run near the end of the payload::

    uint32  magic  = 0x31CCCDDC
    uint32  count                       every recipe the build defines
    count x { FString recipe_id; uint32 bit_flag }

``count`` is the whole master table rather than a list of what the player has,
which is why it grows with the game build and not with progress: 1788 entries
on the June Switch build, 1883 in December, 2012 on ``rev110414``.  Nothing in
it changes length, so an edit is a poke of four bytes per recipe and no offset
downstream moves.

``bit_flag`` is ``ERecipeSaveCategory``, whose named members the executable
gives as ``Created = 2``, ``Favorite = 4``, ``New = 8``, ``GotWindow = 16``.
Bit 0 has no name in that enum -- it is the "player has this recipe" flag the
crafting UI reads as ``ItemCraftRecipeInfo_Ver2::isHave`` (its neighbour
``isCreated`` being bit 1).  Every value seen in a real save is 0, 1, 3 or 9:
``Created`` and ``New`` never appear without bit 0, which is what pins bit 0 as
the one that means *known*.

Recipe ids are ``recipe_life<NN>_<item>`` and the ``NN`` is the Life that
crafts it -- only the six crafting Lives appear, ``life0009`` Cook through
``life0014`` Artist.  The matching bag item is ``irp_`` + the id with the
leading ``recipe_`` sometimes dropped, which is why the item list and this
list are kept as two databases rather than derived from one another.

Rank still gates the *tabs*: a bench groups its list by the Life rank each
recipe is learned at (``ItemCraftRecipeSelectMenuInfo.rankList``), so a Life
left at rank 0 shows a short list however many bits are set here.  Marking
recipes known and raising the Life's rank are two separate edits and a player
who wants the whole catalogue wants both.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

RECIPE_MAGIC = 0x31CCCDDC
_MAGIC_BYTES = struct.pack("<I", RECIPE_MAGIC)

#: ``ERecipeSaveCategory``, plus the bit the enum does not name.
HAVE = 1              # ItemCraftRecipeInfo_Ver2::isHave -- the crafting gate
CREATED = 2           # ERecipeSaveCategory::Created
FAVORITE = 4          # ERecipeSaveCategory::Favorite
NEW = 8               # ERecipeSaveCategory::New -- the "NEW!" badge
GOT_WINDOW = 16       # ERecipeSaveCategory::GotWindow

FLAG_NAMES = ((HAVE, "have"), (CREATED, "created"), (FAVORITE, "favourite"),
              (NEW, "new"), (GOT_WINDOW, "got window"))

#: The six Lives that craft, in recipe-id order.  Nothing else appears.
CRAFT_LIVES = ("life0009", "life0010", "life0011", "life0012", "life0013",
               "life0014")

_PREFIX = "recipe_life"
_ID_MIN, _ID_MAX = 12, 80          # an FString length that could be a recipe id
_COUNT_MAX = 1 << 14


def life_id_for(recipe_id: str) -> Optional[str]:
    """``recipe_life10_iam01004370`` -> ``life0010``.  None if it is not one."""
    if not recipe_id.startswith(_PREFIX):
        return None
    digits = recipe_id[len(_PREFIX):len(_PREFIX) + 2]
    if not digits.isdigit():
        return None
    return "life%04d" % int(digits)


@dataclass
class Recipe:
    """One row of ``recipeInfoMap``: the recipe's id and its flag word."""
    recipe_id: str
    bit_flag: int
    offset: int                    # where the flag word sits in the payload

    @property
    def life_id(self) -> Optional[str]:
        return life_id_for(self.recipe_id)

    @property
    def known(self) -> bool:
        """Whether the crafting bench will list it."""
        return bool(self.bit_flag & HAVE)

    @property
    def flag_names(self) -> List[str]:
        return [name for bit, name in FLAG_NAMES if self.bit_flag & bit]


class RecipeStatus:
    """``FRecipeStatusP`` -- every recipe the build defines, and its flags."""

    def __init__(self, start: int, end: int, entries: List[Recipe]):
        self.start = start
        self.end = end
        self.entries = entries

    # -------------------------------------------------------------- parsing
    @classmethod
    def parse(cls, payload: bytes) -> Optional["RecipeStatus"]:
        """Find and read the block.  None if this save has no recipe table."""
        at = -1
        while True:
            at = payload.find(_MAGIC_BYTES, at + 1)
            if at < 0:
                return None
            try:
                return cls._parse_at(payload, at)
            except (ValueError, struct.error):
                continue           # a coincidental magic; keep looking

    @classmethod
    def _parse_at(cls, payload: bytes, start: int) -> "RecipeStatus":
        p = start + 4
        count = struct.unpack_from("<I", payload, p)[0]
        p += 4
        if not 1 <= count <= _COUNT_MAX:
            raise ValueError("implausible recipe count %d" % count)
        entries: List[Recipe] = []
        for _ in range(count):
            n = struct.unpack_from("<i", payload, p)[0]
            if not _ID_MIN <= n <= _ID_MAX or p + 4 + n + 4 > len(payload):
                raise ValueError("bad recipe id length %d at 0x%X" % (n, p))
            raw = payload[p + 4:p + 4 + n]
            if raw[-1] != 0:
                raise ValueError("unterminated recipe id at 0x%X" % p)
            name = raw[:-1].decode("ascii", "replace")
            if not name.startswith(_PREFIX):
                raise ValueError("not a recipe id: %r" % name)
            p += 4 + n
            entries.append(Recipe(name, struct.unpack_from("<I", payload, p)[0], p))
            p += 4
        return cls(start, p, entries)

    # -------------------------------------------------------------- reading
    def __len__(self) -> int:
        return len(self.entries)

    @property
    def lives(self) -> List[str]:
        """The Lives this save's table actually names, in id order."""
        seen = {e.life_id for e in self.entries}
        return [l for l in CRAFT_LIVES if l in seen]

    def for_life(self, life_id: str) -> List[Recipe]:
        return [e for e in self.entries if e.life_id == life_id]

    def counts(self) -> Dict[str, Dict[str, int]]:
        """``{life_id: {"known": n, "total": n}}``, plus ``"all"``."""
        out: Dict[str, Dict[str, int]] = {}
        for e in self.entries:
            row = out.setdefault(e.life_id or "?", {"known": 0, "total": 0})
            row["total"] += 1
            row["known"] += e.known
        out["all"] = {"known": sum(e.known for e in self.entries),
                      "total": len(self.entries)}
        return out

    def table(self, names=None, language: str = "en") -> List[dict]:
        """One row per crafting Life, for a list on screen."""
        counts = self.counts()
        rows = []
        for life_id in self.lives:
            row = dict(counts[life_id])
            row["life_id"] = life_id
            row["label"] = life_id
            if names is not None:
                row["label"] = names.life_name(life_id, language) or life_id
            rows.append(row)
        return rows

    # -------------------------------------------------------------- editing
    def learn(self, recipe: Recipe, on: bool = True,
              mark_new: bool = False) -> bool:
        """Mark one recipe known (or not).  True if the flag word moved.

        Only the one bit is written: the ``Created``, ``Favorite`` and ``New``
        bits already on a recipe are the game's own record of what the player
        did with it and are left alone.  *mark_new* adds the "NEW!" badge to
        the rest, which is off by default because two thousand of them at once
        is a list nobody can read.

        Forgetting writes a bare 0, which is the value the game itself leaves
        on a recipe the player has never had -- there is no state where
        ``Created`` or ``Favorite`` outlives ``have``.
        """
        if on:
            want = recipe.bit_flag | HAVE | (NEW if mark_new else 0)
        else:
            want = 0
        if want == recipe.bit_flag:
            return False
        recipe.bit_flag = want
        return True

    def learn_all(self, lives: Optional[Iterable[str]] = None, on: bool = True,
                  mark_new: bool = False) -> int:
        """Mark every recipe of *lives* (all of them by default).  Rows changed."""
        wanted = None if lives is None else set(lives)
        changed = 0
        for e in self.entries:
            if wanted is not None and e.life_id not in wanted:
                continue
            changed += self.learn(e, on, mark_new)
        return changed

    # -------------------------------------------------------------- writing
    def write(self, payload: bytearray) -> int:
        """Poke the flag words back.  Returns how many bytes on disk changed.

        Nothing here changes length -- the ids are left exactly as they were --
        so this is a four-byte write per recipe and no offset behind the block
        moves.
        """
        changed = 0
        for e in self.entries:
            blob = struct.pack("<I", e.bit_flag & 0xFFFFFFFF)
            if payload[e.offset:e.offset + 4] != blob:
                payload[e.offset:e.offset + 4] = blob
                changed += 1
        return changed

    def summary(self) -> str:
        c = self.counts()["all"]
        return "recipes known: %d of %d" % (c["known"], c["total"])


def resolve_lives(which: Optional[Sequence[str]]) -> Optional[List[str]]:
    """Turn ``["10", "cook", "life0011"]`` into Life ids.  None means all of them.

    The names are matched against the shipped text database when it is there
    and against the id when it is not, so ``--life blacksmith`` works from a
    clone with the databases and ``--life 10`` works from one without.
    """
    if not which:
        return None
    from . import names as _names
    try:
        db = _names.get()
    except Exception:                       # pragma: no cover - no database
        db = None
    out: List[str] = []
    for token in which:
        text = str(token).strip()
        low = text.lower()
        hit = None
        if low.startswith("life") and low[4:].isdigit():
            hit = "life%04d" % int(low[4:])
        elif low.isdigit():
            hit = "life%04d" % int(low)
        elif db is not None:
            for life_id in CRAFT_LIVES:
                name = db.life_name(life_id, "en")
                if name and name.lower() == low:
                    hit = life_id
                    break
        if hit is None or hit not in CRAFT_LIVES:
            raise ValueError(
                "no crafting Life called %r -- they are %s"
                % (text, ", ".join("%s (%s)" % (l[4:].lstrip("0"), l)
                                   for l in CRAFT_LIVES)))
        if hit not in out:
            out.append(hit)
    return out
