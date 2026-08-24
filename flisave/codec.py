"""Outer container codec for Fantasy Life i save files.

File layout (identical on Steam / Android / Switch):

    file      = AES-256-ECB( pkcs7( body || trailer ) )
    body      = uint32 uncompressed_size || zlib_stream
    trailer   = uint32 b_is_valid(1) || md5(body)[16] || 14 zero bytes   (34 bytes)
    plaintext = zlib_stream inflated -> a UE5 "GVAS" blob

The AES key is derived in-game from a UTF-16 literal: every character is copied
into a 32-byte buffer as ``(uint8)ch - 1``, the tail is left at zero, and then
every byte of the buffer is incremented.  The two operations cancel, so the key
is simply the ASCII of the literal, right-padded with 0x01 to 32 bytes.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

from Crypto.Cipher import AES

KEY_PHRASE = "gQPZXDDr8DsT7VU9mTZwJLYa8PnruSEU"


def derive_key(phrase: str = KEY_PHRASE) -> bytes:
    """Reproduce the game's key schedule input from the passphrase literal."""
    raw = bytes((ord(c) - 1) & 0xFF for c in phrase[:32])
    buf = bytearray(32)
    buf[: len(raw)] = raw
    return bytes((b + 1) & 0xFF for b in buf)


KEY = derive_key()
TRAILER_SIZE = 34
BLOCK = 16


class SaveCodecError(Exception):
    pass


def _unpad(data: bytes) -> bytes:
    if not data or len(data) % BLOCK:
        raise SaveCodecError("ciphertext length is not a multiple of 16")
    n = data[-1]
    if not 1 <= n <= BLOCK or data[-n:] != bytes([n]) * n:
        raise SaveCodecError("bad PKCS#7 padding - wrong key or not a save file")
    return data[:-n]


def _pad(data: bytes) -> bytes:
    n = BLOCK - (len(data) % BLOCK)
    return data + bytes([n]) * n


@dataclass
class SaveContainer:
    """A decoded save: the GVAS payload plus everything needed to re-encode."""

    payload: bytes           # inflated GVAS blob
    md5_valid_flag: int = 1  # trailer's bIsValid field
    trailer_pad: bytes = b"\x00" * 14

    @classmethod
    def decode(cls, blob: bytes, *, verify: bool = True) -> "SaveContainer":
        plain = _unpad(AES.new(KEY, AES.MODE_ECB).decrypt(blob))
        if len(plain) < TRAILER_SIZE + 4:
            raise SaveCodecError("decrypted blob is too small")
        body, trailer = plain[:-TRAILER_SIZE], plain[-TRAILER_SIZE:]
        flag = struct.unpack_from("<I", trailer, 0)[0]
        stored = trailer[4:20]
        if verify and flag and hashlib.md5(body).digest() != stored:
            raise SaveCodecError(
                "MD5 mismatch: save is corrupt "
                f"(stored {stored.hex()}, computed {hashlib.md5(body).hexdigest()})"
            )
        size = struct.unpack_from("<I", body, 0)[0]
        payload = zlib.decompress(body[4:])
        if len(payload) != size:
            raise SaveCodecError(
                f"size header says {size} but {len(payload)} bytes were inflated"
            )
        return cls(payload=payload, md5_valid_flag=flag, trailer_pad=trailer[20:])

    def encode(self, *, level: int = 9) -> bytes:
        body = struct.pack("<I", len(self.payload)) + zlib.compress(self.payload, level)
        trailer = (
            struct.pack("<I", self.md5_valid_flag)
            + hashlib.md5(body).digest()
            + self.trailer_pad
        )
        return AES.new(KEY, AES.MODE_ECB).encrypt(_pad(body + trailer))


def decode_file(path) -> SaveContainer:
    with open(path, "rb") as fh:
        return SaveContainer.decode(fh.read())


def encode_file(path, container: SaveContainer, *, level: int = 9) -> int:
    data = container.encode(level=level)
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)
