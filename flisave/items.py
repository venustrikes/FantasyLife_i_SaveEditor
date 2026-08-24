"""Parser/serialiser for the item-container block of the save payload.

The block is a run of arrays -- one per ``EInventoryCategory``, in enum order,
so the array index *is* the category and the record's handle is
``(category << 12) | slot``.  Each array is a ``uint32 count`` followed by
``count`` records, and every record is an ``FInventoryInfoCore`` with a
category-specific extension bolted on:

    uint32  tag        = 0x189C9D08
    uint16  handle     = (category << 12) | slot
    uint16  get_order  = (slot + 1) * 4
    FString item_id    ("None" for an empty slot)
    uint32  instance_id       running acquisition counter
    uint32  is_favorite       serialised as a 4-byte bool
    uint32  is_presented      serialised as a 4-byte bool
    FString aoc_id            ("None" unless the item came from add-on content)
    FString expired_item_id   ("None")
    bytes   ext        the extension, which differs per category

The extension is *not* the same shape in every bag, which is why it is carried
through verbatim and its layout learned from the array's own records rather
than assumed:

    stackable bags (consumables, materials, ...)   uint16 num
    equipment bags (weapons, tools, shields, ...)  two bytes, two arrays and a
                                                   fixed 10-13 byte tail
    kit bags                                       FName + 8 raw bytes

The equipment extension is where a piece of gear keeps everything that makes it
worth having: :attr:`~ItemRecord.item_title` (the tier its stats are read at),
:attr:`~ItemRecord.grant_skills`, :attr:`~ItemRecord.ripening_age` and
:attr:`~ItemRecord.quality`.  All four are laid out below and all four are
writable, which is what :meth:`ItemRecord.make_super_op` uses.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .stream import Reader, pack_fstring

TAG = 0x189C9D08
TAG_BYTES = struct.pack("<I", TAG)
EMPTY = "None"

# EInventoryCategory: the array index is the enum value, and the handle packs it
# into the top nibble.  Only the bags a player actually fills are named here;
# the rest are the support/instant-character mirrors of the same categories.
CATEGORY_NAMES = {
    0: "Consumables", 1: "Weapons", 2: "Life tools", 3: "Shields",
    4: "Armour", 5: "Craft", 6: "Kits", 7: "Materials", 8: "Recipes",
    9: "Key items", 10: "Mounts",
}
CATEGORY_SHIFT = 12

CONSUME, WEAPON, LIFE_TOOLS, SHIELD, ARMOR = 0, 1, 2, 3, 4
CRAFT, KIT, MATERIAL, RECIPE, IMPORTANT, VEHICLE = 5, 6, 7, 8, 9, 10

# Which bag an item id belongs in.  ``iam`` is the awkward one: shields have
# their own bag, so :func:`category_for` has to ask the gear database.
PREFIX_CATEGORY = {
    "ics": CONSUME, "iwp": WEAPON, "ilt": LIFE_TOOLS, "iam": ARMOR,
    "icf": CRAFT, "ico": CRAFT, "kit": KIT, "imt": MATERIAL, "irp": RECIPE,
    "iky": IMPORTANT, "ive": VEHICLE,
}

PREFIX_LABELS = {
    "ics": "Consumable", "iwp": "Weapon", "iam": "Armour", "imt": "Material",
    "ilt": "Life tool", "iky": "Key item", "ive": "Mount", "irp": "Recipe",
    "icf": "Craft item", "ico": "Craft item", "kit": "Kit",
    "ide": "Decoration", "iwe": "Weapon (alt)",
}

# EItemTitleType.  The title is not decoration: it picks which entry of the
# item's stat list the game reads, so gear written with a title the item has no
# entry for shows every stat as zero.
ITEM_TITLES = ["None", "Rag", "Normal", "Masterpiece", "Supreme", "Legend"]

# ``InventoryInfoEquip``, in the order its serialiser writes it.  The field
# names, widths and struct offsets are the executable's own: UE registers every
# reflected property with its name and offset, and the table for this struct
# reads itemTitle @0x24, quality @0x25, addEquipStatus @0x28, grantSkillId
# @0x30 (three of them), equipAbilityNum @0x48, equipViewNum @0x4A,
# licenseItemCraftLv @0x4C, isBurying @0x4D, ripeningAge @0x4E, creatorSignNo
# @0x50, ExEquipItemType @0x52.
#
#     uint8   item_title          EItemTitleType, picks the stat tier
#     uint8   quality             EItemQualityType, Quality_0..Quality_3
#     uint32  count + count x (uint8 kind + uint32 value)   add_equip_status
#     uint32  count + count x FString                grant_skill_id (3 slots)
#     uint16  equip_ability_num | uint16 equip_view_num
#     uint8   license_item_craft_lv    only on saves older than custom version 2
#     uint32  is_burying          a bool, serialised as four bytes
#     uint16  ripening_age        the Aging Altar's "<n>-year vintage"
#     uint16  creator_sign_no     custom version >= 6
#     uint8   ex_equip_item_type  custom version >= 7
#
# The two arrays vary in length and the last two fields are version-gated, so
# the tail is found by walking the arrays and then read forwards from there --
# never counted back from the end.
EQUIP_MIN_EXT = 26            # anything shorter cannot be an equipment record
STACK_EXT = 2                 # a stackable extension is just ``uint16 num``

# EItemQualityType.  Crafting writes 3; everything the game hands out is 0.
QUALITY_MAX = 3
GRANT_SKILL_SLOTS = 3         # ``grantSkillId`` is a fixed three-element array
NO_SKILL = "None"

# What the game itself puts on a fully aged piece: the reference screenshot's
# 1000-year vintage.  The field is a uint16, so higher fits, but 1000 is the
# number the Altar actually produces and the only one seen in a real save.
OP_RIPENING_AGE = 1000

# How many bytes follow the arrays, per build.  10 is the plain shape, 11 the
# pre-version-2 one that still carried ``licenseItemCraftLv``, 12 adds
# ``creatorSignNo`` and 13 ``ExEquipItemType``.
_TAIL_SIZES = (10, 11, 12, 13)
_TAIL_LEGACY = 11             # the only shape with license_item_craft_lv in it


def _skip_fstring(ext: bytes, i: int) -> int:
    """Past the FString at *i*, empty ones (a bare zero length) included."""
    if i + 4 > len(ext):
        raise ValueError("truncated FString at %d" % i)
    n = struct.unpack_from("<i", ext, i)[0]
    return i + 4 + (n if n > 0 else -2 * n)


def _read_fstring(ext: bytes, i: int):
    """``(text, next_offset)`` for the FString at *i*."""
    n = struct.unpack_from("<i", ext, i)[0]
    if n > 0:
        raw = ext[i + 4:i + 4 + n]
        return raw.split(b"\x00")[0].decode("utf-8", "replace"), i + 4 + n
    if n < 0:
        raw = ext[i + 4:i + 4 - 2 * n]
        return raw.decode("utf-16-le", "replace").split("\x00")[0], i + 4 - 2 * n
    return "", i + 4


ADD_STATUS_ENTRY = 5          # uint8 kind + uint32 value, no string in sight


def _equip_skills_offset(ext: bytes) -> Optional[int]:
    """Where ``grant_skill_id``'s count sits, or None if the shape is unknown."""
    try:
        count = struct.unpack_from("<I", ext, 2)[0]
    except struct.error:
        return None
    if count > 64:
        return None
    i = 6 + count * ADD_STATUS_ENTRY
    return i if 0 < i < len(ext) else None


