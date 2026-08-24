"""Little-endian reader/writer for the UE archive primitives used by the save."""
from __future__ import annotations

import struct


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def bytes(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        if len(v) != n:
            raise EOFError(f"want {n} bytes at 0x{self.pos:X}, got {len(v)}")
        self.pos += n
        return v

    def u8(self) -> int:
        return self.bytes(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.bytes(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.bytes(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.bytes(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.bytes(8))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.bytes(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.bytes(8))[0]

    def fstring(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            return self.bytes(n)[:-1].decode("utf-8", "replace")
        return self.bytes(-n * 2)[:-2].decode("utf-16le", "replace")

    def peek(self, n: int) -> bytes:
        return self.data[self.pos:self.pos + n]


def pack_fstring(s: str) -> bytes:
    """Encode an FString the way the game does (ASCII if it fits, else UTF-16)."""
    if s == "":
        return struct.pack("<i", 0)
    try:
        raw = s.encode("ascii") + b"\x00"
        return struct.pack("<i", len(raw)) + raw
    except UnicodeEncodeError:
        raw = s.encode("utf-16le") + b"\x00\x00"
        return struct.pack("<i", -(len(raw) // 2)) + raw


def fstring_size(s: str) -> int:
    return len(pack_fstring(s))
