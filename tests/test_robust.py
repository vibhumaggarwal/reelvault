import os
import shutil
import subprocess

import pytest

import reelvault


@pytest.mark.parametrize("ext", [".mp4", ".avi"])
def test_robust_roundtrip(tmp_path, blob, ext):
    out = reelvault.encode(blob, tmp_path / f"r{ext}", robust=True)
    assert reelvault.decode(out).data == blob


def test_name_survives(tmp_path, sample_file):
    reel = reelvault.decode(reelvault.encode(sample_file, tmp_path / "r.mp4", robust=True))
    assert reel.name == "notes.txt"


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@needs_ffmpeg
@pytest.mark.parametrize("args", [
    ["-crf", "38"],                          # heavy compression
    ["-vf", "scale=320:320", "-crf", "28"],  # shrunk, like a re-upload
])
def test_survives_lossy_reencode(tmp_path, blob, args):
    src = reelvault.encode(blob, tmp_path / "r.mp4", robust=True)
    reup = tmp_path / "reupload.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, *args, "-c:v", "libx264", str(reup)],
                   check=True)
    assert reelvault.decode(reup).data == blob


@needs_ffmpeg
def test_reports_missing_frames(tmp_path):
    from reelvault.errors import CorruptReelError
    data = os.urandom(8000)  # incompressible, so it spans 4 frames
    src = reelvault.encode(data, tmp_path / "r.mp4", robust=True, repeat=1)
    cut = tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-frames:v", "2", "-c:v", "libx264", str(cut)],
                   check=True)
    with pytest.raises(CorruptReelError, match="missing"):
        reelvault.decode(cut)
