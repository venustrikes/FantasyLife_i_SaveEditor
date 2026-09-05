"""Equipment stats, aging rolls and the shield/armour split, from the cooked tables.

Equipment in this game has no single attack number.  Each ``GDSItemWeaponData``
row carries a ``physicalOffenseList`` and a ``magicOffenseList`` -- five values,
one per ``EItemTitleType`` (Rag, Normal, Masterpiece, Supreme, Legend) -- and
the item record in the save stores only the *title*.  The game looks the numbers
up from it, so a weapon spawned with a title the item has no entry for reads as
0 in game.  ``1`` is the table's "not available at this grade" filler.

Life tools work the same way out of ``GDSItemLifeToolsData``, with one list
instead of two, so they need the same treatment and get it here.

Armour is the same shape (``physicalDefenseList``), but its ids appear in so
many other rows that the anchors below cannot pin an armour row reliably, so
only weapons and tools get stats here.  What armour does need is the bag it
belongs in: ``iam`` splits across ``SHIELD`` and ``ARMOR``, and a shield is an
item whose row points at a ``mdl_sld*`` model.

The third thing here is the Aging Altar's skill rolls.  ``GDSAddSkillLotTable``
holds one lot table per kind of gear per grade; the top one for each kind is
what a fully aged piece rolls from, and that is what ``ripening_skills`` reads.

The tables are cooked UObjects with unversioned properties, so nothing in them
is self-describing and rows have to be found by shape:

* the item id appears as an FName, with the row's ``mdl_*`` model reference
  within ~100 bytes -- both must be present before a row is accepted;
* the two stat lists sit together as a pair of five-element arrays.

Build-time only; the editor reads :mod:`flisave.gear`.
"""
from __future__ import annotations

import bisect
import collections
import re
import struct
from typing import Dict, List, Optional, Sequence, Tuple

from .uasset import UAsset

GD = "Game/Content/GameData/"
WEAPON_TABLE = GD + "Item/GDSItemWeaponData"
TOOL_TABLE = GD + "Item/GDSItemLifeToolsData"
ARMOR_TABLE = GD + "Item/GDSItemArmorData"
MATERIAL_TABLE = GD + "Item/GDSItemMaterialData"
RECIPE_TABLE = GD + "Item/GDSItemRecipeData"
SKILL_LOT_TABLE = GD + "Item/GDSAddSkillLotTable"

# Every material and every recipe the game defines, for the bulk fills.  The
# name database cannot supply these: it is keyed by things that have a name, and
# recipes have none.  Ids that are all digits are the blank placeholder rows the
# tables carry (``irp00000000`` and friends), so they are left out.
MATERIAL_ID = re.compile(r"^imt\d{6,}$")
RECIPE_ID = re.compile(r"^irp_\w+$")

# EItemTitleType.  0 is "no title" and has no entry in the stat lists; the game
# hands out untitled gear whose five entries are all the same, so it never has
# to choose.
TITLES = ["None", "Rag", "Normal", "Masterpiece", "Supreme", "Legend"]
TITLE_COUNT = len(TITLES) - 1
SENTINEL = 1                    # "this item does not exist at this grade"

MODEL_WINDOW = (40, 110)        # where a row's mdl_ reference sits, from the id
LIST_WINDOW = 160               # how far past the id the stat lists can start
STAT_CEILING = 100_000          # anything larger is a price, not a stat

SHIELD_MODEL = "mdl_sld"
# One shield model is shared by so many rows that "nearest id before it" picks
# the wrong owner; it never adds a shield the other two signals miss.
NOISY_MODEL = "mdl_sld000c00_00"
# The offsets at which a genuine model reference follows its own id.
SHIELD_OFFSETS = range(72, 79)


class _Asset:
    """A cooked GameData asset, with its name map and FName lookups."""

    def __init__(self, uasset: bytes, uexp: bytes, prefix: str):
        self.names: List[str] = UAsset(uasset).names
        self.uexp = uexp
        self.index = {n: i for i, n in enumerate(self.names)}
        self.item_re = re.compile(r"^%s\d{6,}$" % prefix)

    def fname_at(self, p: int) -> Optional[str]:
        if p < 0 or p + 8 > len(self.uexp):
            return None
        value, number = struct.unpack_from("<II", self.uexp, p)
        if number or value >= len(self.names):
            return None
        return self.names[value]

    def occurrences(self, name: str) -> List[int]:
        i = self.index.get(name)
        if i is None:
            return []
        needle = struct.pack("<II", i, 0)
        out, p = [], self.uexp.find(needle)
        while p >= 0:
            out.append(p)
            p = self.uexp.find(needle, p + 1)
        return out

    def item_ids(self) -> List[str]:
        return sorted(n for n in self.names if self.item_re.match(n))

    def model_near(self, p: int) -> Optional[int]:
        for off in range(*MODEL_WINDOW):
            name = self.fname_at(p + off)
            if name and name.startswith("mdl_"):
                return off
        return None


