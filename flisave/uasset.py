"""Just enough of the UE5 cooked package format to read a package's name map.

Fantasy Life i's data tables are cooked with unversioned properties, so the
property values themselves have no tags. What we need from the .uasset is the
name map: it holds every FName used by the package, including DataTable row
names. The row payloads in the .uexp are then read positionally.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Tuple

PACKAGE_FILE_TAG = 0x9E2A83C1


class UAssetError(Exception):
    pass


def _fstring(buf: bytes, pos: int) -> Tuple[str, int]:
    n = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if n == 0:
        return "", pos
    if n > 0:
        return buf[pos:pos + n - 1].decode("utf-8", "replace"), pos + n
    n = -n
    return buf[pos:pos + (n - 1) * 2].decode("utf-16le", "replace"), pos + n * 2


@dataclass
class PackageSummary:
    legacy_version: int
    file_version_ue4: int
    file_version_ue5: int
    total_header_size: int
    folder_name: str
    package_flags: int
    name_count: int
    name_offset: int
    export_count: int
    export_offset: int
    import_count: int
    import_offset: int


class UAsset:
    def __init__(self, data: bytes):
        self.data = data
        self.summary = self._read_summary()
        self.names = self._read_names()

    def _read_summary(self) -> PackageSummary:
        d = self.data
        if struct.unpack_from("<I", d, 0)[0] != PACKAGE_FILE_TAG:
            raise UAssetError("not a UE package (bad tag)")
        p = 4
        legacy = struct.unpack_from("<i", d, p)[0]; p += 4
        if legacy != -4:
            p += 4                                  # LegacyUE3Version
        ue4 = struct.unpack_from("<i", d, p)[0]; p += 4
        ue5 = 0
        if legacy <= -8:
            ue5 = struct.unpack_from("<i", d, p)[0]; p += 4
        p += 4                                      # FileVersionLicenseeUE4
        ncustom = struct.unpack_from("<i", d, p)[0]; p += 4
        p += ncustom * 20
        total_header = struct.unpack_from("<i", d, p)[0]; p += 4
        folder, p = _fstring(d, p)
        flags = struct.unpack_from("<I", d, p)[0]; p += 4
        name_count, name_offset = struct.unpack_from("<ii", d, p); p += 8
        # PKG_FilterEditorOnly cooked packages skip LocalizationId
        if not (flags & 0x80000000):
            _, p = _fstring(d, p)                   # LocalizationId
        p += 8                                      # GatherableTextData count/offset
        export_count, export_offset = struct.unpack_from("<ii", d, p); p += 8
        import_count, import_offset = struct.unpack_from("<ii", d, p); p += 8
        return PackageSummary(legacy, ue4, ue5, total_header, folder, flags,
                              name_count, name_offset,
                              export_count, export_offset,
                              import_count, import_offset)

    def _read_names(self) -> List[str]:
        s = self.summary
        if not (0 < s.name_offset < len(self.data)):
            raise UAssetError("name map offset out of range")
        p = s.name_offset
        out = []
        for _ in range(s.name_count):
            name, p = _fstring(self.data, p)
            p += 4                                  # hashes (2 x uint16)
            out.append(name)
        return out

    def name(self, index: int) -> str:
        return self.names[index] if 0 <= index < len(self.names) else "<%d>" % index
