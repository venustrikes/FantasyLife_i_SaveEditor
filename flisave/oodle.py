"""ctypes binding for Oodle's decompressor.

Oodle is proprietary and cannot be shipped with this tool, but a copy of
``oo2core_*_win64.dll`` is present in most UE4/UE5 game installs. Point
``FLI_OODLE_DLL`` at one, drop it next to this file, or pass an explicit path.
The decoder is version-tolerant: an oo2core 8 or 9 build decodes the Kraken
data in the Fantasy Life i paks.
"""
from __future__ import annotations

import ctypes
import glob
import os
from typing import List, Optional

_SEARCH_GLOBS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "oo2core_*_win64.dll"),
    os.path.expanduser(r"~\Downloads\**\oo2core_*_win64.dll"),
    r"C:\Program Files\**\oo2core_*_win64.dll",
    r"C:\Program Files (x86)\**\oo2core_*_win64.dll",
]


class OodleError(Exception):
    pass


def find_dll() -> Optional[str]:
    env = os.environ.get("FLI_OODLE_DLL")
    if env and os.path.isfile(env):
        return env
    for pattern in _SEARCH_GLOBS:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[-1]          # highest version number wins
    return None


class Oodle:
    """Thin wrapper around OodleLZ_Decompress."""

    def __init__(self, dll_path: Optional[str] = None):
        path = dll_path or find_dll()
        if not path:
            raise OodleError(
                "no oo2core_*_win64.dll found. Set FLI_OODLE_DLL to one, or put "
                "a copy next to this project. Any UE4/UE5 game install has one.")
        self.path = path
        self._lib = ctypes.CDLL(path)
        fn = self._lib.OodleLZ_Decompress
        fn.restype = ctypes.c_int64
        fn.argtypes = [
            ctypes.c_char_p, ctypes.c_int64,      # compressed buffer, size
            ctypes.c_char_p, ctypes.c_int64,      # raw buffer, size
            ctypes.c_int32,                       # fuzz safe
            ctypes.c_int32,                       # check crc
            ctypes.c_int32,                       # verbosity
            ctypes.c_void_p, ctypes.c_int64,      # decode buffer base/size
            ctypes.c_void_p, ctypes.c_void_p,     # callback, user data
            ctypes.c_void_p, ctypes.c_int64,      # scratch memory, size
            ctypes.c_int32,                       # thread phase
        ]
        self._fn = fn

    def decompress(self, src: bytes, out_size: int) -> bytes:
        dst = ctypes.create_string_buffer(out_size + 64)
        n = self._fn(src, len(src), dst, out_size,
                     1,      # OodleLZ_FuzzSafe_Yes
                     0,      # OodleLZ_CheckCRC_No
                     0,      # verbosity
                     None, 0, None, None, None, 0,
                     3)      # OodleLZ_Decode_Unthreaded
        if n != out_size:
            raise OodleError("OodleLZ_Decompress returned %d, expected %d"
                             % (n, out_size))
        return dst.raw[:out_size]


_shared: Optional[Oodle] = None


def get(dll_path: Optional[str] = None) -> Oodle:
    global _shared
    if _shared is None or dll_path:
        _shared = Oodle(dll_path)
    return _shared
