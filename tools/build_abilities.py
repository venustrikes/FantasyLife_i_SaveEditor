#!/usr/bin/env python3
"""Build the equipment-ability catalogue the editor ships with.

    python tools/build_abilities.py <save>... [-o data/fli_abilities.json.gz]

Unlike the other two databases this one is not built from the pak.  The PC
release ships an encrypted pak index and the ability table is not in the
executable either, so the ids are gathered from the three places they can still
be read, and each entry records which:

* ``save``  -- the ``grantSkillId`` slots of real equipment records, which is
  the game writing an ability id itself.  Only these carry a bag count.
* ``altar`` -- the Aging Altar lot tables already extracted into
  ``data/fli_gear.json.gz``, so an ability the Altar can roll is offered even
  where no save here has been aged.
* ``text``  -- an ``es_*`` key the game's own text tables name.  Those are the
  game's words for an ability, so the ability exists; nothing here has seen one
  on a piece, which is what the field says.

Feed it as many saves from as many builds as you have: that is the only input
that grows the first two tiers.

Only ids are read.  Nothing that identifies a save or its player is written
out, and the saves themselves are never modified.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flisave import gear as geardb                          # noqa: E402
from flisave import names as namedb                         # noqa: E402
from flisave.items import (ARMOR, LIFE_TOOLS, NO_SKILL,      # noqa: E402
                           SHIELD, VEHICLE, WEAPON)
from flisave.save import SaveFile                           # noqa: E402

#: which bag an ability was seen on, by inventory category.  Mounts take the
#: same extension shape as gear, so they are read too rather than skipped.
BAGS = {WEAPON: "weapon", LIFE_TOOLS: "tool", SHIELD: "shield",
        ARMOR: "armour", VEHICLE: "mount"}

#: an id ends in its level -- ``es_attack_up06`` is the sixth Attack + -- with
#: or without the underscore in front of it.  Ids with no number at all are
#: their own family at level 0 (``es_attribute_change_fire``).
LEVEL = re.compile(r"_?(\d+)$")

#: How the text database keys an ability, in the order worth trying: the id
#: itself, then the family, then the family's first level either way round.
#: Which one hits varies by family and there is no rule to it.
TEXT_KEYS = ("%(id)s", "%(family)s", "%(family)s01", "%(family)s_01")

# Fourteen families the shipped text tables have no entry for at all -- not the
# id, not the family, not the first level.  They are real abilities that real
# saves carry, so leaving them nameless would leave a quarter of the Life-tool
# ones showing as raw ids; these are the editor's own words for them, read off
# the id and the company an ability keeps, and they are marked as such in the
# file so the editors can say so rather than pass them off as the game's.
GLOSS = {
    "es_category_match_damage_deposit": "Damage to ore",
    "es_category_match_damage_fish": "Damage to fish",
    "es_category_match_damage_tree": "Damage to trees",
    "es_collect_up_add": "Gathering + (flat)",
    "es_craft_tension_up": "Crafting focus +",
    "es_craft_time_extension": "Crafting time +",
    "es_critical_evasion_up": "Critical evasion +",
    "es_gain_all_exp_up": "All EXP +",
    "es_production_up_add": "Production + (flat)",
    "es_recipe_up_alchemy": "Alchemy recipe quality +",
    "es_recipe_up_blacksmith": "Smithing recipe quality +",
    "es_recipe_up_carpenter": "Carpentry recipe quality +",
    "es_recipe_up_cook": "Cooking recipe quality +",
    "es_recipe_up_sewing": "Tailoring recipe quality +",
}


def split(ability: str):
    """``(family, level)``.  Level 0 means the id carries no number."""
    m = LEVEL.search(ability)
    return (ability[:m.start()], int(m.group(1))) if m else (ability, 0)


def text_key(ability: str, family: str, table) -> str:
    """The key the text database names this ability under, or ``""``."""
    for shape in TEXT_KEYS:
        key = shape % {"id": ability, "family": family}
        if key in table:
            return key
    return ""


def harvest(paths):
    """``{ability: {bag: count}}`` over every equipment record in *paths*."""
    seen = collections.defaultdict(collections.Counter)
    builds = set()
    for path in paths:
        sf = SaveFile.load(path, verify=False)
        builds.add(sf.header.build_id)
        for arr in sf.items.arrays:
            bag = BAGS.get(arr.index)
            if bag is None:
                continue
            for rec in arr.records:
                if rec.empty or not rec.equipment:
                    continue
                for ability in rec.grant_skills:
                    if ability != NO_SKILL:
                        seen[ability][bag] += 1
    return seen, sorted(builds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("saves", nargs="+", help="save files to read ability ids from")
    ap.add_argument("-o", "--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "fli_abilities.json.gz"))
    args = ap.parse_args()

    seen, builds = harvest(args.saves)
    print("read %d save(s) from %d build(s): %d ability id(s) in the records"
          % (len(args.saves), len(builds), len(seen)))

    # The Altar's own lot tables are the other proven source, and the only one
    # for an ability no save here happens to carry.
    rolls = geardb.get().ripening
    for picks in rolls.values():
        for ability in picks:
            seen.setdefault(ability, collections.Counter())
    print("  plus the Aging Altar rolls: %d id(s) in all" % len(seen))

    table = namedb.get().names.get(namedb.FALLBACK) or {}
    out = {}

    def add(ability: str, origin: str, bags=None) -> None:
        family, level = split(ability)
        entry = {"family": family, "level": level, "from": origin}
        if bags:
            entry["bags"] = dict(sorted(bags.items()))
        key = text_key(ability, family, table)
        if key:
            entry["text"] = key
        elif family in GLOSS:
            entry["gloss"] = GLOSS[family]
        out[ability] = entry

    for ability, bags in seen.items():
        add(ability, "save" if bags else "altar", bags)

    # Everything the text tables name and no save here has carried.  A key that
    # ends in ``_value`` is the "+3 Fire Resistance" line under an ability, not
    # an ability, so it is not one of these.
    for key in sorted(table):
        if (key.startswith("es_") and not key.endswith("_value")
                and key not in out):
            add(key, "text")

    named = sum(1 for e in out.values() if "text" in e)
    glossed = sum(1 for e in out.values() if "gloss" in e)
    origins = collections.Counter(e["from"] for e in out.values())
    payload = {
        "abilities": dict(sorted(out.items())),
        "builds": builds,
        "saves": len(args.saves),
        "source": "equipment records, Aging Altar rolls, text tables",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with gzip.open(args.out, "wb", compresslevel=9) as fh:
        fh.write(raw.encode("utf-8"))

    bags = collections.Counter(b for e in out.values() for b in e.get("bags", ()))
    print("  %d ability id(s): %s"
          % (len(out), ", ".join("%s %d" % kv for kv in sorted(origins.items()))))
    print("  named by the text tables : %d" % named)
    print("  glossed by the editor    : %d" % glossed)
    print("  neither                  : %d" % (len(out) - named - glossed))
    print("  seen on gear             : %s"
          % ", ".join("%s %d" % kv for kv in sorted(bags.items())))
    print("wrote %s (%.1f KB)" % (args.out, os.path.getsize(args.out) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
