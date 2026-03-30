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


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    monkeypatch.delenv("REELVAULT_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)


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


def test_password_from_env(tmp_path, sample_file, monkeypatch):
    monkeypatch.setenv("REELVAULT_PASSWORD", "from-env")
    video = tmp_path / "v.avi"
    run("encode", sample_file, "-p", "-o", video)
    run("decode", video, "-o", tmp_path / "out.txt")
    assert (tmp_path / "out.txt").read_bytes() == sample_file.read_bytes()
    import reelvault
    assert reelvault.decode(video, password="from-env").data == sample_file.read_bytes()


def test_no_tty_without_env_fails_clearly(tmp_path, sample_file, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit, match="REELVAULT_PASSWORD"):
        run("encode", sample_file, "-p", "-o", tmp_path / "v.avi")
