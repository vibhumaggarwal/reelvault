"""
Dense codec: every byte becomes one colour channel of one pixel (24 bits per
pixel). Smallest output, but it needs a lossless video codec.
"""

from typing import Iterable, Iterator, Tuple

import numpy as np

from .. import header

DEFAULT_SIZE = (1280, 720)


def encode(buf: bytes, size: Tuple[int, int] = DEFAULT_SIZE) -> Iterator[np.ndarray]:
    width, height = size
    per_frame = width * height * 3
    for start in range(0, max(len(buf), 1), per_frame):
        chunk = buf[start:start + per_frame].ljust(per_frame, b"\0")
        yield np.frombuffer(chunk, dtype=np.uint8).reshape(height, width, 3)


def decode(frames: Iterable[np.ndarray]) -> bytes:
    buf = bytearray()
    total = None
    for frame in frames:
        buf += frame.tobytes()
        if total is None:
            total = header.total_length(buf)
        if total is not None and len(buf) >= total:
            break
    return bytes(buf)


def detect(frame: np.ndarray) -> bool:
    return header.looks_like_reel(frame.tobytes()[:4])
