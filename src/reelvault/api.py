"""Public encode/decode functions."""

import os
from dataclasses import dataclass
from typing import Optional, Union

from . import header, video
from .codecs import dense
from .errors import NotAReelError, VideoIOError

Source = Union[str, bytes, bytearray, os.PathLike]


@dataclass
class Reel:
    """What came out of a video."""
    name: str
    data: bytes


def encode(source: Source, output: Union[str, os.PathLike], *, name: Optional[str] = None,
           fps: int = 30) -> str:
    """
    Store `source` in a video at `output` and return the output path.

    `source` is a path to a file, or the bytes themselves.
    """
    output = os.fspath(output)
    data, inferred = _read_source(source)
    name = inferred if name is None else name

    if not video.is_lossless(output):
        raise VideoIOError("Use a lossless container (.avi or .mkv)")

    buf = header.build(data, name)
    _ensure_parent(output)
    video.write(output, dense.encode(buf), dense.DEFAULT_SIZE, fps)
    return output


def decode(path: Union[str, os.PathLike]) -> Reel:
    """Recover the file stored in a video."""
    frames = video.read(os.fspath(path))
    first = next(frames, None)
    if first is None or not dense.detect(first):
        raise NotAReelError("This video wasn't made by ReelVault")

    def all_frames():
        yield first
        yield from frames

    hdr, payload = header.parse(dense.decode(all_frames()))
    return Reel(hdr.name, payload)


def _read_source(source: Source):
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), ""
    path = os.fspath(source)
    with open(path, "rb") as f:
        return f.read(), os.path.basename(path)


def _ensure_parent(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
