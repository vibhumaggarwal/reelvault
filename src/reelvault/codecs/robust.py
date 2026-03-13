"""
Robust codec: survives lossy compression (MP4/WebM, re-uploads, resizing).

Each frame is a 128x128 grid of black or white cells, one bit per cell, drawn
as `block`-pixel squares. Every frame starts with its own header:

    frame index   32 bits
    frame count   32 bits
    payload bits  16 bits

so frames can be dropped, repeated or reordered and the decoder still knows
exactly what it has and what's missing. The browser app uses the same layout.

Decoding averages each cell's brightness (after resizing the frame to the
grid, so scaled videos work) and lets every copy of a frame vote on each bit.
"""

from typing import Dict, Iterable, Iterator

import cv2
import numpy as np

from .. import header
from ..errors import CorruptReelError

GRID = 128
CELLS = GRID * GRID
INDEX_BITS = 32
COUNT_BITS = 32
LEN_BITS = 16
HEADER_BITS = INDEX_BITS + COUNT_BITS + LEN_BITS
PAYLOAD_BITS = CELLS - HEADER_BITS          # 16,304 bits per frame
MAX_FRAMES = 1 << 24                        # sanity limit for damaged headers


def frame_count(nbytes: int) -> int:
    return max(1, -(-nbytes * 8 // PAYLOAD_BITS))


def frame_size(block: int) -> int:
    return GRID * block


def _to_bits(value: int, width: int) -> np.ndarray:
    return np.array([(value >> (width - 1 - i)) & 1 for i in range(width)], np.uint8)


def _from_bits(bits) -> int:
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def encode(buf: bytes, block: int = 4, repeat: int = 2) -> Iterator[np.ndarray]:
    bits = np.unpackbits(np.frombuffer(buf, np.uint8))
    total = frame_count(len(buf))
    for idx in range(total):
        chunk = bits[idx * PAYLOAD_BITS:(idx + 1) * PAYLOAD_BITS]
        cells = np.zeros(CELLS, np.uint8)
        cells[:INDEX_BITS] = _to_bits(idx, INDEX_BITS)
        cells[INDEX_BITS:INDEX_BITS + COUNT_BITS] = _to_bits(total, COUNT_BITS)
        cells[INDEX_BITS + COUNT_BITS:HEADER_BITS] = _to_bits(len(chunk), LEN_BITS)
        cells[HEADER_BITS:HEADER_BITS + len(chunk)] = chunk

        img = np.repeat(np.repeat(cells.reshape(GRID, GRID) * 255, block, 0), block, 1)
        frame = np.ascontiguousarray(np.stack([img] * 3, -1))
        for _ in range(repeat):
            yield frame


def levels(frame: np.ndarray) -> np.ndarray:
    """Mean brightness of each cell, whatever the frame's resolution."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (GRID, GRID), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()


def read_frame_header(lv: np.ndarray):
    bits = lv[:HEADER_BITS] > 127
    return (_from_bits(bits[:INDEX_BITS]),
            _from_bits(bits[INDEX_BITS:INDEX_BITS + COUNT_BITS]),
            _from_bits(bits[INDEX_BITS + COUNT_BITS:]))


def decode(frames: Iterable[np.ndarray]) -> bytes:
    sums: Dict[int, np.ndarray] = {}
    seen: Dict[int, int] = {}
    counts: Dict[int, int] = {}

    for frame in frames:
        lv = levels(frame)
        idx, total, plen = read_frame_header(lv)
        if plen > PAYLOAD_BITS or total > MAX_FRAMES or idx >= total:
            continue  # damaged header
        counts[total] = counts.get(total, 0) + 1
        if idx in sums:
            sums[idx] += lv
            seen[idx] += 1
        else:
            sums[idx] = lv.copy()
            seen[idx] = 1

    if not sums:
        raise CorruptReelError("No readable frames")

    total = max(counts, key=counts.get)  # majority vote on the frame count
    missing = [i for i in range(total) if i not in sums]
    if missing:
        shown = ", ".join(map(str, missing[:8])) + ("…" if len(missing) > 8 else "")
        raise CorruptReelError(f"{len(missing)} of {total} frames are missing (index {shown})")

    parts = []
    for i in range(total):
        lv = sums[i] / seen[i]
        _, _, plen = read_frame_header(lv)
        parts.append(lv[HEADER_BITS:HEADER_BITS + plen] > 127)
    bits = np.concatenate(parts)
    return np.packbits(bits[: len(bits) // 8 * 8]).tobytes()


def detect(frame: np.ndarray) -> bool:
    lv = levels(frame)
    idx, total, plen = read_frame_header(lv)
    if idx != 0 or total == 0 or total > MAX_FRAMES or plen < 32:
        return False
    magic = np.packbits(lv[HEADER_BITS:HEADER_BITS + 32] > 127).tobytes()
    return header.looks_like_reel(magic)


def single_frame_bytes(frame: np.ndarray) -> bytes:
    """Payload bytes carried by one frame (enough to read the reel header from frame 0)."""
    lv = levels(frame)
    _, _, plen = read_frame_header(lv)
    bits = lv[HEADER_BITS:HEADER_BITS + min(plen, PAYLOAD_BITS)] > 127
    return np.packbits(bits[: len(bits) // 8 * 8]).tobytes()
