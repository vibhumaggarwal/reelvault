"""
End-to-end tests of the web app in headless Chromium: record a reel in the
browser and decode it in Python, and decode a Python reel in the browser.

Needs `pip install playwright && playwright install chromium`; skipped otherwise.
"""

import os
import socket
import threading
import time

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

import reelvault  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config("reelvault.server:app", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(base_url):
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium not installed: {e}")
        page = browser.new_page(accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base_url)
        yield page
        assert not errors, errors
        browser.close()


def test_browser_encode_python_decode(page, tmp_path):
    data = os.urandom(30_000)  # ~15 frames
    src = tmp_path / "from browser.bin"
    src.write_bytes(data)

    page.click("#tab-encode")
    page.set_input_files("#encode-input", str(src))
    page.fill("#encode-password", "pw")
    with page.expect_download(timeout=120_000) as dl:
        page.click("#encode-go")
    out = tmp_path / dl.value.suggested_filename
    dl.value.save_as(out)

    reel = reelvault.decode(out, password="pw")
    assert reel.name == "from browser.bin"
    assert reel.data == data


def test_python_encode_browser_decode(page, tmp_path):
    data = os.urandom(30_000)
    # Playwright's Chromium has no H.264, so use WebM for this direction
    video = reelvault.encode(data, tmp_path / "py.webm", robust=True, name="from python.bin", password="pw")

    page.click("#tab-decode")
    page.set_input_files("#decode-input", video)
    page.fill("#decode-password", "pw")
    with page.expect_download(timeout=120_000) as dl:
        page.click("#decode-go")
    out = tmp_path / "out.bin"
    dl.value.save_as(out)

    assert dl.value.suggested_filename == "from python.bin"
    assert out.read_bytes() == data


def test_browser_reports_wrong_password(page, tmp_path):
    video = reelvault.encode(b"secret", tmp_path / "s.webm", robust=True, password="right")
    page.click("#tab-decode")
    page.click("#decode-clear")
    page.set_input_files("#decode-input", video)
    page.fill("#decode-password", "wrong")
    page.click("#decode-go")
    page.wait_for_function("document.querySelector('#decode-status').textContent.includes('failed')", timeout=60_000)
    assert "Wrong password" in page.inner_text("#toasts")