def _equip_tail_offset(ext: bytes) -> Optional[int]:
    """Where the ``equip_ability_num`` block starts, or None if the shape is new."""
    i = _equip_skills_offset(ext)
    if i is None:
        return None
    try:
        count = struct.unpack_from("<I", ext, i)[0]
        i += 4
        for _ in range(count):
            i = _skip_fstring(ext, i)
    except (ValueError, struct.error):
        return None
    return i if len(ext) - i in _TAIL_SIZES else None


def _equip_field(ext: bytes, name: str):
    """``(offset, width)`` of one trailing field, or None when this build has none.

    Everything after the two arrays is fixed-width, so the whole tail follows
    from where the arrays end -- which is why the version-gated fields at the
    very end can be absent without moving anything in front of them.
    """
    tail = _equip_tail_offset(ext)
    if tail is None:
        return None
    rest = len(ext) - tail
    off = tail + 4                             # past ability_num + view_num
    if rest == _TAIL_LEGACY:
        off += 1                               # license_item_craft_lv sits here
    places = {
        "equip_ability_num": (tail, 2),
        "equip_view_num": (tail + 2, 2),
        "is_burying": (off, 4),
        "ripening_age": (off + 4, 2),
        "creator_sign_no": (off + 6, 2),
        "ex_equip_item_type": (off + 8, 1),
    }
    at = places.get(name)
    if at is None or at[0] + at[1] > len(ext):
        return None
    return at


