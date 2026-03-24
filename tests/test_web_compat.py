"""The browser app and the Python package must read each other's reels."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import reelvault
from reelvault import packing, video
from reelvault.codecs import robust

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "js" / "harness.mjs"
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def node(*args):
    return subprocess.run([NODE, str(HARNESS), *map(str, args)], check=True, capture_output=True, text=True).stdout


@pytest.mark.parametrize("password", ["-", "hunter2"])
def test_python_decodes_browser_frames(tmp_path, blob, password):
    src = tmp_path / "in.bin"
    src.write_bytes(blob)
    cells_path = tmp_path / "cells"
    node("build", src, "from browser ✓.bin", password, cells_path)

    # Draw the browser's cell grids exactly as the canvas does, then encode them as a real MP4
    cells = np.frombuffer(cells_path.read_bytes(), np.uint8).reshape(-1, robust.GRID, robust.GRID)
    frames = (np.stack([np.repeat(np.repeat(c * 255, 4, 0), 4, 1)] * 3, -1) for c in cells)
    mp4 = str(tmp_path / "browser.mp4")
    video.write(mp4, frames, (512, 512))

    reel = reelvault.decode(mp4, password=None if password == "-" else password)
    assert reel.name == "from browser ✓.bin"
    assert reel.data == blob


def test_browser_opens_python_reels(tmp_path):
    data = b"made in python " * 1000
    buf = tmp_path / "reel.bin"
    buf.write_bytes(packing.pack(data, "py ✓.txt", password="pw"))
    out = tmp_path / "out"
    assert node("open", buf, "pw", out).strip() == "py ✓.txt"
    assert out.read_bytes() == data


def test_browser_rejects_wrong_password(tmp_path):
    buf = tmp_path / "reel.bin"
    buf.write_bytes(packing.pack(b"secret", "s", password="pw"))
    with pytest.raises(subprocess.CalledProcessError) as e:
        node("open", buf, "nope", tmp_path / "out")
    assert "Wrong password" in e.value.stderr
