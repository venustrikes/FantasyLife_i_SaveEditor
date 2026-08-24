#!/usr/bin/env python3
"""Build the equipment database the editor ships with.

    python tools/build_geardb.py <pak-or-apk> [-o data/fli_gear.json.gz]

Holds what the save format alone cannot tell you: the per-title stat lists a
weapon's attack is looked up in, which ``iam`` items are shields (they live in a
different bag from the rest of the armour), and every material and recipe id,
for the bulk fills.

Same inputs as ``build_textdb.py``: a loose ``pakchunk0-*.pak`` or the Android
APK, plus an Oodle decompressor in ``FLI_OODLE_DLL``.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flisave import geardata, names as _names

from build_textdb import open_pak            # noqa: E402  (same directory)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="pakchunk0-*.pak, or the game APK")
    ap.add_argument("-o", "--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "fli_gear.json.gz"))
    ap.add_argument("--oodle", help="path to oo2core_*_win64.dll")
    args = ap.parse_args()

    if args.oodle:
        os.environ["FLI_OODLE_DLL"] = args.oodle

    pak = open_pak(args.source)
    print("pak: %d entries" % len(pak.entries))

    db = _names.get()
    payload = geardata.build(pak, db if db.loaded else None)
    payload["source"] = os.path.basename(args.source)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(args.out, "wb", compresslevel=9) as fh:
        fh.write(raw)

    weapons = payload["weapons"]
    tools = set(payload["tools"])
    flat = sum(1 for v in weapons.values() if len(set(v["phys"])) == 1)
    print("  weapons  : %d with stat lists (%d flat across every title)"
          % (len(weapons) - len(tools), flat))
    print("  tools    : %d Life tools with power lists" % len(tools))
    print("  op skills: %d items with an Aging Altar best roll"
          % len(payload["op_skills"]))
    print("  shields  : %d ids" % len(payload["shields"]))
    print("  materials: %d ids" % len(payload["materials"]))
    print("  recipes  : %d ids" % len(payload["recipes"]))
    print("wrote %s (%.1f KB gzipped, %.1f KB raw)"
          % (args.out, os.path.getsize(args.out) / 1024, len(raw) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
