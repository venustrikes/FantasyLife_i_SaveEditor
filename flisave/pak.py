"""Minimal reader for Unreal Engine .pak archives (version 8-11).

Only what is needed to pull asset files out of the Fantasy Life i Android
build: unencrypted index, path-hash/full-directory index layout, and Zlib or
uncompressed block data.
"""
from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

PAK_MAGIC = 0x5A6F12E1
COMPRESSION_NAME_LEN = 32


class PakError(Exception):
    pass


def _fstring(buf: bytes, pos: int) -> Tuple[str, int]:
    n = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        s = buf[pos:pos + n - 1].decode("utf-8", "replace")
        return s, pos + n
    n = -n
    s = buf[pos:pos + (n - 1) * 2].decode("utf-16le", "replace")
    return s, pos + n * 2


@dataclass
class PakEntry:
    offset: int
    size: int                 # bytes on disk
    uncompressed_size: int
    compression: int          # index into PakFile.compression_methods
    encrypted: bool
    blocks: List[Tuple[int, int]]      # (start, end) relative to entry offset
    block_size: int

    @property
    def compressed(self) -> bool:
        return self.compression != 0


class PakFile:
    """Random-access reader over a .pak file object."""

    def __init__(self, fh, size: Optional[int] = None):
        self.fh = fh
        if size is None:
            fh.seek(0, io.SEEK_END)
            size = fh.tell()
        self.size = size
        self.mount_point = ""
        self.compression_methods: List[str] = ["None"]
        self.entries: Dict[str, PakEntry] = {}
        self._read_footer()
        self._read_index()

    # ------------------------------------------------------------------ io
    def _read(self, offset: int, length: int) -> bytes:
        self.fh.seek(offset)
        out = self.fh.read(length)
        if len(out) != length:
            raise PakError("short read at 0x%X (%d/%d)" % (offset, len(out), length))
        return out

    # -------------------------------------------------------------- footer
    def _read_footer(self) -> None:
        tail = self._read(max(0, self.size - 1024), min(1024, self.size))
        magic = struct.pack("<I", PAK_MAGIC)
        pos = tail.rfind(magic)
        if pos < 0:
            raise PakError("pak magic not found; not a .pak file")
        base = self.size - len(tail) + pos
        self.version = struct.unpack_from("<I", tail, pos + 4)[0]
        self.index_offset, self.index_size = struct.unpack_from("<qq", tail, pos + 8)
        p = pos + 4 + 4 + 8 + 8 + 20
        if self.version >= 8:
            count = 5 if self.version >= 9 else 4
            methods = []
            for i in range(count):
                raw = tail[p + i * COMPRESSION_NAME_LEN:
                           p + (i + 1) * COMPRESSION_NAME_LEN]
                name = raw.split(b"\x00")[0].decode("ascii", "replace")
                if name:
                    methods.append(name)
            self.compression_methods = ["None"] + methods
        self.encrypted_index = bool(tail[pos - 1]) if pos >= 1 else False
        self.footer_at = base

    # --------------------------------------------------------------- index
    def _read_index(self) -> None:
        if self.encrypted_index:
            raise PakError("index is encrypted; no key available")
        idx = self._read(self.index_offset, self.index_size)
        p = 0
        self.mount_point, p = _fstring(idx, p)
        num_entries = struct.unpack_from("<i", idx, p)[0]
        p += 4
        if self.version < 10:
            raise PakError("pak version %d index layout not supported" % self.version)
        p += 8                                   # PathHashSeed
        has_path_hash = struct.unpack_from("<i", idx, p)[0]
        p += 4
        if has_path_hash:
            p += 8 + 8 + 20                      # offset, size, hash
        has_full_dir = struct.unpack_from("<i", idx, p)[0]
        p += 4
        if not has_full_dir:
            raise PakError("pak has no full directory index; cannot list names")
        dir_off, dir_size = struct.unpack_from("<qq", idx, p)
        p += 8 + 8 + 20
        enc_len = struct.unpack_from("<i", idx, p)[0]
        p += 4
        encoded = idx[p:p + enc_len]

        raw = self._read(dir_off, dir_size)
        q = 0
        ndirs = struct.unpack_from("<i", raw, q)[0]
        q += 4
        for _ in range(ndirs):
            dname, q = _fstring(raw, q)
            nfiles = struct.unpack_from("<i", raw, q)[0]
            q += 4
            for _ in range(nfiles):
                fname, q = _fstring(raw, q)
                where = struct.unpack_from("<i", raw, q)[0]
                q += 4
                if where < 0:
                    continue                     # entry stored unencoded; skipped
                path = (self.mount_point + dname + fname).replace("../../../", "")
                self.entries[path] = self._decode_entry(encoded, where)
        self.num_entries = num_entries

    def _decode_entry(self, buf: bytes, at: int) -> PakEntry:
        flags = struct.unpack_from("<I", buf, at)[0]
        p = at + 4
        comp = (flags >> 23) & 0x3F
        encrypted = bool(flags & (1 << 22))
        nblocks = (flags >> 6) & 0xFFFF
        block_size = (flags & 0x3F) << 11

        if flags & (1 << 31):
            offset = struct.unpack_from("<I", buf, p)[0]; p += 4
        else:
            offset = struct.unpack_from("<Q", buf, p)[0]; p += 8
        if flags & (1 << 30):
            usize = struct.unpack_from("<I", buf, p)[0]; p += 4
        else:
            usize = struct.unpack_from("<Q", buf, p)[0]; p += 8
        if comp != 0:
            if flags & (1 << 29):
                size = struct.unpack_from("<I", buf, p)[0]; p += 4
            else:
                size = struct.unpack_from("<Q", buf, p)[0]; p += 8
        else:
            size = usize

        # A one-block entry stores no block table: the whole file is one chunk.
        if nblocks == 1:
            block_size = usize

        blocks: List[Tuple[int, int]] = []
        if comp != 0:
            if nblocks == 1 and not encrypted:
                header = self._entry_header_size(offset, comp, 1)
                blocks = [(header, header + size)]
            elif nblocks > 0:
                start = 0
                for _ in range(nblocks):
                    bsize = struct.unpack_from("<I", buf, p)[0]
                    p += 4
                    blocks.append((start, start + bsize))
                    start += _align(bsize, 16) if encrypted else bsize
                header = self._entry_header_size(offset, comp, nblocks)
                blocks = [(a + header, b + header) for a, b in blocks]
        return PakEntry(offset, size, usize, comp, encrypted, blocks, block_size)

    def _entry_header_size(self, offset: int, comp: int, nblocks: int) -> int:
        # FPakEntry serialised in front of the data: offset, size, usize,
        # method, hash[20], (blocks), flags, block size
        n = 8 + 8 + 8 + 4 + 20
        if comp != 0:
            n += 4 + nblocks * 16
        n += 1 + 4
        return n

    # ----------------------------------------------------------------- read
    def read(self, path: str) -> bytes:
        e = self.entries[path]
        if e.encrypted:
            raise PakError("%s is encrypted" % path)
        method = self.compression_methods[e.compression] \
            if e.compression < len(self.compression_methods) else "?"
        if e.compression == 0:
            header = self._entry_header_size(e.offset, 0, 0)
            return self._read(e.offset + header, e.uncompressed_size)
        out = bytearray()
        low = method.lower()
        if low in ("zlib", "gzip"):
            for a, b in e.blocks:
                out += zlib.decompress(self._read(e.offset + a, b - a))
        elif low == "oodle":
            from . import oodle
            dec = oodle.get()
            remaining = e.uncompressed_size
            for a, b in e.blocks:
                want = min(e.block_size, remaining)
                out += dec.decompress(self._read(e.offset + a, b - a), want)
                remaining -= want
        else:
            raise PakError("%s uses unsupported compression %r" % (path, method))
        return bytes(out[:e.uncompressed_size])

    def list(self, needle: str = "") -> List[str]:
        n = needle.lower()
        return sorted(p for p in self.entries if n in p.lower())


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a
