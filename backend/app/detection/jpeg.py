"""app/detection/jpeg.py — Pure-Python in-memory JPEG header & size validation.

Validates uploaded Socket.IO frames without writing any file to disk and
without importing OpenCV/Pillow so B5a works with no vision dependencies.
"""
from __future__ import annotations

import struct
from typing import Any

MAX_FRAME_BYTES = 300 * 1024  # 300 KB (contract §8)
MAX_FRAME_WIDTH = 1280        # px (contract §8)

_SOF_MARKERS = frozenset(
    {
        0xC0, 0xC1, 0xC2, 0xC3,
        0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB,
        0xCD, 0xCE, 0xCF,
    }
)


def parse_jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Parse `(width, height)` from a JPEG byte stream in RAM.

    Raises ValueError if *data* is not a valid JPEG with a Start-Of-Frame header.
    """
    n = len(data)
    if n < 4 or data[0] != 0xFF or data[1] != 0xD8:
        raise ValueError("Not a JPEG stream (missing SOI marker).")

    idx = 2
    while idx < n:
        # Seek next 0xFF marker prefix
        if data[idx] != 0xFF:
            idx += 1
            continue
        while idx < n and data[idx] == 0xFF:
            idx += 1
        if idx >= n:
            break

        marker = data[idx]
        idx += 1

        if marker == 0x00 or marker == 0x01 or (0xD0 <= marker <= 0xD7) or marker == 0xD8:
            continue
        if marker == 0xD9 or marker == 0xDA:
            # EOI or Start of Scan reached without finding SOF
            break

        if idx + 2 > n:
            break
        seg_len = struct.unpack(">H", data[idx : idx + 2])[0]
        if seg_len < 2 or idx + seg_len > n:
            raise ValueError("Malformed JPEG segment length.")

        if marker in _SOF_MARKERS:
            if seg_len < 7:
                raise ValueError("Truncated JPEG SOF segment.")
            height, width = struct.unpack(">HH", data[idx + 3 : idx + 7])
            if width <= 0 or height <= 0:
                raise ValueError("Invalid JPEG dimensions.")
            return width, height

        idx += seg_len

    raise ValueError("Missing JPEG Start-Of-Frame header.")


def validate_jpeg_frame(
    image: Any,
    declared_width: Any = None,
    declared_height: Any = None,
) -> tuple[bytes, int, int]:
    """Validate frame bytes, JPEG header, byte limit (<=300 KB), and width (<=1280).

    Returns `(jpeg_bytes, width, height)`. Raises `ValueError` on any violation.
    """
    if isinstance(image, (bytearray, memoryview)):
        jpeg_bytes = bytes(image)
    elif isinstance(image, bytes):
        jpeg_bytes = image
    else:
        raise ValueError("Frame image must be binary bytes.")

    if len(jpeg_bytes) == 0 or len(jpeg_bytes) > MAX_FRAME_BYTES:
        raise ValueError(
            f"JPEG size {len(jpeg_bytes)} out of allowed range 1..{MAX_FRAME_BYTES} bytes."
        )

    width, height = parse_jpeg_dimensions(jpeg_bytes)
    if width > MAX_FRAME_WIDTH:
        raise ValueError(f"JPEG width {width} exceeds limit {MAX_FRAME_WIDTH}.")

    if declared_width is not None:
        if (
            not isinstance(declared_width, int)
            or isinstance(declared_width, bool)
            or declared_width <= 0
            or declared_width > MAX_FRAME_WIDTH
            or declared_width != width
        ):
            raise ValueError("Declared frame width invalid or mismatched.")

    if declared_height is not None:
        if (
            not isinstance(declared_height, int)
            or isinstance(declared_height, bool)
            or declared_height <= 0
            or declared_height != height
        ):
            raise ValueError("Declared frame height invalid or mismatched.")

    return jpeg_bytes, width, height