def category_for(item_id: str) -> Optional[int]:
    """The bag the game files *item_id* under, or None if the prefix is new."""
    from . import gear
    if gear.is_shield(item_id):
        return SHIELD
    return PREFIX_CATEGORY.get(item_id[:3])


def _fstring_len(buf: bytes, i: int) -> Optional[int]:
    """Byte length of a plausible FString at *i*, else None."""
    if i + 4 > len(buf):
        return None
    n = struct.unpack_from("<i", buf, i)[0]
    if 2 <= n <= 128 and i + 4 + n <= len(buf):
        s = buf[i + 4:i + 4 + n]
        if s[-1] == 0 and all(0x20 <= c < 0x7F for c in s[:-1]):
            return 4 + n
    if -128 <= n <= -2 and i + 4 - 2 * n <= len(buf):
        s = buf[i + 4:i + 4 - 2 * n]
        if s[-2:] == b"\x00\x00":
            return 4 - 2 * n
    return None


def _make_template(ext: bytes):
    """Describe an extension as an alternating sequence of raw runs and FStrings."""
    tpl, i, raw_start = [], 0, 0
    while i < len(ext):
        n = _fstring_len(ext, i)
        if n is not None:
            if i > raw_start:
                tpl.append(("raw", i - raw_start))
            tpl.append(("str", 0))
            i += n
            raw_start = i
        else:
            i += 1
    if len(ext) > raw_start:
        tpl.append(("raw", len(ext) - raw_start))
    return tpl


def _ext_len(buf: bytes, pos: int, tpl) -> int:
    n = 0
    for kind, size in tpl:
        if kind == "raw":
            n += size
        else:
            k = _fstring_len(buf, pos + n)
            if k is None:
                raise ValueError("extension template broke at 0x%X" % (pos + n))
            n += k
    return n


