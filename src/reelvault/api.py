"""Public encode/decode functions."""

import io
import os
import zipfile
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Optional, Union

from . import header, packing, video
from .codecs import dense, robust as robust_codec
from .errors import NotAReelError, VideoIOError

Source = Union[str, bytes, bytearray, os.PathLike]
Progress = Optional[Callable[[int, int], None]]   # (frames_done, frames_total)


def _track(frames: Iterable, total: int, progress: Progress) -> Iterator:
    if progress is None:
        yield from frames
        return
    done = 0
    for frame in frames:
        yield frame
        done += 1
        progress(done, max(total, done))


@dataclass
class Reel:
    """What came out of a video."""
    name: str
    data: bytes
    is_folder: bool = False

    def save(self, dest: Optional[Union[str, os.PathLike]] = None, overwrite: bool = False) -> str:
        """
        Write the file (or extract the folder) to `dest`, defaulting to the
        stored name in the current directory. Returns the path written.
        """
        dest = os.fspath(dest) if dest is not None else (self.name or "reel_output")
        if os.path.exists(dest) and not overwrite:
            raise FileExistsError(f"{dest} already exists")
        if self.is_folder:
            with zipfile.ZipFile(io.BytesIO(self.data)) as zf:
                _safe_extract(zf, dest)
        else:
            with open(dest, "wb") as f:
                f.write(self.data)
        return dest


def encode(source: Source, output: Union[str, os.PathLike], *, name: Optional[str] = None,
           robust: bool = False, compress: bool = True, password: Optional[str] = None,
           fps: int = 30, block: int = 4, repeat: int = 2, progress: Progress = None) -> str:
    """
    Store `source` in a video at `output` and return the output path.

    `source` is a path to a file or folder, or the bytes themselves.
    Folders are zipped and restored as folders by Reel.save().

    robust=False packs 3 bytes per pixel and needs a lossless container
    (.avi or .mkv). robust=True draws black/white blocks that survive lossy
    codecs (.mp4, .webm), re-uploads and resizing, at roughly 3x the size.

    compress=True deflates the data first when that makes it smaller.
    password encrypts it with AES-256-GCM; the filename stays readable.
    progress, if given, is called as progress(frames_done, frames_total).
    """
    output = os.fspath(output)
    data, inferred, is_folder = _read_source(source)
    name = inferred if name is None else name

    if not robust and not video.is_lossless(output):
        raise VideoIOError(
            f"{os.path.splitext(output)[1] or 'That container'} is lossy and would destroy the data. "
            "Use .avi/.mkv, or pass robust=True for .mp4/.webm."
        )

    flags = header.FLAG_FOLDER if is_folder else 0
    buf = packing.pack(data, name, compress=compress, password=password, flags=flags)
    _ensure_parent(output)
    if robust:
        side = robust_codec.frame_size(block)
        total = robust_codec.frame_count(len(buf)) * repeat
        video.write(output, _track(robust_codec.encode(buf, block, repeat), total, progress), (side, side), fps)
    else:
        w, h = dense.DEFAULT_SIZE
        total = max(1, -(-len(buf) // (w * h * 3)))
        video.write(output, _track(dense.encode(buf), total, progress), dense.DEFAULT_SIZE, fps)
    return output


def decode(path: Union[str, os.PathLike], password: Optional[str] = None,
           progress: Progress = None) -> Reel:
    """Recover the file stored in a video. Pass `password` for encrypted reels."""
    path = os.fspath(path)
    frames = _track(video.read(path), video.frame_count(path), progress)
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

    hdr, data = packing.unpack(buf, password)
    return Reel(hdr.name, data, hdr.folder)


@dataclass
class ReelInfo:
    """What a reel contains, read from its header without decoding the data."""
    name: str
    size: int            # original size in bytes
    stored_size: int     # bytes actually stored (after compression/encryption)
    mode: str            # "lossless" or "robust"
    compressed: bool
    encrypted: bool
    is_folder: bool


def inspect(path: Union[str, os.PathLike]) -> ReelInfo:
    """Read a reel's header from its first frame. Works without the password."""
    first = next(video.read(os.fspath(path)), None)
    if first is None:
        raise NotAReelError("The video has no frames")
    if dense.detect(first):
        mode, buf = "lossless", first.tobytes()
    elif robust_codec.detect(first):
        mode, buf = "robust", robust_codec.single_frame_bytes(first)
    else:
        raise NotAReelError("This video wasn't made by ReelVault, or is too damaged to recognise")

    hdr, _ = header.parse(buf, check_payload=False)
    return ReelInfo(hdr.name, hdr.orig_size, hdr.payload_len, mode,
                    hdr.compressed, hdr.encrypted, hdr.folder)


def _read_source(source: Source):
    """Returns (bytes, name, is_folder)."""
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), "", False
    path = os.fspath(source)
    if os.path.isdir(path):
        return _zip_folder(path), os.path.basename(os.path.normpath(path)), True
    with open(path, "rb") as f:
        return f.read(), os.path.basename(path), False


def _zip_folder(path: str) -> bytes:
    buf = io.BytesIO()
    # Stored, not deflated: the whole zip gets compressed afterwards anyway
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for fname in sorted(files):
                full = os.path.join(root, fname)
                zf.write(full, os.path.relpath(full, path))
    return buf.getvalue()


def _safe_extract(zf: zipfile.ZipFile, dest: str):
    """Extract without letting entries escape `dest` (zip-slip)."""
    root = os.path.realpath(dest)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(root, member))
        if target != root and not target.startswith(root + os.sep):
            raise ValueError(f"Unsafe path in archive: {member}")
    zf.extractall(root)


def _ensure_parent(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
