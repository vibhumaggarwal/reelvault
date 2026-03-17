"""
HTTP API.

    POST /api/encode   form: file, robust (bool), password (optional)  -> video
    POST /api/decode   form: file (video), password (optional)         -> original file
    POST /api/inspect  form: file (video)                              -> JSON header info
    GET  /api/health

Run with `reelvault serve` or `uvicorn reelvault.server:app`.
"""

import os
import tempfile
import uuid
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from . import __version__, decode, encode, inspect
from .errors import NotAReelError, CorruptReelError, PasswordError, ReelVaultError, VideoIOError

MAX_UPLOAD = int(os.getenv("REELVAULT_MAX_UPLOAD_MB", "200")) * 1024 * 1024
WORK_DIR = os.path.join(tempfile.gettempdir(), "reelvault")
os.makedirs(WORK_DIR, exist_ok=True)

app = FastAPI(title="ReelVault", version=__version__)


def _save_upload(file: UploadFile, suffix: str) -> str:
    path = os.path.join(WORK_DIR, uuid.uuid4().hex + suffix)
    size = 0
    with open(path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                os.remove(path)
                raise HTTPException(413, f"Upload is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
            out.write(chunk)
    return path


def _remove(*paths: str):
    for p in paths:
        if p and os.path.exists(p):
            os.remove(p)


def _attachment(name: str) -> dict:
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}


def _video_suffix(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    return ext if ext in {".avi", ".mkv", ".mp4", ".webm"} else ".avi"


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


# Plain `def` routes run in a worker thread, so long encodes don't block the server
@app.post("/api/encode")
def api_encode(file: UploadFile = File(...), robust: bool = Form(False),
               password: Optional[str] = Form(None)):
    src = _save_upload(file, "")
    ext = ".mp4" if robust else ".avi"
    out = os.path.join(WORK_DIR, uuid.uuid4().hex + ext)
    try:
        encode(src, out, name=file.filename or "file", robust=robust, password=password or None)
    except PasswordError as e:
        _remove(out)
        raise HTTPException(400, str(e))
    except ReelVaultError as e:
        _remove(out)
        raise HTTPException(500, str(e))
    finally:
        _remove(src)
    return FileResponse(out, media_type="video/mp4" if robust else "video/x-msvideo",
                        headers=_attachment(f"{file.filename or 'file'}{ext}"),
                        background=BackgroundTask(_remove, out))


@app.post("/api/decode")
def api_decode(file: UploadFile = File(...), password: Optional[str] = Form(None)):
    src = _save_upload(file, _video_suffix(file))
    try:
        reel = decode(src, password=password or None)
    except PasswordError as e:
        raise HTTPException(401, str(e))
    except (NotAReelError, CorruptReelError, VideoIOError) as e:
        raise HTTPException(422, str(e))
    finally:
        _remove(src)

    name = reel.name or "reel_output"
    if reel.is_folder:
        return Response(reel.data, media_type="application/zip", headers=_attachment(name + ".zip"))
    return Response(reel.data, media_type="application/octet-stream", headers=_attachment(name))


@app.post("/api/inspect")
def api_inspect(file: UploadFile = File(...)):
    src = _save_upload(file, _video_suffix(file))
    try:
        return inspect(src).__dict__
    except (NotAReelError, CorruptReelError, VideoIOError) as e:
        raise HTTPException(422, str(e))
    finally:
        _remove(src)
