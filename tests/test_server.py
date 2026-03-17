import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from reelvault.server import app  # noqa: E402

client = TestClient(app)
DATA = b"hello from the api test\n" * 500


def _encode(robust=False, password=None):
    form = {"robust": str(robust).lower()}
    if password:
        form["password"] = password
    r = client.post("/api/encode", files={"file": ("ünïcode name.txt", DATA)}, data=form)
    assert r.status_code == 200, r.text
    return r.content


@pytest.mark.parametrize("robust,ext", [(False, "avi"), (True, "mp4")])
def test_roundtrip(robust, ext):
    video = _encode(robust)
    r = client.post("/api/decode", files={"file": (f"v.{ext}", video)})
    assert r.status_code == 200
    assert r.content == DATA
    assert "%C3%BCn%C3%AFcode%20name.txt" in r.headers["content-disposition"]


def test_password_flow():
    video = _encode(password="pw")
    assert client.post("/api/decode", files={"file": ("v.avi", video)}).status_code == 401
    assert client.post("/api/decode", files={"file": ("v.avi", video)}, data={"password": "nope"}).status_code == 401
    r = client.post("/api/decode", files={"file": ("v.avi", video)}, data={"password": "pw"})
    assert r.content == DATA


def test_inspect():
    r = client.post("/api/inspect", files={"file": ("v.avi", _encode(password="pw"))})
    info = r.json()
    assert info["name"] == "ünïcode name.txt" and info["encrypted"] is True


def test_garbage_upload_is_422():
    r = client.post("/api/decode", files={"file": ("v.avi", b"not a video at all")})
    assert r.status_code == 422


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"
