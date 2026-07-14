from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


class ManagedAssemblyError(ValueError):
    """Raised when a file does not contain readable CLR assembly metadata."""


@dataclass(frozen=True)
class AssemblyIdentity:
    name: str
    version: str
    public_key_token: str


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _compressed_uint(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    if first & 0x80 == 0:
        return first, offset + 1
    if first & 0xC0 == 0x80:
        return ((first & 0x3F) << 8) | data[offset + 1], offset + 2
    if first & 0xE0 == 0xC0:
        return (
            ((first & 0x1F) << 24)
            | (data[offset + 1] << 16)
            | (data[offset + 2] << 8)
            | data[offset + 3],
            offset + 4,
        )
    raise ManagedAssemblyError("invalid compressed metadata integer")


def _read_heap_index(data: bytes, offset: int, size: int) -> tuple[int, int]:
    if size == 2:
        return _u16(data, offset), offset + 2
    return _u32(data, offset), offset + 4


def _read_string(heap: bytes, index: int) -> str:
    if index == 0:
        return ""
    end = heap.find(b"\0", index)
    if end < 0:
        raise ManagedAssemblyError("unterminated metadata string")
    return heap[index:end].decode("utf-8")


def _read_blob(heap: bytes, index: int) -> bytes:
    if index == 0:
        return b""
    size, start = _compressed_uint(heap, index)
    end = start + size
    if end > len(heap):
        raise ManagedAssemblyError("metadata blob exceeds its heap")
    return heap[start:end]


_TYPEDEF_OR_REF = ([2, 1, 27], 2)
_HAS_CONSTANT = ([4, 8, 23], 2)
_HAS_CUSTOM_ATTRIBUTE = (
    [6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 44, 43],
    5,
)
_HAS_FIELD_MARSHAL = ([4, 8], 1)
_HAS_DECL_SECURITY = ([2, 6, 32], 2)
_MEMBER_REF_PARENT = ([2, 1, 26, 6, 27], 3)
_HAS_SEMANTICS = ([20, 23], 1)
_METHOD_DEF_OR_REF = ([6, 10], 1)
_MEMBER_FORWARDED = ([4, 6], 1)
_CUSTOM_ATTRIBUTE_TYPE = ([6, 10], 3)
_RESOLUTION_SCOPE = ([0, 26, 35, 1], 2)


def _table_index_size(rows: list[int], table: int) -> int:
    return 2 if rows[table] < 0x10000 else 4


def _coded_index_size(rows: list[int], coded: tuple[list[int], int]) -> int:
    tables, tag_bits = coded
    limit = 1 << (16 - tag_bits)
    return 2 if max((rows[table] for table in tables), default=0) < limit else 4


def _row_size(
    table: int,
    rows: list[int],
    string_size: int,
    guid_size: int,
    blob_size: int,
) -> int:
    table_index = lambda target: _table_index_size(rows, target)
    coded_index = lambda coded: _coded_index_size(rows, coded)
    schemas = {
        0: (2, string_size, guid_size, guid_size, guid_size),
        1: (coded_index(_RESOLUTION_SCOPE), string_size, string_size),
        2: (4, string_size, string_size, coded_index(_TYPEDEF_OR_REF), table_index(4), table_index(6)),
        3: (table_index(4),),
        4: (2, string_size, blob_size),
        5: (table_index(6),),
        6: (4, 2, 2, string_size, blob_size, table_index(8)),
        7: (table_index(8),),
        8: (2, 2, string_size),
        9: (table_index(2), coded_index(_TYPEDEF_OR_REF)),
        10: (coded_index(_MEMBER_REF_PARENT), string_size, blob_size),
        11: (2, coded_index(_HAS_CONSTANT), blob_size),
        12: (coded_index(_HAS_CUSTOM_ATTRIBUTE), coded_index(_CUSTOM_ATTRIBUTE_TYPE), blob_size),
        13: (coded_index(_HAS_FIELD_MARSHAL), blob_size),
        14: (2, coded_index(_HAS_DECL_SECURITY), blob_size),
        15: (2, 4, table_index(2)),
        16: (4, table_index(4)),
        17: (blob_size,),
        18: (table_index(2), table_index(20)),
        19: (table_index(20),),
        20: (2, string_size, coded_index(_TYPEDEF_OR_REF)),
        21: (table_index(2), table_index(23)),
        22: (table_index(23),),
        23: (2, string_size, blob_size),
        24: (2, table_index(6), coded_index(_HAS_SEMANTICS)),
        25: (table_index(2), coded_index(_METHOD_DEF_OR_REF), coded_index(_METHOD_DEF_OR_REF)),
        26: (string_size,),
        27: (blob_size,),
        28: (2, coded_index(_MEMBER_FORWARDED), string_size, table_index(26)),
        29: (4, table_index(4)),
        30: (4, 4),
        31: (4,),
    }
    try:
        return sum(schemas[table])
    except KeyError as exc:
        raise ManagedAssemblyError(f"unsupported metadata table before Assembly: {table}") from exc


def _rva_to_offset(data: bytes, pe_offset: int, optional_size: int, rva: int) -> int:
    section_count = _u16(data, pe_offset + 6)
    section_offset = pe_offset + 24 + optional_size
    for index in range(section_count):
        offset = section_offset + index * 40
        virtual_size = _u32(data, offset + 8)
        virtual_address = _u32(data, offset + 12)
        raw_size = _u32(data, offset + 16)
        raw_offset = _u32(data, offset + 20)
        span = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + span:
            return raw_offset + (rva - virtual_address)
    raise ManagedAssemblyError(f"RVA 0x{rva:x} is outside PE sections")


def read_assembly_identity(path: str | Path) -> AssemblyIdentity:
    data = Path(path).read_bytes()
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise ManagedAssemblyError("not a PE file")

    pe_offset = _u32(data, 0x3C)
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ManagedAssemblyError("missing PE signature")
    optional_size = _u16(data, pe_offset + 20)
    optional_offset = pe_offset + 24
    magic = _u16(data, optional_offset)
    if magic == 0x10B:
        directory_offset = optional_offset + 96
    elif magic == 0x20B:
        directory_offset = optional_offset + 112
    else:
        raise ManagedAssemblyError("unsupported PE optional header")

    cli_rva = _u32(data, directory_offset + 14 * 8)
    if cli_rva == 0:
        raise ManagedAssemblyError("not a managed assembly")
    cli_offset = _rva_to_offset(data, pe_offset, optional_size, cli_rva)
    metadata_rva = _u32(data, cli_offset + 8)
    metadata_offset = _rva_to_offset(data, pe_offset, optional_size, metadata_rva)
    if _u32(data, metadata_offset) != 0x424A5342:
        raise ManagedAssemblyError("invalid CLR metadata signature")

    version_length = _u32(data, metadata_offset + 12)
    streams_header = (metadata_offset + 16 + version_length + 3) & ~3
    stream_count = _u16(data, streams_header + 2)
    cursor = streams_header + 4
    streams: dict[str, bytes] = {}
    for _ in range(stream_count):
        relative = _u32(data, cursor)
        size = _u32(data, cursor + 4)
        name_start = cursor + 8
        name_end = data.index(0, name_start)
        name = data[name_start:name_end].decode("ascii")
        cursor = (name_end + 4) & ~3
        streams[name] = data[metadata_offset + relative:metadata_offset + relative + size]

    tables = streams.get("#~") or streams.get("#-")
    strings = streams.get("#Strings")
    blobs = streams.get("#Blob")
    if tables is None or strings is None or blobs is None:
        raise ManagedAssemblyError("required CLR metadata streams are missing")

    heap_sizes = tables[6]
    string_size = 4 if heap_sizes & 0x01 else 2
    guid_size = 4 if heap_sizes & 0x02 else 2
    blob_size = 4 if heap_sizes & 0x04 else 2
    valid = _u64(tables, 8)
    cursor = 24
    rows = [0] * 64
    for table in range(64):
        if valid & (1 << table):
            rows[table] = _u32(tables, cursor)
            cursor += 4

    assembly_table = 32
    if rows[assembly_table] != 1:
        raise ManagedAssemblyError("assembly metadata table is missing or ambiguous")
    for table in range(assembly_table):
        if rows[table]:
            cursor += rows[table] * _row_size(table, rows, string_size, guid_size, blob_size)

    major = _u16(tables, cursor + 4)
    minor = _u16(tables, cursor + 6)
    build = _u16(tables, cursor + 8)
    revision = _u16(tables, cursor + 10)
    flags = _u32(tables, cursor + 12)
    index = cursor + 16
    public_key_index, index = _read_heap_index(tables, index, blob_size)
    name_index, index = _read_heap_index(tables, index, string_size)
    _culture_index, index = _read_heap_index(tables, index, string_size)

    name = _read_string(strings, name_index)
    public_key = _read_blob(blobs, public_key_index)
    token = ""
    if public_key:
        if flags & 0x0001:
            token = hashlib.sha1(public_key).digest()[-8:][::-1].hex()
        elif len(public_key) == 8:
            token = public_key.hex()
        else:
            token = hashlib.sha1(public_key).digest()[-8:][::-1].hex()

    return AssemblyIdentity(
        name=name,
        version=f"{major}.{minor}.{build}.{revision}",
        public_key_token=token,
    )


def inventory(root: Path, output: Path) -> None:
    lines: list[str] = []
    ignored = (
        ManagedAssemblyError,
        OSError,
        ValueError,
        struct.error,
        IndexError,
        UnicodeDecodeError,
    )
    for path in sorted(root.rglob("*.dll")):
        try:
            identity = read_assembly_identity(path)
        except ignored:
            continue
        lines.append(
            "\t".join(
                (
                    path.relative_to(root).as_posix(),
                    identity.name,
                    identity.version,
                    identity.public_key_token,
                )
            )
        )
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    inventory(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
