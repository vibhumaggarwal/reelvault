import pytest

import reelvault


@pytest.mark.parametrize("robust,ext", [(False, ".avi"), (True, ".mp4")])
def test_inspect_reads_header_only(tmp_path, sample_file, robust, ext):
    out = reelvault.encode(sample_file, tmp_path / f"i{ext}", robust=robust, password="pw")
    info = reelvault.inspect(out)  # no password needed
    assert info.name == "notes.txt"
    assert info.size == sample_file.stat().st_size
    assert info.mode == ("robust" if robust else "lossless")
    assert info.encrypted and info.compressed and not info.is_folder
