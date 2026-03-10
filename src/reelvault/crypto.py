"""
Password encryption: PBKDF2-HMAC-SHA256 key derivation + AES-256-GCM.

Both are available in the browser's WebCrypto API, so reels encrypted here can
be decrypted by the web app and vice versa. GCM's authentication tag also means
a wrong password is detected, not silently turned into garbage.
"""

import hashlib
import os

from .errors import PasswordError
from .header import CryptoParams

ITERATIONS = 600_000   # OWASP 2023 recommendation for PBKDF2-SHA256


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise PasswordError("Encryption needs the 'cryptography' package: pip install reelvault[crypto]") from e
    return AESGCM(key)


def encrypt(data: bytes, password: str):
    """Returns (ciphertext, CryptoParams)."""
    if not password:
        raise PasswordError("Password can't be empty")
    params = CryptoParams(salt=os.urandom(16), nonce=os.urandom(12), iterations=ITERATIONS)
    ct = _aesgcm(_key(password, params.salt, params.iterations)).encrypt(params.nonce, data, None)
    return ct, params


def decrypt(data: bytes, password: str, params: CryptoParams) -> bytes:
    if not password:
        raise PasswordError("This reel is encrypted; a password is required")
    from cryptography.exceptions import InvalidTag
    try:
        return _aesgcm(_key(password, params.salt, params.iterations)).decrypt(params.nonce, data, None)
    except InvalidTag:
        raise PasswordError("Wrong password") from None
