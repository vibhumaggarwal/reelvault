"""Public encode/decode functions."""

import os
from dataclasses import dataclass
from typing import Optional, Union

from . import packing, video
from .codecs import dense, robust as robust_codec
from .errors import NotAReelError, VideoIOError

Source = Union[str, bytes, bytearray, os.PathLike]


@dataclass
class Reel:
    """What came out of a video."""
    name: str
    data: bytes


def encode(source: Source, output: Union[str, os.PathLike], *, name: Optional[str] = None,
           robust: bool = False, compress: bool = True,
           fps: int = 30, block: int = 4, repeat: int = 2) -> str:
    """
    Store `source` in a video at `output` and return the output path.

    `source` is a path to a file, or the bytes themselves.

    robust=False packs 3 bytes per pixel and needs a lossless container
    (.avi or .mkv). robust=True draws black/white blocks that survive lossy
    codecs (.mp4, .webm), re-uploads and resizing, at roughly 3x the size.

    compress=True deflates the data first when that makes it smaller.
    """
    output = os.fspath(output)
    data, inferred = _read_source(source)
    name = inferred if name is None else name

    if not robust and not video.is_lossless(output):
        raise VideoIOError(
            f"{os.path.splitext(output)[1] or 'That container'} is lossy and would destroy the data. "
            "Use .avi/.mkv, or pass robust=True for .mp4/.webm."
        )

    buf = packing.pack(data, name, compress=compress)
    _ensure_parent(output)
    if robust:
        side = robust_codec.frame_size(block)
        video.write(output, robust_codec.encode(buf, block, repeat), (side, side), fps)
    else:
        video.write(output, dense.encode(buf), dense.DEFAULT_SIZE, fps)
    return output


def decode(path: Union[str, os.PathLike]) -> Reel:
    """Recover the file stored in a video."""
    frames = video.read(os.fspath(path))
    first = next(frames, None)
    if first is None:
        raise NotAReelError("The video has no frames")

    def all_frames():
        yield first
        yield from frames

    # The format is detected from the first frame, so callers never need to say which mode was used
    if dense.detect(first):
        buf = dense.decode(all_frames())
    elif robust_codec.detect(first):
        buf = robust_codec.decode(all_frames())
    else:
        raise NotAReelError("This video wasn't made by ReelVault, or is too damaged to recognise")

    hdr, data = packing.unpack(buf)
    return Reel(hdr.name, data)


def _read_source(source: Source):
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), ""
    path = os.fspath(source)
    with open(path, "rb") as f:
        return f.read(), os.path.basename(path)


def _ensure_parent(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
