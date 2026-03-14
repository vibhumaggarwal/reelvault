"""Reading and writing video files with OpenCV."""

import os
from typing import Iterable, Iterator, List, Tuple

import cv2
import numpy as np

from .errors import VideoIOError

# Lossless codecs keep every pixel value exact; lossy ones need robust mode.
LOSSLESS = {".avi": ["png "], ".mkv": ["FFV1"]}
LOSSY = {".mp4": ["avc1", "mp4v"], ".webm": ["VP80"]}


def is_lossless(path: str) -> bool:
    return _ext(path) in LOSSLESS


def codecs_for(path: str) -> List[str]:
    ext = _ext(path)
    if ext in LOSSLESS:
        return LOSSLESS[ext]
    if ext in LOSSY:
        return LOSSY[ext]
    raise VideoIOError(f"Unsupported video type {ext or '(none)'}; use .avi, .mkv, .mp4 or .webm")


def write(path: str, frames: Iterable[np.ndarray], size: Tuple[int, int], fps: int = 30) -> int:
    """Write BGR frames to `path`. Returns the number of frames written."""
    writer = None
    tried = codecs_for(path)
    for fourcc in tried:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if writer.isOpened():
            break
        writer.release()
        writer = None
    if writer is None:
        raise VideoIOError(f"No working codec for {path} (tried {', '.join(t.strip() for t in tried)})")

    count = 0
    try:
        for frame in frames:
            writer.write(frame)
            count += 1
    finally:
        writer.release()

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise VideoIOError(f"{path} was not created")
    return count


def read(path: str) -> Iterator[np.ndarray]:
    """Yield BGR frames one at a time."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoIOError(f"Couldn't open {path} as a video")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def frame_count(path: str) -> int:
    """Frame count from the container's metadata (may be 0 if unknown)."""
    cap = cv2.VideoCapture(path)
    try:
        return max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        cap.release()


def _ext(path: str) -> str:
    return os.path.splitext(os.fspath(path))[1].lower()
