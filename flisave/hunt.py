"""Progressive value hunting across one or more saves.

Works like a memory scanner: the first pass records every offset holding a
known value, later passes intersect that set with the offsets holding the new
value.  Two or three passes usually pin a field down exactly.
"""
from __future__ import annotations

import json
import os
import struct
from typing import Dict, List, Optional

TYPES = {
    "u8": ("<B", 1), "i8": ("<b", 1),
    "u16": ("<H", 2), "i16": ("<h", 2),
    "u32": ("<I", 4), "i32": ("<i", 4),
    "u64": ("<Q", 8), "i64": ("<q", 8),
    "f32": ("<f", 4), "f64": ("<d", 8),
}


def scan(payload: bytes, value, kind: str = "u32") -> List[int]:
    fmt, _ = TYPES[kind]
    needle = struct.pack(fmt, value)
    hits, i = [], 0
    while True:
        i = payload.find(needle, i)
        if i < 0:
            return hits
        hits.append(i)
        i += 1


def scan_all_types(payload: bytes, value: int, kinds=("u32", "u16", "u64", "i32")
                   ) -> Dict[str, List[int]]:
    out = {}
    for k in kinds:
        fmt, size = TYPES[k]
        try:
            struct.pack(fmt, value)
        except struct.error:
            continue
        out[k] = scan(payload, value, k)
    return out


class Hunt:
    """Candidate set carried between passes, persisted as small JSON."""

    def __init__(self, kind: str = "u32", candidates: Optional[List[int]] = None,
                 history: Optional[List] = None):
        self.kind = kind
        self.candidates = candidates
        self.history = history or []

    @classmethod
    def load(cls, path: str) -> "Hunt":
        if not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return cls(d.get("kind", "u32"), d.get("candidates"), d.get("history"))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"kind": self.kind, "candidates": self.candidates,
                       "history": self.history}, fh)

    def step(self, payload: bytes, value, kind: Optional[str] = None) -> List[int]:
        kind = kind or self.kind
        if self.candidates is not None and kind != self.kind:
            raise ValueError("hunt already started with type %r" % self.kind)
        self.kind = kind
        hits = scan(payload, value, kind)
        if self.candidates is None:
            self.candidates = hits
        else:
            keep = set(hits)
            self.candidates = [o for o in self.candidates if o in keep]
        self.history.append({"value": value, "hits": len(hits),
                             "remaining": len(self.candidates)})
        return self.candidates