@dataclass
class ItemRecord:
    offset: int
    handle: int
    sort: int                 # FInventoryInfoCore::getOrder
    item_id: str
    instance_id: int
    is_favorite: int
    is_presented: int
    aoc_id: str
    expired_item_id: str
    ext: bytes = b""          # the category extension, carried through verbatim
    array_index: int = 0      # which container this record lives in
    index: int = 0            # position of this record inside that container

    @property
    def container(self) -> int:
        """Container id the game stored in the handle (0 while the slot is free)."""
        return self.handle >> CATEGORY_SHIFT

    @property
    def slot(self) -> int:
        """Slot id the game stored in the handle (0 while the slot is free)."""
        return self.handle & 0x0FFF

    # ------------------------------------------------------- extension views
    @property
    def stackable(self) -> bool:
        """True when this bag counts its items rather than tracking instances."""
        return len(self.ext) == STACK_EXT

    @property
    def equipment(self) -> bool:
        return len(self.ext) >= EQUIP_MIN_EXT

    @property
    def quantity(self) -> int:
        """How many of the item this slot holds.

        Equipment has no count -- every piece is its own record -- so an
        occupied equipment slot answers 1 and ignores writes.
        """
        if self.stackable:
            return struct.unpack_from("<H", self.ext, 0)[0]
        return 0 if self.empty else 1

    @quantity.setter
    def quantity(self, value: int) -> None:
        if self.stackable:
            self.ext = struct.pack("<H", max(0, min(0xFFFF, int(value))))

    @property
    def item_title(self) -> int:
        """``EItemTitleType`` -- which entry of the item's stat list applies."""
        return self.ext[0] if self.equipment else 0

    @item_title.setter
    def item_title(self, value: int) -> None:
        if self.equipment:
            title = max(0, min(len(ITEM_TITLES) - 1, int(value)))
            self.ext = bytes((title,)) + self.ext[1:]

    @property
    def title_name(self) -> str:
        return ITEM_TITLES[self.item_title] if self.equipment else ""

    @property
    def quality(self) -> int:
        """``EItemQualityType`` -- 0 on anything the game hands out, 3 on crafts."""
        return self.ext[1] if self.equipment else 0

    @quality.setter
    def quality(self, value: int) -> None:
        if self.equipment:
            q = max(0, min(QUALITY_MAX, int(value)))
            self.ext = self.ext[:1] + bytes((q,)) + self.ext[2:]

    # -------------------------------------------------- fixed trailing fields
    def _tail_get(self, name: str) -> int:
        at = _equip_field(self.ext, name) if self.equipment else None
        if at is None:
            return 0
        off, width = at
        fmt = {1: "<B", 2: "<H", 4: "<I"}[width]
        return struct.unpack_from(fmt, self.ext, off)[0]

    def _tail_set(self, name: str, value: int) -> None:
        at = _equip_field(self.ext, name) if self.equipment else None
        if at is None:
            return
        off, width = at
        fmt = {1: "<B", 2: "<H", 4: "<I"}[width]
        ceiling = (1 << (8 * width)) - 1
        blob = bytearray(self.ext)
        struct.pack_into(fmt, blob, off, max(0, min(ceiling, int(value))))
        self.ext = bytes(blob)

    @property
    def equip_ability_num(self) -> int:
        """Ability slots on this piece.  The game writes 1 on everything it grants."""
        return self._tail_get("equip_ability_num")

    @equip_ability_num.setter
    def equip_ability_num(self, value: int) -> None:
        self._tail_set("equip_ability_num", value)

    @property
    def ripening_age(self) -> int:
        """Years at the Aging Altar -- the ``Aging: <n>-year vintage`` line.

        Zero on everything an editor spawns, because the field is inside the
        equipment extension and nothing used to write it.
        """
        return self._tail_get("ripening_age")

    @ripening_age.setter
    def ripening_age(self, value: int) -> None:
        self._tail_set("ripening_age", value)

    @property
    def is_burying(self) -> int:
        """Set while the piece is buried at the Aging Altar rather than in the bag."""
        return self._tail_get("is_burying")

    @is_burying.setter
    def is_burying(self, value: int) -> None:
        self._tail_set("is_burying", 1 if value else 0)

    @property
    def creator_sign_no(self) -> int:
        """Which maker's signature is stamped on a crafted piece."""
        return self._tail_get("creator_sign_no")

    # ------------------------------------------------------- granted skills
    @property
    def grant_skills(self) -> List[str]:
        """The three ``es_*`` equipment skills on this piece, ``"None"`` for empty."""
        # The tail has to walk before the count in front of it can be trusted:
        # on a shape this build does not know, that count is not a count.
        i = _equip_skills_offset(self.ext) if self.equipment else None
        if i is None or _equip_tail_offset(self.ext) is None:
            return []
        count = struct.unpack_from("<I", self.ext, i)[0]
        i += 4
        out = []
        for _ in range(count):
            text, i = _read_fstring(self.ext, i)
            out.append(text)
        return out

    @grant_skills.setter
    def grant_skills(self, values) -> None:
        i = _equip_skills_offset(self.ext) if self.equipment else None
        tail = _equip_tail_offset(self.ext) if self.equipment else None
        if i is None or tail is None:
            return
        slots = [str(v) if v else NO_SKILL for v in values][:GRANT_SKILL_SLOTS]
        slots += [NO_SKILL] * (GRANT_SKILL_SLOTS - len(slots))
        block = struct.pack("<I", len(slots))
        block += b"".join(pack_fstring(s) for s in slots)
        self.ext = self.ext[:i] + block + self.ext[tail:]

    # -------------------------------------------------------------- mutation
    def place(self, item_id: str, quantity: int, instance_id: int,
              title: Optional[int] = None, super_op: bool = False) -> None:
        """Occupy this slot the way the game does.

        For equipment that means a title the item actually has stats for.
        Writing a quantity into an equipment record instead is what leaves
        spawned gear reading zero attack in game: the first byte of the
        extension is the title, not a count, and the game reads the item's
        attack out of its data table at that grade.

        With *super_op* the piece is finished the way the Aging Altar finishes
        one -- see :meth:`make_super_op`.
        """
        self.item_id = item_id
        self.instance_id = instance_id
        self.aoc_id = self.expired_item_id = EMPTY
        self.is_favorite = self.is_presented = 0
        self.handle = ((self.array_index & 0xF) << CATEGORY_SHIFT) | (self.index & 0x0FFF)
        self.sort = ((self.index + 1) * 4) & 0xFFFF
        if self.equipment:
            from . import gear
            self.item_title = gear.best_title(item_id) if title is None else title
            if super_op:
                self.make_super_op(keep_title=title is not None)
        else:
            self.quantity = quantity

    def make_super_op(self, *, age: int = OP_RIPENING_AGE,
                      keep_title: bool = False) -> dict:
        """Finish this piece the way a fully aged one comes out of the Altar.

        Four things separate the gear in a "super OP" save from the gear an
        editor spawns, and all four live in this record:

        * ``item_title`` -- the tier the game reads the stats at.  A weapon or
          tool that only exists at Legend reads 0 at any other title.
        * ``ripening_age`` -- the Aging Altar's vintage, shown as
          *Aging: <n>-year vintage*.  Nothing wrote it before, so spawned gear
          was always a 0-year piece.
        * ``grant_skills`` -- the three ``es_*`` equipment skills the Altar
          rolls, taken here from the game's own best-roll table for the item.
        * ``quality`` -- ``EItemQualityType``, which tops out at 3.

        Returns what it set, so a caller can say so.  Does nothing to a
        stackable record: those have none of these fields.
        """
        if not self.equipment:
            return {}
        from . import gear
        if not keep_title:
            best = gear.best_title(self.item_id)
            if best:
                self.item_title = best
        skills = gear.op_skills(self.item_id)
        if skills:
            self.grant_skills = skills
        self.ripening_age = age
        self.quality = QUALITY_MAX
        self.is_burying = 0
        return {"title": self.item_title, "title_name": self.title_name,
                "ripening_age": self.ripening_age, "quality": self.quality,
                "skills": [s for s in self.grant_skills if s != NO_SKILL]}

    @property
    def empty(self) -> bool:
        return self.item_id in ("", EMPTY)

    @property
    def category(self) -> str:
        return PREFIX_LABELS.get(self.item_id[:3], "?")

    def pack(self) -> bytes:
        return b"".join((
            TAG_BYTES,
            struct.pack("<HH", self.handle, self.sort),
            pack_fstring(self.item_id),
            struct.pack("<III", self.instance_id, self.is_favorite, self.is_presented),
            pack_fstring(self.aoc_id),
            pack_fstring(self.expired_item_id),
            self.ext,
        ))

    def clear(self) -> None:
        """Reset the slot to the exact shape the game writes for a free slot."""
        self.handle = 0
        self.sort = 0
        self.item_id = EMPTY
        self.instance_id = 0
        self.is_favorite = self.is_presented = 0
        self.aoc_id = self.expired_item_id = EMPTY
        if self.stackable:
            self.quantity = 0
        elif self.equipment:
            self.item_title = 0
            self.quality = 0
            self.grant_skills = []
            self.equip_ability_num = 0
            self.ripening_age = 0
            self.is_burying = 0


