# Changelog

## 1.0.0 (2026-03-31)

First release.

- Lossless mode: 3 bytes per pixel in PNG-in-AVI or FFV1 MKV, no size overhead.
- Robust mode: a 128×128 black-and-white grid with per-frame index and count. It survives H.264 re-encoding and resizing, and decodes by voting across repeated frames.
- Folders, filenames, deflate compression, and AES-256-GCM encryption with a PBKDF2-SHA256 key.
- `reelvault` CLI: `encode`, `decode`, `info` and `serve`.
- HTTP API and a browser app that is format-compatible with the Python package.
- Format spec in FORMAT.md.
