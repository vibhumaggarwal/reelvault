import pytest

import reelvault


def test_folder_roundtrip(tmp_path):
    src = tmp_path / "project"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("alpha")
    (src / "sub" / "b.bin").write_bytes(bytes(range(256)))

    reel = reelvault.decode(reelvault.encode(src, tmp_path / "f.avi"))
    assert reel.is_folder and reel.name == "project"

    out = reel.save(tmp_path / "restored")
    assert (tmp_path / "restored" / "a.txt").read_text() == "alpha"
    assert (tmp_path / "restored" / "sub" / "b.bin").read_bytes() == bytes(range(256))


def test_save_file_uses_stored_name(tmp_path, sample_file, monkeypatch):
    reel = reelvault.decode(reelvault.encode(sample_file, tmp_path / "r.avi"))
    monkeypatch.chdir(tmp_path / "..")
    dest = tmp_path / "copy.txt"
    reel.save(dest)
    assert dest.read_bytes() == sample_file.read_bytes()


def test_save_refuses_to_overwrite(tmp_path, sample_file):
    reel = reelvault.decode(reelvault.encode(sample_file, tmp_path / "r.avi"))
    with pytest.raises(FileExistsError):
        reel.save(sample_file)
    reel.save(sample_file, overwrite=True)


def test_zip_slip_blocked(tmp_path):
    import io, zipfile
    from reelvault.api import Reel
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(ValueError):
        Reel("evil", buf.getvalue(), is_folder=True).save(tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()
