import pytest

import reelvault
from reelvault.errors import PasswordError


@pytest.mark.parametrize("robust,ext", [(False, ".avi"), (True, ".mp4")])
def test_encrypted_roundtrip(tmp_path, sample_file, robust, ext):
    out = reelvault.encode(sample_file, tmp_path / f"e{ext}", password="correct horse", robust=robust)
    reel = reelvault.decode(out, password="correct horse")
    assert reel.data == sample_file.read_bytes()
    assert reel.name == "notes.txt"


def test_wrong_password(tmp_path, blob):
    out = reelvault.encode(blob, tmp_path / "e.avi", password="right")
    with pytest.raises(PasswordError, match="Wrong"):
        reelvault.decode(out, password="wrong")


def test_missing_password(tmp_path, blob):
    out = reelvault.encode(blob, tmp_path / "e.avi", password="right")
    with pytest.raises(PasswordError, match="required"):
        reelvault.decode(out)


def test_ciphertext_hides_content(tmp_path):
    from reelvault import packing
    secret = b"very secret text " * 100
    assert b"very secret" not in packing.pack(secret, "s", password="pw", compress=False)


def test_empty_password_rejected(tmp_path):
    with pytest.raises(PasswordError):
        reelvault.encode(b"x", tmp_path / "e.avi", password="")
