"""Read a cooked UTexture2D out of the shipped paks.

Only what the icon builder needs.  A cooked texture keeps its pixels in the
``.uexp`` right behind the platform data, which is laid out as

    int32   SizeX
    int32   SizeY
    int32   packed (slice count / flags)
    FString pixel format       "PF_ASTC_4x4", "PF_B8G8R8A8", ...
    int32   first mip to serialise
    int32   mip count
    int32   0
    bytes   mip 0

The UI textures this project cares about are all single-mip and never spill
into a ``.ubulk``, so mip 0 is simply the block data that follows.

Decoding needs two build-time packages that the editor itself never imports:
``texture2ddecoder`` for ASTC and ``Pillow`` for the PNG side.  Both are
imported inside the functions that use them, so this module stays importable
without either.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

PIXEL_FORMAT = re.compile(rb"PF_[A-Za-z0-9_]+\x00")

# pixel format -> (block width, block height, bytes per block)
BLOCKS = {
    "PF_ASTC_4x4": (4, 4, 16),
    "PF_ASTC_6x6": (6, 6, 16),
    "PF_ASTC_8x8": (8, 8, 16),
    "PF_DXT1": (4, 4, 8),
    "PF_DXT5": (4, 4, 16),
    "PF_BC7": (4, 4, 16),
    "PF_B8G8R8A8": (1, 1, 4),
    "PF_G8": (1, 1, 1),
}


class TextureError(Exception):
    pass


@dataclass
class Texture:
    name: str
    width: int
    height: int
    pixel_format: str
    data: bytes                  # mip 0, still in its native format

    @property
    def block_size(self) -> Tuple[int, int, int]:
        if self.pixel_format not in BLOCKS:
            raise TextureError("unsupported pixel format %r" % self.pixel_format)
        return BLOCKS[self.pixel_format]

    def expected_bytes(self) -> int:
        bw, bh, size = self.block_size
        return ((self.width + bw - 1) // bw) * ((self.height + bh - 1) // bh) * size

    def to_rgba(self) -> bytes:
        """Decode mip 0 to straight RGBA bytes."""
        fmt = self.pixel_format
        if fmt == "PF_B8G8R8A8":
            b = bytearray(self.data)
            b[0::4], b[2::4] = b[2::4], b[0::4]
            return bytes(b)
        if fmt.startswith("PF_ASTC"):
            import texture2ddecoder
            bw, bh, _ = self.block_size
            raw = texture2ddecoder.decode_astc(self.data, self.width, self.height,
                                               bw, bh)
        elif fmt in ("PF_DXT1", "PF_DXT5", "PF_BC7"):
            import texture2ddecoder
            fn = {"PF_DXT1": texture2ddecoder.decode_bc1,
                  "PF_DXT5": texture2ddecoder.decode_bc3,
                  "PF_BC7": texture2ddecoder.decode_bc7}[fmt]
            raw = fn(self.data, self.width, self.height)
        else:
            raise TextureError("no decoder for %r" % fmt)
        b = bytearray(raw)                      # decoder hands back BGRA
        b[0::4], b[2::4] = b[2::4], b[0::4]
        return bytes(b)

    def to_image(self):
        """Decode to a Pillow image."""
        from PIL import Image
        return Image.frombytes("RGBA", (self.width, self.height), self.to_rgba())


def parse(uexp: bytes, name: str = "") -> Texture:
    """Pull mip 0 out of a cooked texture's ``.uexp``."""
    m = PIXEL_FORMAT.search(uexp)
    if not m:
        raise TextureError("no pixel format string in %s" % (name or "uexp"))
    fmt = uexp[m.start():m.end() - 1].decode("ascii")
    head = m.start() - 4 - 12                   # SizeX, SizeY, packed, then FString
    if head < 0:
        raise TextureError("%s: platform data runs off the front" % name)
    width, height, _packed = struct.unpack_from("<iii", uexp, head)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise TextureError("%s: implausible size %dx%d" % (name, width, height))

    tex = Texture(name, width, height, fmt, b"")
    start = m.end() + 12                        # first mip, mip count, one spare
    want = tex.expected_bytes()
    if start + want > len(uexp):
        raise TextureError("%s: mip 0 wants %d bytes, only %d left"
                           % (name, want, len(uexp) - start))
    tex.data = uexp[start:start + want]
    return tex


def read(pak, base: str) -> Texture:
    """Read ``base`` (a path without extension) out of an open pak."""
    return parse(pak.read(base + ".uexp"), base.split("/")[-1])
