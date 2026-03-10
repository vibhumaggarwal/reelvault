"""
Turning a file into the payload that goes in the reel, and back.

Order on the way in: (folder -> zip) -> compress -> encrypt.
"""

import zlib
from typing import Optional, Tuple

from . import crypto, header
from .errors import CorruptReelError


def _deflate(data: bytes) -> bytes:
    # Raw deflate (no zlib wrapper) so browsers can inflate it with DecompressionStream("deflate-raw")
    c = zlib.compressobj(level=9, wbits=-15)
    return c.compress(data) + c.flush()


def _inflate(data: bytes, expected: int) -> bytes:
    try:
        out = zlib.decompress(data, wbits=-15)
    except zlib.error as e:
        raise CorruptReelError(f"Compressed data is damaged: {e}") from e
    if len(out) != expected:
        raise CorruptReelError("Decompressed size doesn't match the header")
    return out


def pack(data: bytes, name: str, *, compress: bool = True, password: Optional[str] = None,
         flags: int = 0) -> bytes:
    """Build the full reel buffer (header + payload)."""
    payload = data
    if compress:
        squeezed = _deflate(data)
        # Only keep compression when it actually helps (already-compressed files often grow)
        if len(squeezed) < len(data):
            payload = squeezed
            flags |= header.FLAG_DEFLATE
    params = None
    if password is not None:
        payload, params = crypto.encrypt(payload, password)
        flags |= header.FLAG_ENCRYPTED
    return header.build(payload, name, orig_size=len(data), flags=flags, crypto=params)


def unpack(buf: bytes, password: Optional[str] = None) -> Tuple[header.Header, bytes]:
    """Validate a reel buffer and return (header, original bytes)."""
    hdr, payload = header.parse(buf)
    if hdr.encrypted:
        payload = crypto.decrypt(payload, password, hdr.crypto)
    if hdr.compressed:
        payload = _inflate(payload, hdr.orig_size)
    return hdr, payload
