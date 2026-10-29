"""Bounded, data-only reader for Gameloft's multipart offset containers."""
from dataclasses import dataclass
import lzma
import struct

MAX_BLOCK = 16 * 1024 * 1024


@dataclass(frozen=True)
class PackPart:
    name: str
    first_index: int
    offsets: tuple[int, ...]


def layout(name, read):
    """Return a layout only when all parts have valid, exact offset tables."""
    data = read(name)
    if len(data) < 10:
        return None
    total, parts = struct.unpack_from('<HH', data)
    if not (0 < total <= 4096 and 0 < parts <= 16 and 4 + 2 * parts <= len(data)):
        return None
    starts = struct.unpack_from('<' + 'H' * parts, data, 4)
    if starts[0] != 0 or list(starts) != sorted(set(starts)) or starts[-1] >= total:
        return None
    result = []
    for part in range(parts):
        part_name = name if part == 0 else name + '.' + str(part)
        try:
            payload = data if part == 0 else read(part_name)
        except KeyError:
            return None
        count = (starts[part + 1] if part + 1 < parts else total) - starts[part]
        start = 4 + 2 * parts if part == 0 else 0
        end = start + 4 * (count + 1)
        if end > len(payload):
            return None
        offsets = struct.unpack_from('<' + 'I' * (count + 1), payload, start)
        if offsets[0] != end or offsets[-1] != len(payload) or list(offsets) != sorted(offsets):
            return None
        result.append(PackPart(part_name, starts[part], offsets))
    return result


def unpack(parts, read):
    """Yield index, content type and uncompressed block bytes; never execute game code."""
    for part in parts:
        data = read(part.name)
        for local, (start, end) in enumerate(zip(part.offsets, part.offsets[1:])):
            blob = data[start:end]
            if not blob:
                continue
            marker = blob[0]
            content = blob[1:]
            if marker >= 127:
                decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE, memlimit=64 * 1024 * 1024)
                content = decoder.decompress(content, max_length=MAX_BLOCK + 1)
                if not decoder.eof or len(content) > MAX_BLOCK:
                    raise ValueError('Compressed asset exceeds the decoder limit or is truncated')
            if len(content) > MAX_BLOCK:
                raise ValueError('Asset block exceeds the decoder limit')
            yield part.first_index + local, marker - 127 if marker >= 127 else marker, content
