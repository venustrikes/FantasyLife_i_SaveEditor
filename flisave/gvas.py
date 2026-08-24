"""UE5 GVAS header plus the LEVEL5 sub-header that follows it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .stream import Reader

GVAS_MAGIC = b"GVAS"
L5_MAGIC = 0xAB16A21A


@dataclass
class GvasHeader:
    save_game_version: int
    package_ue4: int
    package_ue5: int
    engine: Tuple[int, int, int, int, str]
    custom_version_format: int
    custom_versions: List[Tuple[str, int]] = field(default_factory=list)
    save_class: str = ""
    header_size: int = 0          # bytes consumed by the GVAS header itself
    l5_magic: int = 0
    l5_version: int = 0
    l5_flags: int = 0
    build_id: str = ""
    body_offset: int = 0          # first byte after the LEVEL5 sub-header

    @classmethod
    def parse(cls, payload: bytes) -> "GvasHeader":
        r = Reader(payload)
        if r.bytes(4) != GVAS_MAGIC:
            raise ValueError("not a GVAS payload")
        sgv, p4, p5 = r.u32(), r.u32(), r.u32()
        eng = (r.u16(), r.u16(), r.u16(), r.u32(), r.fstring())
        cvf = r.u32()
        n = r.u32()
        cvs = [(r.bytes(16).hex(), r.i32()) for _ in range(n)]
        hdr_size = r.pos
        klass = r.fstring()
        l5_magic = r.u32()
        l5_version = r.u32()
        l5_flags = r.u32()
        build = r.fstring()
        return cls(sgv, p4, p5, eng, cvf, cvs, klass, hdr_size,
                   l5_magic, l5_version, l5_flags, build, r.pos)

    @property
    def engine_version(self) -> str:
        a, b, c, cl, branch = self.engine
        return f"{a}.{b}.{c} (cl {cl}, {branch})"
