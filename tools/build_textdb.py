#!/usr/bin/env python3
"""Build the item/Life name database the editor ships with.

    python tools/build_textdb.py <pak-or-apk> [-o data/fli_text.json.gz]

Accepts either a loose ``pakchunk0-*.pak`` or the Android APK (the pak is read
straight out of the nested zips, no extraction needed).

Needs an Oodle decompressor: set ``FLI_OODLE_DLL`` to an ``oo2core_*_win64.dll``
or drop one in the project root. Any UE4/UE5 game install ships one.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flisave.pak import PakFile
from flisave.gamedata import GameText, LANGUAGES

PAK_IN_OBB = "Game/Content/Paks/pakchunk0-Android_ASTC.pak"


def open_pak(path: str) -> PakFile:
    if path.lower().endswith(".apk"):
        apk = zipfile.ZipFile(path)
        obb = zipfile.ZipFile(apk.open("assets/main.obb.png"))
        info = obb.getinfo(PAK_IN_OBB)
        print("reading %s from %s" % (PAK_IN_OBB, os.path.basename(path)))
        # Random access through two nested zips is slow; buffer it once.
        buf = io.BytesIO()
        with obb.open(PAK_IN_OBB) as fh:
            while True:
                chunk = fh.read(1 << 22)
                if not chunk:
                    break
                buf.write(chunk)
        buf.seek(0)
        return PakFile(buf, info.file_size)
    return PakFile(open(path, "rb"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="pakchunk0-*.pak, or the game APK")
    ap.add_argument("-o", "--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "fli_text.json.gz"))
    ap.add_argument("--oodle", help="path to oo2core_*_win64.dll")
    args = ap.parse_args()

    if args.oodle:
        os.environ["FLI_OODLE_DLL"] = args.oodle

    pak = open_pak(args.source)
    print("pak: %d entries, compression %s" % (len(pak.entries), pak.compression_methods))

    problems = []
    text = GameText(pak, on_error=lambda t, e: problems.append((t, str(e))))
    for t, e in problems:
        print("  skipped %s (%s)" % (t.split("/")[-1], e))

    payload = text.to_json()
    payload["source"] = os.path.basename(args.source)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(args.out, "wb", compresslevel=9) as fh:
        fh.write(raw)

    print()
    for lang in LANGUAGES:
        print("  %-8s %5d names  %5d descriptions"
              % (lang, len(payload["names"][lang]), len(payload["descriptions"][lang])))
    print()
    print("wrote %s (%.1f KB gzipped, %.1f KB raw)"
          % (args.out, os.path.getsize(args.out) / 1024, len(raw) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
