"""Exceptions raised by ReelVault."""


class ReelVaultError(Exception):
    """Base class for every ReelVault error."""


class NotAReelError(ReelVaultError):
    """The video wasn't made by ReelVault, or is too damaged to recognise."""


class CorruptReelError(ReelVaultError):
    """The video is a ReelVault reel, but the data inside is incomplete or damaged."""


class PasswordError(ReelVaultError):
    """The reel is encrypted and the password is missing or wrong."""


class VideoIOError(ReelVaultError):
    """A video file couldn't be written or read."""
