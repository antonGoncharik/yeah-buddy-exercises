#!/usr/bin/env python3
"""Strip non-essential metadata from exercise preview JPG/GIF files in-place."""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def strip_jpeg(data: bytes) -> bytes:
    if len(data) < 2 or data[:2] != b"\xff\xd8":
        return data

    out = bytearray(b"\xff\xd8")
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        i += 2

        if marker == 0xDA:
            out.extend(data[i - 2 :])
            return bytes(out)
        if marker == 0xD9:
            out.extend(b"\xff\xd9")
            return bytes(out)
        if i + 2 > len(data):
            break

        length = struct.unpack(">H", data[i : i + 2])[0]
        if length < 2 or i + length > len(data):
            break

        segment = data[i - 2 : i + length]
        if marker in range(0xE0, 0xF0) or marker == 0xFE:
            i += length
            continue

        out.extend(segment)
        i += length

    return bytes(out)


def _read_sub_blocks(data: bytes, pos: int) -> int:
    while pos < len(data):
        size = data[pos]
        pos += 1
        if size == 0:
            return pos
        pos += size
    return pos


def _extension_end(data: bytes, pos: int) -> int:
    """pos points at 0x21 extension introducer."""
    if pos + 2 > len(data) or data[pos] != 0x21:
        return pos + 1
    return _read_sub_blocks(data, pos + 2)


def _image_block_end(data: bytes, pos: int) -> int:
    """pos points at 0x2C image separator."""
    if pos + 10 > len(data) or data[pos] != 0x2C:
        return pos + 1
    cur = pos + 10
    packed = data[cur - 1]
    if packed & 0x80:
        lct_bytes = 3 * (2 ** ((packed & 0x07) + 1))
        cur += lct_bytes
    cur += 1
    return _read_sub_blocks(data, cur)


def _is_xmp_application(data: bytes, pos: int) -> bool:
    if pos + 14 > len(data) or data[pos] != 0x21 or data[pos + 1] != 0xFF:
        return False
    app_id = data[pos + 3 : pos + 11]
    return app_id.startswith(b"XMP")


def strip_gif(data: bytes) -> bytes:
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return data

    out = bytearray()
    pos = 13
    packed = data[10]
    if packed & 0x80:
        gct_bytes = 3 * (2 ** ((packed & 0x07) + 1))
        pos = 13 + gct_bytes

    out.extend(data[:pos])

    while pos < len(data):
        byte = data[pos]

        if byte == 0x3B:
            out.append(0x3B)
            break

        if byte == 0x21:
            end = _extension_end(data, pos)
            ext_label = data[pos + 1]
            if ext_label == 0xFE or _is_xmp_application(data, pos):
                pos = end
                continue
            out.extend(data[pos:end])
            pos = end
            continue

        if byte == 0x2C:
            end = _image_block_end(data, pos)
            out.extend(data[pos:end])
            pos = end
            continue

        out.append(byte)
        pos += 1

    return bytes(out)


def process_file(path: Path, dry_run: bool) -> tuple[bool, int]:
    original = path.read_bytes()
    if path.suffix.lower() == ".jpg":
        cleaned = strip_jpeg(original)
    elif path.suffix.lower() == ".gif":
        cleaned = strip_gif(original)
    else:
        return False, 0

    if cleaned == original:
        return False, 0

    if not dry_run:
        path.write_bytes(cleaned)
    return True, len(original) - len(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing files",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    images = sorted((root / "images").glob("*.jpg"))
    videos = sorted((root / "videos").glob("*.gif"))
    paths = images + videos

    changed = 0
    bytes_saved = 0
    for path in paths:
        did_change, saved = process_file(path, args.dry_run)
        if did_change:
            changed += 1
            bytes_saved += saved

    mode = "would update" if args.dry_run else "updated"
    print(
        f"{mode} {changed}/{len(paths)} files "
        f"({bytes_saved} bytes removed)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
