# ReelVault

Store any file or folder inside a video and get it back byte-for-byte.

```bash
reelvault encode thesis.pdf --robust -p     # -> thesis.pdf.mp4, encrypted
reelvault decode thesis.pdf.mp4             # -> thesis.pdf, checksum verified
```

Each video carries the filename, the size and a CRC-32 checksum. A decode either returns exactly what went in or tells you what went wrong: wrong password, missing frames, or a damaged video.

## Two modes

| | **lossless** (default) | **robust** (`--robust`) |
|---|---|---|
| Container | `.avi` (PNG codec) or `.mkv` (FFV1) | `.mp4` (H.264) or `.webm` |
| Size (random data) | 1.0× the file | ~3.6× the file |
| Survives re-encoding, uploads, resizing | No | Yes |
| Decodes in the browser app | No | Yes |

Use **lossless** to package files as video with no overhead. Use **robust** when the video will go through something that re-compresses it, like a video host, a chat app or a screen recorder.

Robust reels are tested against:
- re-encoding at H.264 CRF 38;
- shrinking from 512 px to 320 px;
- videos with frames cut off, where the decoder reports exactly which frames are missing.

## Install

```bash
pip install -e ".[crypto,server]"   # from a checkout
```

The core needs only `numpy` and `opencv-python`. The extras add:
- **`crypto`:** password encryption;
- **`server`:** the web app and HTTP API.

## Command line

```bash
reelvault encode report.pdf               # report.pdf.avi
reelvault encode report.pdf --robust      # report.pdf.mp4
reelvault encode photos/ -p               # a whole folder, asks for a password
reelvault info report.pdf.mp4             # name, size, mode, encrypted? (no password needed)
reelvault decode report.pdf.mp4           # restores report.pdf (or the folder)
reelvault serve                           # web app + API on http://127.0.0.1:8000
```

## Python

```python
import reelvault

reelvault.encode("report.pdf", "report.mp4", robust=True, password="hunter2")

reel = reelvault.decode("report.mp4", password="hunter2")
reel.name, len(reel.data)      # ("report.pdf", 482113)
reel.save()                    # writes ./report.pdf (folders are extracted)

reelvault.inspect("report.mp4")
# ReelInfo(name='report.pdf', size=482113, stored_size=471002, mode='robust',
#          compressed=True, encrypted=True, is_folder=False)
```

`encode` and `decode` take a `progress=lambda done, total: ...` callback.

## Browser app

`reelvault serve` hosts a page that encodes and decodes robust reels entirely in the browser. Files never leave the tab. Videos made in the browser decode with the Python tool and the other way round, including encrypted ones. A test suite runs the browser code under Node to check this (`tests/test_web_compat.py`).

## HTTP API

| Method | Path | Form fields | Returns |
|---|---|---|---|
| POST | `/api/encode` | `file`, `robust`, `password` | the video |
| POST | `/api/decode` | `file`, `password` | the original file (folders as `.zip`) |
| POST | `/api/inspect` | `file` | JSON header info |
| GET | `/api/health` | | status |

Uploads are capped at 200 MB (`REELVAULT_MAX_UPLOAD_MB`). The API answers 401 for a missing or wrong password and 422 for videos that aren't readable reels.

## How it works

1. **Packing.** The file (or a zip of the folder) is compressed with deflate if that makes it smaller. It's then encrypted with AES-256-GCM if you gave a password, using a key from PBKDF2-SHA256 with 600k iterations. A header with the name, sizes and CRC-32 goes in front.
2. **Lossless frames.** The bytes are written straight into pixel colour channels, 3 bytes per pixel. A lossless codec keeps every value exact.
3. **Robust frames.** Each bit becomes a black or white 4×4 square on a 128×128 grid. Every frame starts with its index and the total frame count, and is written three times. When decoding:
   - frames are resized to the grid, so resolution doesn't matter;
   - each square's brightness is averaged, so blurry compression edges don't matter;
   - every copy of a frame votes on each bit.

The exact byte layout is in [FORMAT.md](FORMAT.md).

## Benchmarks

10 MB of random data on an M-series MacBook (`python scripts/benchmark.py 10`):

| Mode | Video | Ratio | Encode | Decode |
|---|---:|---:|---:|---:|
| lossless .avi | 10.0 MB | 1.0× | 0.3 s | 0.1 s |
| lossless .mkv | 11.1 MB | 1.1× | 0.4 s | 0.2 s |
| lossless .avi + password | 10.0 MB | 1.0× | 0.4 s | 0.1 s |
| robust .mp4 | 35.7 MB | 3.6× | 15.0 s | 3.5 s |

Random data is the worst case. Text, code and other compressible files come out much smaller, because they're deflated first.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

The ffmpeg re-encoding tests need `ffmpeg`, and the browser compatibility tests need `node`. Both are skipped if missing.

## License

MIT
