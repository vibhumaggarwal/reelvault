import pytest

from reelvault.cli import main


def run(*args):
    main([str(a) for a in args])


def test_encode_decode(tmp_path, sample_file, capsys):
    video = tmp_path / "v.avi"
    run("encode", sample_file, "-o", video)
    run("decode", video, "-o", tmp_path / "out.txt")
    assert (tmp_path / "out.txt").read_bytes() == sample_file.read_bytes()
    assert "checksum OK" in capsys.readouterr().out


def test_password_prompt(tmp_path, sample_file, monkeypatch):
    answers = iter(["s3cret", "s3cret", "s3cret"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    video = tmp_path / "v.mp4"
    run("encode", sample_file, "--robust", "-p", "-o", video)
    run("decode", video, "-o", tmp_path / "out.txt")
    assert (tmp_path / "out.txt").read_bytes() == sample_file.read_bytes()


def test_wrong_password_exits_cleanly(tmp_path, sample_file, monkeypatch):
    answers = iter(["right", "right", "wrong"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    video = tmp_path / "v.avi"
    run("encode", sample_file, "-p", "-o", video)
    with pytest.raises(SystemExit, match="Wrong password"):
        run("decode", video, "-o", tmp_path / "out.txt")


def test_info(tmp_path, sample_file, capsys):
    video = tmp_path / "v.avi"
    run("encode", sample_file, "-o", video)
    capsys.readouterr()
    run("info", video)
    out = capsys.readouterr().out
    assert "notes.txt" in out and "lossless" in out


def test_refuses_overwrite(tmp_path, sample_file):
    video = tmp_path / "v.avi"
    run("encode", sample_file, "-o", video)
    with pytest.raises(SystemExit, match="already exists"):
        run("encode", sample_file, "-o", video)
