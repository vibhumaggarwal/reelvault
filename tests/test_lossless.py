import pytest

import reelvault
from reelvault.errors import NotAReelError, VideoIOError


@pytest.mark.parametrize("ext", [".avi", ".mkv"])
def test_bytes_roundtrip(tmp_path, blob, ext):
    out = reelvault.encode(blob, tmp_path / f"reel{ext}")
    assert reelvault.decode(out).data == blob


def test_file_keeps_its_name(tmp_path, sample_file):
    reel = reelvault.decode(reelvault.encode(sample_file, tmp_path / "reel.avi"))
    assert reel.name == "notes.txt"
    assert reel.data == sample_file.read_bytes()


def test_empty_file(tmp_path):
    assert reelvault.decode(reelvault.encode(b"", tmp_path / "e.avi")).data == b""


def test_multi_frame(tmp_path):
    data = bytes(range(256)) * 20_000  # > one 1280x720 frame
    assert reelvault.decode(reelvault.encode(data, tmp_path / "m.avi")).data == data


def test_rejects_lossy_container_without_robust(tmp_path):
    with pytest.raises(VideoIOError):
        reelvault.encode(b"x", tmp_path / "x.mp4")


def test_rejects_other_videos(tmp_path):
    import cv2
    import numpy as np
    path = str(tmp_path / "plain.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"png "), 30, (64, 64))
    w.write(np.full((64, 64, 3), 120, np.uint8))
    w.release()
    with pytest.raises(NotAReelError):
        reelvault.decode(path)


def test_compression_shrinks_text(tmp_path):
    from reelvault import header, packing
    text = b"the same line again and again\n" * 50_000
    hdr, _ = header.parse(packing.pack(text, "t"))
    assert hdr.compressed and hdr.payload_len < len(text) / 50
    for compress in (True, False):
        out = reelvault.encode(text, tmp_path / f"{compress}.avi", compress=compress)
        assert reelvault.decode(out).data == text


def test_incompressible_data_is_stored_as_is(tmp_path, blob):
    from reelvault import header, packing
    hdr, _ = header.parse(packing.pack(blob, "x"))
    assert not hdr.compressed


def test_progress_callback(tmp_path):
    calls = []
    data = bytes(range(256)) * 20_000
    out = reelvault.encode(data, tmp_path / "p.avi", compress=False, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (2, 2)
    seen = []
    reelvault.decode(out, progress=lambda d, t: seen.append(d))
    assert seen and seen[0] == 1
