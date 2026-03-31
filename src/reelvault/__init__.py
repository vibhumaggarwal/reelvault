"""ReelVault: store any file inside a video and get it back byte-for-byte."""

__version__ = "1.0.0"

from .api import Reel, ReelInfo, decode, encode, inspect

__all__ = ["encode", "decode", "inspect", "Reel", "ReelInfo"]