def _stat_lists(asset: _Asset, p: int) -> Optional[Tuple[List[int], List[int]]]:
    """The physical/magic pair: two five-element arrays back to back."""
    span = TITLE_COUNT * 4 + 4
    end = min(p + LIST_WINDOW, len(asset.uexp) - 2 * span)
    for q in range(p + 8, end):
        if (struct.unpack_from("<I", asset.uexp, q)[0] != TITLE_COUNT
                or struct.unpack_from("<I", asset.uexp, q + span)[0] != TITLE_COUNT):
            continue
        phys = list(struct.unpack_from("<%di" % TITLE_COUNT, asset.uexp, q + 4))
        mag = list(struct.unpack_from("<%di" % TITLE_COUNT, asset.uexp, q + span + 4))
        if any(v < 0 or v > STAT_CEILING for v in phys + mag):
            continue
        return phys, mag
    return None


def weapon_stats(pak) -> Dict[str, Dict[str, List[int]]]:
    """``{item_id: {"phys": [...5], "mag": [...5]}}`` for every weapon."""
    asset = _Asset(pak.read(WEAPON_TABLE + ".uasset"),
                   pak.read(WEAPON_TABLE + ".uexp"), "iwp")
    out: Dict[str, Dict[str, List[int]]] = {}
    for item in asset.item_ids():
        for p in asset.occurrences(item):
            if asset.model_near(p) is None:
                continue
            lists = _stat_lists(asset, p)
            if lists:
                out[item] = {"phys": lists[0], "mag": lists[1]}
                break
    return out


def _power_list(asset: _Asset, p: int) -> Optional[List[int]]:
    """The one five-element list a Life tool keeps its power in.

    Tools have no magic counterpart, so the pair test the weapons use does not
    apply: the first five-element list after the row's id is the power, and the
    price list that follows further down is well outside the window.
    """
    span = TITLE_COUNT * 4 + 4
    end = min(p + LIST_WINDOW, len(asset.uexp) - span)
    for q in range(p + 8, end):
        if struct.unpack_from("<I", asset.uexp, q)[0] != TITLE_COUNT:
            continue
        values = list(struct.unpack_from("<%di" % TITLE_COUNT, asset.uexp, q + 4))
        if any(v < 0 or v > STAT_CEILING for v in values):
            continue
        return values
    return None


def tool_power(pak) -> Dict[str, Dict[str, List[int]]]:
    """``{item_id: {"phys": [...5], "mag": []}}`` for every Life tool.

    Life tools are graded exactly like weapons -- five values, one per
    ``EItemTitleType``, with ``1`` for "not available at this grade" -- so a
    True Axe of Time spawned at anything but Legend reads 0 in game just as a
    True Sword of Time does.  They live in their own table, which is why they
    were missing from the database and why nothing could pick a grade for them.
    """
    asset = _Asset(pak.read(TOOL_TABLE + ".uasset"),
                   pak.read(TOOL_TABLE + ".uexp"), "ilt")
    out: Dict[str, Dict[str, List[int]]] = {}
    for item in asset.item_ids():
        for p in asset.occurrences(item):
            if asset.model_near(p) is None:
                continue
            values = _power_list(asset, p)
            if values:
                out[item] = {"phys": values, "mag": []}
                break
    return out


# The Aging Altar's best roll for each kind of gear.  ``high_high`` is the top
# of the two-axis grid the lot tables are laid out on, and its entries are the
# top variant of each skill family (``es_felling_up05`` and friends).
RIPENING_PREFIX = "addSkillTbl_ripening_high_high_"
POOL_PREFIX = "addSkillTbl_"
POOL_NAME = re.compile(r"^addSkillTbl_(?!ripening_)(.+)_\d+$")
SKILL_ID = re.compile(r"^es_\w+$")
OP_SKILL_SLOTS = 3
_FAMILY_TAIL = re.compile(r"_?\d+$")


