"""
The header written in front of every payload.

    magic        4   b"RVLT"
    version      1   format version (1)
    flags        1   FLAG_* bits below
    name_len     2   length of the UTF-8 filename
    name         n
    orig_size    8   size of the original file
    payload_len  8   size of the payload as stored (after compression/encryption)
    crc32        4   CRC32 of the stored payload
    [salt 16 | nonce 12 | iterations 4]   only when FLAG_ENCRYPTED is set
    payload

Integers are big-endian.
"""

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

from .errors import CorruptReelError, NotAReelError

MAGIC = b"RVLT"
VERSION = 1

FLAG_DEFLATE = 0x01     # payload is raw-deflate compressed
FLAG_ENCRYPTED = 0x02   # payload is AES-256-GCM encrypted
FLAG_FOLDER = 0x04      # original was a folder, stored as a zip

_FIXED = struct.Struct(">4sBBH")          # magic, version, flags, name_len
_SIZES = struct.Struct(">QQI")            # orig_size, payload_len, crc32
_CRYPTO = struct.Struct(">16s12sI")       # salt, nonce, iterations
MAX_NAME_BYTES = 1024


@dataclass
class CryptoParams:
    salt: bytes
    nonce: bytes
    iterations: int


@dataclass
class Header:
    name: str
    orig_size: int
    payload_len: int
    crc32: int
    flags: int = 0
    crypto: Optional[CryptoParams] = None

    @property
    def compressed(self) -> bool:
        return bool(self.flags & FLAG_DEFLATE)

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)

    @property
    def folder(self) -> bool:
        return bool(self.flags & FLAG_FOLDER)


def _clip_name(name: str) -> bytes:
    raw = name.encode("utf-8")[:MAX_NAME_BYTES]
    return raw.decode("utf-8", "ignore").encode("utf-8")


def build(payload: bytes, name: str = "", orig_size: Optional[int] = None,
          flags: int = 0, crypto: Optional[CryptoParams] = None) -> bytes:
    """Header + payload, ready to be turned into frames."""
    if bool(flags & FLAG_ENCRYPTED) != (crypto is not None):
        raise ValueError("crypto params must be given exactly when FLAG_ENCRYPTED is set")
    nb = _clip_name(name)
    parts = [
        _FIXED.pack(MAGIC, VERSION, flags, len(nb)),
        nb,
        _SIZES.pack(len(payload) if orig_size is None else orig_size, len(payload), zlib.crc32(payload)),
    ]
    if crypto:
        parts.append(_CRYPTO.pack(crypto.salt, crypto.nonce, crypto.iterations))
    parts.append(payload)
    return b"".join(parts)


def header_length(buf: bytes) -> Optional[int]:
    """Length of the header, or None if `buf` is too short to know yet."""
    if len(buf) < _FIXED.size:
        return None
    _, _, flags, name_len = _FIXED.unpack_from(buf)
    n = _FIXED.size + name_len + _SIZES.size
    if flags & FLAG_ENCRYPTED:
        n += _CRYPTO.size
    return n


def total_length(buf: bytes) -> Optional[int]:
    """Header + payload length, or None if the header isn't complete yet."""
    n = header_length(buf)
    if n is None or len(buf) < n:
        return None
    return n + parse(buf[:n], check_payload=False)[0].payload_len


def looks_like_reel(buf: bytes) -> bool:
    return buf[:4] == MAGIC


def parse(buf: bytes, check_payload: bool = True):
    """Split `buf` into (Header, payload). Validates the checksum unless told not to."""
    if not looks_like_reel(buf):
        raise NotAReelError("Not a ReelVault stream")
    n = header_length(buf)
    if n is None or len(buf) < n:
        raise CorruptReelError("Video ended inside the header")

    _, version, flags, name_len = _FIXED.unpack_from(buf)
    if version != VERSION:
        raise NotAReelError(f"Made by a newer ReelVault (format v{version}); please upgrade")
    pos = _FIXED.size
    name = buf[pos:pos + name_len].decode("utf-8", "replace")
    pos += name_len
    orig_size, payload_len, crc = _SIZES.unpack_from(buf, pos)
    pos += _SIZES.size
    crypto = None
    if flags & FLAG_ENCRYPTED:
        crypto = CryptoParams(*_CRYPTO.unpack_from(buf, pos))
        pos += _CRYPTO.size

    header = Header(name, orig_size, payload_len, crc, flags, crypto)
    if not check_payload:
        return header, b""

    payload = bytes(buf[pos:pos + payload_len])
    if len(payload) < payload_len:
        raise CorruptReelError("Video ended before all data was recovered")
    if zlib.crc32(payload) != crc:
        raise CorruptReelError("Checksum mismatch: the video is damaged or was compressed too hard")
    return header, payload
