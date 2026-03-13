"""
reelvault encode report.pdf               -> report.pdf.avi   (lossless)
reelvault encode report.pdf --robust      -> report.pdf.mp4   (survives re-uploads)
reelvault encode photos/ -p               -> photos.avi       (folder, asks for a password)
reelvault decode report.pdf.mp4           -> report.pdf
reelvault info report.pdf.mp4
"""

import argparse
import getpass
import os
import sys

from . import __version__, decode, encode, inspect
from .errors import PasswordError, ReelVaultError


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _ask_password(confirm: bool) -> str:
    pw = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        sys.exit("error: passwords don't match")
    return pw


def cmd_encode(args):
    src = os.path.normpath(args.input)
    ext = ".mp4" if args.robust else ".avi"
    out = args.output or os.path.basename(src) + ext
    if os.path.exists(out) and not args.force:
        sys.exit(f"error: {out} already exists (use -o or -f)")
    password = _ask_password(confirm=True) if args.password else None

    encode(src, out, robust=args.robust, compress=not args.no_compress, password=password, fps=args.fps)
    info = inspect(out)
    print(f"{src} -> {out}")
    print(f"  {_size(info.size)} stored as a {_size(os.path.getsize(out))} {info.mode} video"
          + (", encrypted" if info.encrypted else ""))


def cmd_decode(args):
    info = inspect(args.video)
    password = _ask_password(confirm=False) if info.encrypted else None
    reel = decode(args.video, password=password)
    dest = reel.save(args.output, overwrite=args.force)
    kind = "folder" if reel.is_folder else "file"
    print(f"{args.video} -> {dest} ({kind}, {_size(len(reel.data))}, checksum OK)")


def cmd_info(args):
    info = inspect(args.video)
    rows = [
        ("Name", info.name or "(none)"),
        ("Type", "folder" if info.is_folder else "file"),
        ("Size", _size(info.size)),
        ("Stored", f"{_size(info.stored_size)}" + (" (compressed)" if info.compressed else "")),
        ("Mode", info.mode),
        ("Encrypted", "yes" if info.encrypted else "no"),
    ]
    for k, v in rows:
        print(f"{k + ':':<11}{v}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="reelvault", description="Store any file inside a video and get it back.")
    p.add_argument("--version", action="version", version=f"reelvault {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("encode", help="store a file or folder in a video")
    e.add_argument("input")
    e.add_argument("-o", "--output", help="video path (.avi/.mkv lossless, .mp4/.webm with --robust)")
    e.add_argument("--robust", action="store_true", help="survive compression and re-uploads (~3x larger)")
    e.add_argument("-p", "--password", action="store_true", help="encrypt; you'll be asked for a password")
    e.add_argument("--no-compress", action="store_true", help="skip deflate compression")
    e.add_argument("--fps", type=int, default=30)
    e.add_argument("-f", "--force", action="store_true", help="overwrite the output")
    e.set_defaults(func=cmd_encode)

    d = sub.add_parser("decode", help="get the file or folder back")
    d.add_argument("video")
    d.add_argument("-o", "--output", help="where to save (default: the stored name)")
    d.add_argument("-f", "--force", action="store_true", help="overwrite an existing file")
    d.set_defaults(func=cmd_decode)

    i = sub.add_parser("info", help="show what a video contains")
    i.add_argument("video")
    i.set_defaults(func=cmd_info)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except (ReelVaultError, FileNotFoundError, FileExistsError) as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
