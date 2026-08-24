#!/usr/bin/env python3
"""Build the icon set the GUI ships with.

    python tools/build_icons.py <pak-or-apk> [--oodle oo2core_8_win64.dll]

Pulls the game's own UI art out of the paks, decodes it (the Android build
stores everything as ASTC 4x4) and writes plain PNGs into ``data/icons/``:

    coin, star            the currency icons
    life01 .. life14      the fourteen Life emblems, ribbon cropped off
    item/<item id>        the items that really do have a 2D icon (key items,
                          a few pieces of armour) - ordinary items are drawn as
                          3D models in game and have no icon to take
    cat/<prefix>          a generated chip per item-id prefix, so every row in
                          the editor has something to show

Everything lands at two sizes (24 px for table rows, 48 px for the picker), so
the editor can hand the file straight to Tk without Pillow at runtime.

Build-time only, and needs two extra packages:  pip install Pillow texture2ddecoder
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flisave import texture
from flisave.pak import PakFile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (24, 48)

PAK_IN_OBB = "Game/Content/Paks/"

# Life emblems, in the order the save numbers the Lives (life0001 .. life0014).
LIFE_EMBLEMS = ["b01", "b02", "b03", "b04", "c01", "c02", "c03", "g01",
                "w01", "w02", "w03", "w04", "w05", "w06"]
LIFE_CROP = (0, 0, 1.0, 0.60)          # keep the shield, drop the ribbon

CURRENCY = {"coin": "tex_icon_moneytype_000100",
            "star": "tex_icon_moneytype_000800"}

ITEM_ID = re.compile(r"tex_icon_((?:ic[sf]|iwp|iam|imt|iky|ilt|ive|irp|ico)\d{6,})$")

# Item-id prefix -> (label, colour) for the generated category chips.
CATEGORIES = {
    "ics": ("CO", (86, 170, 106)),
    "iwp": ("WP", (196, 84, 84)),
    "iam": ("AR", (94, 128, 196)),
    "imt": ("MT", (168, 132, 84)),
    "ilt": ("FU", (150, 110, 168)),
    "iky": ("KY", (206, 168, 74)),
    "ive": ("MO", (86, 156, 168)),
    "irp": ("RE", (128, 128, 140)),
    "icf": ("CF", (176, 120, 96)),
    "ico": ("OB", (120, 140, 110)),
    "ide": ("DE", (168, 120, 150)),
    "?": ("--", (120, 120, 128)),
}


def open_paks(source: str):
    """Every pak in an APK, or the single pak given."""
    if not source.lower().endswith(".apk"):
        return [PakFile(open(source, "rb"))]
    apk = zipfile.ZipFile(source)
    obb = zipfile.ZipFile(apk.open("assets/main.obb.png"))
    paks = []
    for info in obb.infolist():
        if not info.filename.startswith(PAK_IN_OBB) or not info.filename.endswith(".pak"):
            continue
        print("  reading %s" % os.path.basename(info.filename))
        buf = io.BytesIO()
        with obb.open(info.filename) as fh:
            while True:
                chunk = fh.read(1 << 22)
                if not chunk:
                    break
                buf.write(chunk)
        buf.seek(0)
        paks.append(PakFile(buf, info.file_size))
    return paks


def find(paks, predicate):
    """First (pak, path-without-extension) whose path satisfies *predicate*."""
    for pak in paks:
        for name in pak.entries:
            if name.endswith(".uasset") and predicate(name):
                return pak, name[:-len(".uasset")]
    return None, None


def save_sized(img, stem: str, out_dir: str, index: dict, key: str) -> None:
    from PIL import Image
    for size in SIZES:
        thumb = img.copy()
        thumb.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(thumb, ((size - thumb.width) // 2, (size - thumb.height) // 2))
        d = os.path.join(out_dir, str(size), os.path.dirname(stem))
        os.makedirs(d, exist_ok=True)
        canvas.save(os.path.join(out_dir, str(size), stem + ".png"))
    index[key] = stem


def crop_fraction(img, box):
    l, t, r, b = box
    return img.crop((int(img.width * l), int(img.height * t),
                     int(img.width * r), int(img.height * b)))


def trim(img):
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def category_chip(label: str, colour, size: int = 96):
    """A rounded chip standing in for items the game has no 2D icon for."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, radius = size // 10, size // 4
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius,
                        fill=colour + (235,),
                        outline=tuple(max(0, c - 45) for c in colour) + (255,),
                        width=max(2, size // 24))
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(size * 0.42))
    except OSError:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), label, font=font)
    d.text(((size - (box[2] - box[0])) / 2 - box[0],
            (size - (box[3] - box[1])) / 2 - box[1]),
           label, font=font, fill=(255, 255, 255, 245))
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="the game APK, or one pakchunk*.pak")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "icons"))
    ap.add_argument("--oodle", help="path to oo2core_*_win64.dll")
    args = ap.parse_args()
    if args.oodle:
        os.environ["FLI_OODLE_DLL"] = args.oodle

    print("opening %s" % os.path.basename(args.source))
    paks = open_paks(args.source)
    print("  %d pak(s), %d entries" % (len(paks), sum(len(p.entries) for p in paks)))

    index = {"lives": {}, "items": {}, "currency": {}, "categories": {},
             "sizes": list(SIZES)}
    os.makedirs(args.out, exist_ok=True)

    # ---------------------------------------------------------- currency
    for key, leaf in CURRENCY.items():
        pak, base = find(paks, lambda n, leaf=leaf: n.endswith("/%s.uasset" % leaf))
        if base is None:
            print("  ! no %s" % leaf)
            continue
        save_sized(trim(texture.read(pak, base).to_image()), key,
                   args.out, index["currency"], key)
    print("  currency: %s" % ", ".join(sorted(index["currency"])))

    # ------------------------------------------------------------- lives
    # The emblems only ship inside the localised folders - each language bakes
    # its own ribbon text into the art.  The ribbon is cropped off here, so any
    # language does; English is simply the first one to try.
    for i, tag in enumerate(LIFE_EMBLEMS, start=1):
        pak, base = None, None
        for lang in ("/L10N/en/", "/L10N/"):
            pak, base = find(paks, lambda n, t=tag, l=lang: "/UI/Icon/Life/" in n
                             and l in n and ("life_%s_" % t) in n)
            if base is not None:
                break
        if base is None:
            print("  ! no emblem for life%04d (%s)" % (i, tag))
            continue
        img = trim(crop_fraction(texture.read(pak, base).to_image(), LIFE_CROP))
        save_sized(img, "life%02d" % i, args.out, index["lives"], "life%04d" % i)
    print("  lives: %d emblem(s)" % len(index["lives"]))

    # ------------------------------------------------------------- items
    seen = set()
    for pak in paks:
        for name in pak.entries:
            if not name.endswith(".uasset") or "/UI/Icon/Item" not in name:
                continue
            m = ITEM_ID.search(name[:-len(".uasset")])
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            try:
                img = trim(texture.read(pak, name[:-len(".uasset")]).to_image())
            except Exception as exc:
                print("  ! %s (%s)" % (m.group(1), exc))
                continue
            save_sized(img, "item/%s" % m.group(1), args.out,
                       index["items"], m.group(1))
    print("  items: %d icon(s)" % len(index["items"]))

    # -------------------------------------------------------- categories
    for prefix, (label, colour) in CATEGORIES.items():
        stem = "cat/%s" % ("other" if prefix == "?" else prefix)
        save_sized(category_chip(label, colour), stem,
                   args.out, index["categories"], prefix)
    print("  categories: %d chip(s)" % len(index["categories"]))

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, sort_keys=True)

    total = sum(len(files) for _r, _d, files in os.walk(args.out))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _d, files in os.walk(args.out) for f in files)
    print("\nwrote %d file(s), %.0f KB, into %s" % (total, size / 1024, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
