"""
Measure video size and speed for each mode.

    python scripts/benchmark.py [size_mb]

Uses random (incompressible) data, so sizes are worst-case; text and other
compressible files come out much smaller.
"""

import os
import sys
import tempfile
import time

import reelvault


def run(label, data, path, **kwargs):
    t = time.perf_counter()
    reelvault.encode(data, path, **kwargs)
    enc = time.perf_counter() - t
    t = time.perf_counter()
    assert reelvault.decode(path, password=kwargs.get("password")).data == data
    dec = time.perf_counter() - t
    size = os.path.getsize(path)
    print(f"| {label:<28} | {size / 1e6:>7.1f} MB | {size / len(data):>5.1f}x | {enc:>6.1f} s | {dec:>6.1f} s |")


def main():
    mb = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    data = os.urandom(int(mb * 1e6))
    print(f"{mb:g} MB of random data\n")
    print("| Mode                         |   Video    | Ratio | Encode | Decode |")
    print("|------------------------------|-----------:|------:|-------:|-------:|")
    with tempfile.TemporaryDirectory() as d:
        run("lossless .avi", data, f"{d}/a.avi")
        run("lossless .mkv", data, f"{d}/a.mkv")
        run("lossless .avi + password", data, f"{d}/p.avi", password="benchmark")
        run("robust .mp4", data, f"{d}/r.mp4", robust=True)
        run("robust .mp4, repeat=1", data, f"{d}/r1.mp4", robust=True, repeat=1)


if __name__ == "__main__":
    main()
