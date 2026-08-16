"""安全单测：上传文件名穿越清洗、文件类型/大小校验（对应 CODE_REVIEW P1-1/3）。"""

import os

from fastapi.testclient import TestClient
from main import UPLOAD_DIR, app


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n x"


def test_path_traversal_sanitized():
    """恶意文件名 ../../evil.png 必须被清洗为 uploads/ 内的安全文件名，不能越界。"""
    with TestClient(app) as c:
        files = {
            "returned_image": ("../../evil.png", _png(), "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"})
        assert r.status_code == 200
        saved = [f for f in os.listdir(UPLOAD_DIR) if "evil" in f]
        assert saved, "清洗后的 evil 文件应已落盘"
        assert all("/" not in f and "\\" not in f for f in saved)
        # 确证未写到 UPLOAD_DIR 之外
        assert not os.path.exists(os.path.join(UPLOAD_DIR, "..", "evil.png"))


def test_reject_non_image():
    with TestClient(app) as c:
        files = {
            "returned_image": ("x.txt", b"hello not an image", "text/plain"),
            "product_image": ("y.txt", b"hello", "text/plain"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"})
        assert r.status_code == 400


def test_reject_oversize():
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024)
    with TestClient(app) as c:
        files = {
            "returned_image": ("big.png", big, "image/png"),
            "product_image": ("prod.png", _png(), "image/png"),
        }
        r = c.post("/api/analyze", files=files, data={"mode": "mock"})
        assert r.status_code == 413
