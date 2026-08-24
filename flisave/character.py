"""The character block: name, vitals, and the Life the player is living.

Everything in the payload shifts when items are added or the name changes, so
the block is found by its shape rather than by an offset.  What it looks like:

    float32   1.0
    uint32    HP
    uint32    HP max
    uint32    SP
    uint32    SP max
    uint32    ?
    uint32    ?
    FString   character name      "Angel"
    FString   current life id     "life0001"

The anchor is that pair of FStrings: a printable name immediately followed by a
``lifeXXXX`` id.  Inside the per-Life arrays a ``lifeXXXX`` id is preceded by
another ``lifeXXXX`` id or by an array count, never by a name, which is what
keeps this from matching there.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import List, Optional

LIFE_ID = re.compile(rb"\x09\x00\x00\x00(life\d{4})\x00")
NAME_MAX = 64                 # longest character name worth believing
VITALS_BACK = 0x18            # HP sits this far in front of the name FString

FIELDS = ("hp", "hp_max", "sp", "sp_max")


@dataclass
class Character:
    """Where the character block is, and what it currently says."""

    name: str
    name_offset: int          # start of the name's FString length field
    name_bytes: int           # how many bytes that FString occupies
    life_id: str
    life_offset: int
    vitals_offset: int        # first of the four uint32s
    hp: int
    hp_max: int
    sp: int
    sp_max: int

    def vital_offset(self, field: str) -> int:
        return self.vitals_offset + 4 * FIELDS.index(field)


def _fstring_at(payload: bytes, pos: int) -> Optional[str]:
    """Read a plain ASCII FString at *pos*, or None if that is not one."""
    if pos < 0 or pos + 4 > len(payload):
        return None
    n = struct.unpack_from("<i", payload, pos)[0]
    if not 2 <= n <= NAME_MAX or pos + 4 + n > len(payload):
        return None
    raw = payload[pos + 4:pos + 4 + n]
    if raw[-1] != 0 or not all(0x20 <= c < 0x7F for c in raw[:-1]):
        return None
    return raw[:-1].decode("ascii")


def find(payload: bytes) -> Optional[Character]:
    """Locate the character block, or None if this save has none."""
    for m in LIFE_ID.finditer(payload):
        head = m.start()
        for back in range(6, NAME_MAX + 8):
            start = head - back
            name = _fstring_at(payload, start)
            if name is None or start + 4 + (back - 4) != head:
                continue
            if re.fullmatch(r"life\d{4}", name):
                break                     # a Life array, not the character
            vitals = start - VITALS_BACK
            if vitals < 0:
                break
            hp, hp_max, sp, sp_max = struct.unpack_from("<4I", payload, vitals)
            # Sanity only, no ordering: current HP outruns the stored maximum
            # once equipment and buffs are in play (a live save reads 500/200),
            # and demanding hp <= hp_max loses the block entirely.
            if not all(0 < v <= 1_000_000 for v in (hp, hp_max, sp_max)):
                break
            if sp > 1_000_000:
                break
            return Character(name=name, name_offset=start, name_bytes=back,
                             life_id=m.group(1).decode(), life_offset=head,
                             vitals_offset=vitals,
                             hp=hp, hp_max=hp_max, sp=sp, sp_max=sp_max)
    return None


def pack_name(name: str) -> bytes:
    """Serialise a character name back into an FString."""
    raw = name.encode("utf-8", "ignore")[:NAME_MAX - 1] + b"\x00"
    return struct.pack("<i", len(raw)) + raw


def summary(ch: Optional[Character]) -> List[str]:
    if ch is None:
        return ["character block  : not found"]
    return [
        "character        : %s" % ch.name,
        "current life     : %s" % ch.life_id,
        "HP / SP          : %d/%d   %d/%d" % (ch.hp, ch.hp_max, ch.sp, ch.sp_max),
    ]
