"""The per-Life arrays (level / experience / rank / equipment loadout).

The payload holds several arrays keyed by the Life ids ``life0000``..``life0014``.
Each is ``uint32 count`` followed by ``count`` entries of
``FString life_id`` + a fixed-size body.  Bodies seen so far:

    9  bytes  uint32 rank, uint8 unk, uint32 pa
    2  bytes  uint16 level
    4  bytes  uint32 experience
    40 bytes  10 x (uint16 item_handle, uint16 item_sort)   equipment loadout
    36 bytes   9 x (uint16 item_handle, uint16 item_sort)   second loadout

The arrays are located by pattern, not by hard-coded offset, so the module
keeps working when the payload shifts (for example after item edits).

``pa`` is the per-Life ability points the game spends on a Life's abilities -
``PA`` in the Italian UI, ``LifeSkillPoint`` in the executable.  ``rank`` is a
0-based index into the ``life_rank_XXXX`` text rows: 0 is "None" (the Life has
not been started), 1 "Novice", 2 "Fledgling".  Both were confirmed against a
live save (Paladin: rank 2 = Fledgling in game, level 10, 40 PA), and ``raw`` is
always available so nothing is hidden behind a guess.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional

# 4-byte length prefix (9) + "life0000\0"
_FIRST = re.compile(rb"\x09\x00\x00\x00life0000\x00")
_ENTRY_HEAD = 13          # FString "lifeXXXX" is always 13 bytes

LIFE_NAMES = {
    "life0000": "(none / villager)",
    "life0001": "Life 1",
    "life0002": "Life 2",
    "life0003": "Life 3",
    "life0004": "Life 4",
    "life0005": "Life 5",
    "life0006": "Life 6",
    "life0007": "Life 7",
    "life0008": "Life 8",
    "life0009": "Life 9",
    "life0010": "Life 10",
    "life0011": "Life 11",
    "life0012": "Life 12",
    "life0013": "Life 13",
    "life0014": "Life 14",
}

# body size -> (array role, [(field name, offset, struct code)])
BODY_LAYOUTS: Dict[int, tuple] = {
    9: ("rank / PA", [("rank", 0, "<I"), ("flag", 4, "<B"),
                      ("pa", 5, "<I")]),
    2: ("level", [("level", 0, "<H")]),
    4: ("experience", [("exp", 0, "<I")]),
    40: ("equipment (10 slots)", []),
    36: ("equipment (9 slots)", []),
}


@dataclass
class LifeEntry:
    life_id: str
    body_offset: int
    body_size: int

    @property
    def label(self) -> str:
        return LIFE_NAMES.get(self.life_id, self.life_id)


class LifeArray:
    def __init__(self, offset: int, count: int, body_size: int,
                 entries: List[LifeEntry]):
        self.offset = offset
        self.count = count
        self.body_size = body_size
        self.entries = entries

    @property
    def role(self) -> str:
        return BODY_LAYOUTS.get(self.body_size, ("body %d bytes" % self.body_size,
                                                 []))[0]

    @property
    def fields(self):
        return BODY_LAYOUTS.get(self.body_size, (None, []))[1]

    def read(self, payload, entry: LifeEntry) -> Dict[str, int]:
        out = {}
        for name, off, code in self.fields:
            out[name] = struct.unpack_from(code, payload, entry.body_offset + off)[0]
        return out

    def write(self, payload, entry: LifeEntry, name: str, value: int) -> None:
        for fname, off, code in self.fields:
            if fname == name:
                struct.pack_into(code, payload, entry.body_offset + off, value)
                return
        raise KeyError("array at 0x%X has no field %r" % (self.offset, name))

    def raw(self, payload, entry: LifeEntry) -> bytes:
        return bytes(payload[entry.body_offset:entry.body_offset + self.body_size])


class LifeSection:
    """All per-Life arrays found in a payload."""

    def __init__(self, arrays: List[LifeArray]):
        self.arrays = arrays

    @classmethod
    def parse(cls, payload: bytes) -> "LifeSection":
        arrays: List[LifeArray] = []
        for m in _FIRST.finditer(payload):
            head = m.start()
            if head < 4:
                continue
            count = struct.unpack_from("<I", payload, head - 4)[0]
            if not 2 <= count <= 64:
                continue
            second = payload.find(b"\x09\x00\x00\x00life0001\x00", m.end())
            if second < 0:
                continue
            stride = second - head
            body = stride - _ENTRY_HEAD
            if body < 0 or body > 4096:
                continue
            entries, pos, ok = [], head, True
            for i in range(count):
                want = ("life%04d" % i).encode()
                if payload[pos:pos + 4] != b"\x09\x00\x00\x00" or \
                        payload[pos + 4:pos + 12] != want:
                    ok = False
                    break
                entries.append(LifeEntry(want.decode(), pos + _ENTRY_HEAD, body))
                pos += stride
            if ok:
                arrays.append(LifeArray(head - 4, count, body, entries))
        return cls(arrays)

    def by_role(self, role: str) -> Optional[LifeArray]:
        for a in self.arrays:
            if a.role == role:
                return a
        return None

    def table(self, payload) -> List[dict]:
        """One row per Life, merging every array that carries named fields."""
        ids = []
        for a in self.arrays:
            for e in a.entries:
                if e.life_id not in ids:
                    ids.append(e.life_id)
        rows = []
        for life_id in sorted(ids):
            row = {"life_id": life_id, "label": LIFE_NAMES.get(life_id, life_id)}
            for a in self.arrays:
                for e in a.entries:
                    if e.life_id != life_id:
                        continue
                    if a.fields:
                        vals = a.read(payload, e)
                        for k, v in vals.items():
                            row[k] = v
                            row["@" + k] = e.body_offset + \
                                next(o for n, o, _ in a.fields if n == k)
            rows.append(row)
        return rows

    def summary(self, payload) -> str:
        out = ["per-Life arrays: %d" % len(self.arrays)]
        for a in self.arrays:
            out.append("  0x%07X  count=%d body=%dB  %s"
                       % (a.offset, a.count, a.body_size, a.role))
        rows = self.table(payload)
        keys = [k for k in ("rank", "flag", "pa", "level", "exp")
                if any(k in r for r in rows)]
        if keys:
            out.append("")
            out.append("  %-10s %s" % ("life", "  ".join("%8s" % k for k in keys)))
            for r in rows:
                out.append("  %-10s %s" % (r["life_id"],
                                           "  ".join("%8s" % r.get(k, "-")
                                                     for k in keys)))
        return "\n".join(out)