def _lot_tables(pak) -> Dict[str, List[str]]:
    """``{lot table name: [skill id, ...]}``, in the order the table lists them."""
    asset = _Asset(pak.read(SKILL_LOT_TABLE + ".uasset"),
                   pak.read(SKILL_LOT_TABLE + ".uexp"), "es")
    starts: List[Tuple[int, str]] = []
    for name in asset.names:
        if not name.startswith("addSkill"):
            continue
        here = asset.occurrences(name)
        if here:
            starts.append((min(here), name))
    starts.sort()
    out: Dict[str, List[str]] = {}
    for k, (p, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(asset.uexp)
        skills: List[str] = []
        for q in range(p, end):
            got = asset.fname_at(q)
            if got and SKILL_ID.match(got) and got not in skills:
                skills.append(got)
        out[name] = skills
    return out


def _item_pools(pak, table: str, prefix: str) -> Dict[str, str]:
    """``{item_id: pool token}`` -- which ``addSkillTbl_<token>_NN`` a row names.

    The token is the game's own word for the kind of gear a row is (``ax``,
    ``pickaxe``, ``sword``), which is what the ripening categories are keyed by.
    """
    asset = _Asset(pak.read(table + ".uasset"), pak.read(table + ".uexp"), prefix)
    anchors: List[Tuple[int, str]] = []
    for item in asset.item_ids():
        anchors.extend((p, item) for p in asset.occurrences(item))
    anchors.sort()
    seen: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for k, (p, item) in enumerate(anchors):
        end = anchors[k + 1][0] if k + 1 < len(anchors) else len(asset.uexp)
        for q in range(p, end):
            got = asset.fname_at(q)
            if not got:
                continue
            hit = POOL_NAME.match(got)
            if hit:
                seen[item][hit.group(1)] += 1
    return {item: c.most_common(1)[0][0] for item, c in seen.items() if c}


def _family(skill: str) -> str:
    return _FAMILY_TAIL.sub("", skill)


def _token_categories(lots: Dict[str, List[str]], tokens,
                      fuzzy: bool = True) -> Dict[str, str]:
    """Match each gear token to a ripening category.

    Most tokens *are* the category under a different spelling (``staff`` for
    ``Staff``); the tool ones are not (``ax`` is ``felling``, ``pickaxe`` is
    ``mining``), so with *fuzzy* those fall back to comparing skill families --
    an axe's own pool and the felling ripening pool share ``es_felling_*``,
    ``es_spot_attack_*`` and the rest, and nothing else comes close.

    Without *fuzzy* only the exact name counts, which is what armour needs: the
    Altar has no category for body armour, so the nearest match is always the
    wrong answer rather than a near miss.
    """
    cats = {name[len(RIPENING_PREFIX):]: skills
            for name, skills in lots.items() if name.startswith(RIPENING_PREFIX)}
    by_lower = {c.lower(): c for c in cats}
    families = {c: {_family(s) for s in skills} for c, skills in cats.items()}
    out: Dict[str, str] = {}
    for token in tokens:
        if token.lower() in by_lower:
            out[token] = by_lower[token.lower()]
            continue
        if not fuzzy:
            continue
        pool: set = set()
        for suffix in ("_02", "_01"):
            pool |= {_family(s) for s in lots.get(POOL_PREFIX + token + suffix, [])}
        if not pool:
            continue
        best = max(cats, key=lambda c: len(pool & families[c]))
        if pool & families[best]:
            out[token] = best
    return out


WEAPON_ID = re.compile(r"^iwp\d{6,}$")
TOOL_ID = re.compile(r"^ilt\d{6,}$")
# Item ids are prefix + two digits of gear family + a serial, and the family is
# exactly what a ripening category keys on: every ``iwp05`` is a bow, every
# ``ilt01`` an axe.  A row whose own pool reference the scan could not pin down
# therefore inherits from the rest of its family rather than going without.
FAMILY_KEY = 5


def _fill_families(out: Dict[str, List[str]], ids: Sequence[str]) -> None:
    votes: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for item, picks in out.items():
        votes[item[:FAMILY_KEY]][tuple(picks)] += 1
    for item in ids:
        if item in out:
            continue
        family = votes.get(item[:FAMILY_KEY])
        if family:
            out[item] = list(family.most_common(1)[0][0])


def ripening_skills(pak, shields: Optional[Sequence[str]] = None) -> Dict[str, List[str]]:
    """``{item_id: [skill, skill, skill]}`` -- the Altar's best roll per item.

    A piece of gear that has been aged carries three ``es_*`` equipment skills
    in its save record.  Which three it can get is decided by the kind of gear
    it is, and the game keeps one lot table per kind and grade; the top table
    for each kind leads with that kind's headline skill, so its first three
    entries are the best roll the game itself would produce.

    The sixteen categories cover weapons, Life tools and shields.  There is
    none for body armour -- so armour gets nothing here rather than a guess.
    """
    lots = _lot_tables(pak)
    out: Dict[str, List[str]] = {}

    def collect(pools: Dict[str, str], fuzzy: bool) -> None:
        cats = _token_categories(lots, sorted(set(pools.values())), fuzzy)
        for item, token in pools.items():
            picks = lots.get(RIPENING_PREFIX + cats.get(token, ""), [])
            if picks:
                out[item] = picks[:OP_SKILL_SLOTS]

    for table, prefix, pattern in ((WEAPON_TABLE, "iwp", WEAPON_ID),
                                   (TOOL_TABLE, "ilt", TOOL_ID)):
        collect(_item_pools(pak, table, prefix), fuzzy=True)
        _fill_families(out, table_ids(pak, table, pattern))
    collect(_item_pools(pak, ARMOR_TABLE, "iam"), fuzzy=False)
    # Armour cannot be filled by family -- a family there mixes shields with
    # hats -- so the shield list, which is derived separately, does it instead.
    picks = lots.get(RIPENING_PREFIX + "shield", [])[:OP_SKILL_SLOTS]
    for item in shields or ():
        if picks:
            out.setdefault(item, picks)
    return out


def shield_ids(pak, name_db=None) -> List[str]:
    """Which ``iam`` items the game files under SHIELD rather than ARMOR.

    Three independent signals, unioned: the model reference sitting at its own
    row's offset (precise but incomplete), the model found by the same row scan
    the weapon stats use, and -- when a name database is supplied -- the word
    for "shield" in any of the Latin-script languages.  Each covers a few the
    others miss and none of them contributes a false positive on its own.
    """
    asset = _Asset(pak.read(ARMOR_TABLE + ".uasset"),
                   pak.read(ARMOR_TABLE + ".uexp"), "iam")
    items = asset.item_ids()

    anchors: List[Tuple[int, str]] = []
    for item in items:
        anchors.extend((p, item) for p in asset.occurrences(item))
    anchors.sort()
    positions = [a[0] for a in anchors]

    found = set()
    for model in (n for n in asset.names if n.startswith(SHIELD_MODEL)):
        for p in asset.occurrences(model):
            k = bisect.bisect_right(positions, p) - 1
            if k >= 0 and (p - positions[k]) in SHIELD_OFFSETS:
                found.add(anchors[k][1])

    for item in items:
        for p in asset.occurrences(item):
            off = asset.model_near(p)
            if off is None:
                continue
            model = asset.fname_at(p + off)
            if model.startswith(SHIELD_MODEL) and model != NOISY_MODEL:
                found.add(item)
            break

    if name_db is not None:
        word = re.compile(r"\b(scudo|shield|bouclier|schild|escudo)\b", re.I)
        for item in items:
            for lang in ("it", "en", "fr", "de", "es"):
                text = name_db.resolve(item, lang)
                if text and word.search(text):
                    found.add(item)
                    break
    return sorted(found)


def table_ids(pak, base: str, pattern) -> List[str]:
    """Every name in a cooked table that looks like an item id."""
    names = UAsset(pak.read(base + ".uasset")).names
    return sorted(n for n in names if pattern.match(n))


def build(pak, name_db=None) -> dict:
    stats = weapon_stats(pak)
    tools = tool_power(pak)
    stats.update(tools)
    shields = shield_ids(pak, name_db)
    return {
        "titles": TITLES,
        "sentinel": SENTINEL,
        "weapons": stats,
        "tools": sorted(tools),
        "ripening_skills": ripening_skills(pak, shields),
        "shields": shields,
        "materials": table_ids(pak, MATERIAL_TABLE, MATERIAL_ID),
        "recipes": table_ids(pak, RECIPE_TABLE, RECIPE_ID),
    }
