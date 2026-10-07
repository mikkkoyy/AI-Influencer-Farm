"""Tests for image generation dashboard API endpoints."""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dashboard.app import app
from core.db import init_db
from config.settings import settings


def _make_minimal_png() -> bytes:
    buf = BytesIO()
    img = Image.new("RGB", (1, 1), color="red")
    img.save(buf, format="PNG")
    return buf.getvalue()


_MINIMAL_PNG = _make_minimal_png()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("storage") / "viralstack.db"
    settings.db_path = str(db_path)
    init_db()
    return TestClient(app)


def test_list_image_backends(client):
    response = client.get("/api/image-generation/backends")
    assert response.status_code == 200
    data = response.json()
    assert "backends" in data
    assert len(data["backends"]) == 2


def test_detect_backends(client):
    response = client.get("/api/image-generation/detect")
    assert response.status_code == 200
    data = response.json()
    assert "comfyui" in data
    assert "automatic1111" in data
    assert "detected" in data["comfyui"]
    assert "url" in data["comfyui"]


def test_generate_image_requires_prompt(client):
    response = client.post("/api/image-generation/generate", json={"backend": "comfyui"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Prompt is required"


def test_upload_reference_image_success(client, tmp_path):
    ref_dir = Path(settings.db_path).parent / "reference-images"
    ref_dir.mkdir(parents=True, exist_ok=True)

    image_data = _MINIMAL_PNG
    response = client.post(
        "/api/image-generation/reference-image",
        files={"file": ("test.png", image_data, "image/png")},
        data={"influencer_id": "1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "url" in data
    assert data["url"].startswith("/reference-images/")


def test_upload_reference_image_invalid_type(client):
    response = client.post(
        "/api/image-generation/reference-image",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_reference_image_too_large(client):
    large_data = b"x" * (11 * 1024 * 1024)
    response = client.post(
        "/api/image-generation/reference-image",
        files={"file": ("large.png", large_data, "image/png")},
    )
    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()


def test_image_history_endpoint(client):
    response = client.get("/api/image-generation/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_generate_image_invalid_backend(client):
    response = client.post("/api/image-generation/generate", json={"backend": "nonexistent", "prompt": "test"})
    assert response.status_code == 500
    assert "Unsupported image generation backend" in response.json()["detail"]