@dataclass
class ItemArray:
    index: int
    offset: int
    records: List[ItemRecord] = field(default_factory=list)
    pre: bytes = b""      # opaque bytes sitting between the previous array and
                          # this array's count field, carried through verbatim

    @property
    def count(self) -> int:
        return len(self.records)

    @property
    def kinds(self) -> List[str]:
        seen = []
        for r in self.records:
            p = r.item_id[:3]
            if not r.empty and p not in seen:
                seen.append(p)
        return seen

    @property
    def label(self) -> str:
        name = CATEGORY_NAMES.get(self.index)
        if name:
            return name
        k = self.kinds
        if not k:
            return "container %d (empty)" % self.index
        return " / ".join(PREFIX_LABELS.get(p, p) for p in k[:3])

    @property
    def used(self) -> int:
        return sum(1 for r in self.records if not r.empty)

    def pack(self) -> bytes:
        head = self.pre + struct.pack("<I", len(self.records))
        return head + b"".join(r.pack() for r in self.records)


class ItemSection:
    """Every item container, plus the exact byte span it occupies."""

    def __init__(self, start: int, end: int, arrays: List[ItemArray]):
        self.start = start
        self.end = end
        self.arrays = arrays

    @classmethod
    def parse(cls, payload: bytes) -> "ItemSection":
        first = payload.find(TAG_BYTES)
        if first < 4:
            raise ValueError("no item container tag found in payload")
        start = first - 4
        r = Reader(payload, start)
        arrays: List[ItemArray] = []
        pending_gap = b""
        while r.pos + 8 <= len(payload):
            here = r.pos
            count = struct.unpack_from("<I", payload, r.pos)[0]
            if payload[r.pos + 4:r.pos + 8] != TAG_BYTES or not 0 < count <= 1_000_000:
                break
            r.pos += 4
            arr = ItemArray(index=len(arrays), offset=here, pre=pending_gap)
            pending_gap = b""
            tpl = None
            for i in range(count):
                rec_off = r.pos
                if payload[r.pos:r.pos + 4] != TAG_BYTES:
                    raise ValueError(
                        "array %d record %d: missing tag at 0x%X" % (arr.index, i, r.pos))
                r.pos += 4
                handle = r.u16()
                sort = r.u16()
                item_id = r.fstring()
                instance, favorite, presented = r.u32(), r.u32(), r.u32()
                aoc, expired = r.fstring(), r.fstring()
                if tpl is None:
                    tpl = cls._learn(payload, r.pos, count)
                try:
                    span = _ext_len(payload, r.pos, tpl)
                except ValueError:
                    # A bag can hold records of more than one shape (an empty kit
                    # slot spells its target "None", a filled one names an item),
                    # so re-learn from the record that did not fit and carry on.
                    tpl = cls._learn(payload, r.pos, count)
                    span = _ext_len(payload, r.pos, tpl)
                ext = r.bytes(span)
                arr.records.append(ItemRecord(
                    rec_off, handle, sort, item_id, instance, favorite, presented,
                    aoc, expired, ext, array_index=arr.index, index=i))
            arrays.append(arr)
            # Arrays are not always adjacent; skip to the next tag and keep the
            # bytes in between (including unrelated structs) verbatim.
            nxt = payload.find(TAG_BYTES, r.pos)
            if nxt < 4 or nxt - 4 < r.pos:
                break
            pending_gap = payload[r.pos:nxt - 4]
            r.pos = nxt - 4
        section = cls(start, r.pos, arrays)
        if section.pack() != payload[start:section.end]:
            raise ValueError("item section did not round-trip; layout mismatch")
        return section

    @staticmethod
    def _learn(payload: bytes, pos: int, count: int):
        """The extension template, read off the record starting at *pos*.

        A single-record array is the one case that cannot be measured: the bytes
        after it cannot be told apart from the gap that follows, so they travel
        with the gap instead.  Byte order, and so the round-trip, is unaffected.
        """
        if count <= 1:
            return []
        nxt = payload.find(TAG_BYTES, pos)
        if nxt < 0:
            raise ValueError("truncated item section")
        return _make_template(payload[pos:nxt])

    def pack(self) -> bytes:
        return b"".join(a.pack() for a in self.arrays)

    @property
    def records(self):
        for a in self.arrays:
            for r in a.records:
                yield r

    def next_instance_id(self) -> int:
        return max((r.instance_id for r in self.records), default=0) + 1

    def find(self, item_id: str) -> List[ItemRecord]:
        return [r for r in self.records if r.item_id == item_id]

    def first_empty(self, array_index: int) -> Optional[ItemRecord]:
        for r in self.arrays[array_index].records:
            if r.empty:
                return r
        return None

    def array_for_item(self, item_id: str) -> Optional[ItemArray]:
        """The container the game would put *item_id* in."""
        index = category_for(item_id)
        if index is not None and index < len(self.arrays):
            return self.arrays[index]
        return self.array_for_prefix(item_id[:3])

    def array_for_prefix(self, prefix: str) -> Optional[ItemArray]:
        """Fallback for an id whose prefix the category map does not know."""
        for a in self.arrays:
            if prefix in a.kinds:
                return a
        return None

    def summary(self) -> str:
        out = ["item section 0x%X..0x%X  (%d containers)"
               % (self.start, self.end, len(self.arrays))]
        for a in self.arrays:
            out.append("  [%2d] slots=%5d used=%4d  %s"
                       % (a.index, a.count, a.used, a.label))
        return "\n".join(out)
