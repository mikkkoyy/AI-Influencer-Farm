import json
from unittest.mock import patch, MagicMock

import pytest

from pipeline import image_gen


def test_comfyui_workflow_contains_expected_nodes():
    workflow = image_gen._comfyui_workflow(
        prompt="test prompt",
        negative_prompt="bad quality",
        width=512,
        height=768,
        steps=20,
        cfg_scale=6.5,
        seed=42,
        model="test_model.safetensors",
    )
    assert "3" in workflow
    assert "4" in workflow
    assert "5" in workflow
    assert "6" in workflow
    assert "7" in workflow
    assert "8" in workflow
    assert "9" in workflow
    assert workflow["3"]["class_type"] == "KSampler"
    assert workflow["4"]["inputs"]["ckpt_name"] == "test_model.safetensors"


def test_comfyui_workflow_defaults():
    workflow = image_gen._comfyui_workflow(prompt="test")
    assert workflow["5"]["inputs"]["width"] == 512
    assert workflow["5"]["inputs"]["height"] == 768
    assert workflow["3"]["inputs"]["steps"] == 30
    assert workflow["3"]["inputs"]["cfg"] == 7.0


def test_check_backend_health_comfyui_online(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"node_id": {"class_type": "KSampler"}}

    class FakeClient:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, timeout=None):
            assert "/object_info" in url
            return FakeResponse()

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    result = image_gen.check_backend_health("comfyui")
    assert result["ok"] is True
    assert result["backend"] == "comfyui"


def test_check_backend_health_a1111_online(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return [{"title": "model1", "model_name": "model1.safetensors"}]
        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, timeout=None):
            assert "/sdapi/v1/sd-models" in url
            return FakeResponse()

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    result = image_gen.check_backend_health("automatic1111")
    assert result["ok"] is True
    assert result["backend"] == "automatic1111"
    assert "model1" in result.get("models", [])


def test_check_backend_health_offline(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, timeout=None):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    result = image_gen.check_backend_health("comfyui")
    assert result["ok"] is False
    assert "error" in result


def test_generate_image_unsupported_backend():
    with pytest.raises(ValueError, match="Unsupported image generation backend"):
        image_gen.generate_image(backend="nonexistent", prompt="test")


def test_generate_image_comfyui_success(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"prompt_id": "abc123"}
        def raise_for_status(self):
            pass

    class FakeHistoryResponse:
        status_code = 200
        def json(self):
            return {
                "abc123": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {
                        "9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}
                    },
                }
            }
        def raise_for_status(self):
            pass

    class FakeImageResponse:
        status_code = 200
        def __init__(self, content):
            self._content = content
            self.content = content
        def read(self):
            return self._content
        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, json=None, timeout=None):
            if url.endswith("/prompt"):
                return FakeResponse()
            if "/history/" in url:
                return FakeHistoryResponse()
            raise RuntimeError(f"unexpected post: {url}")
        def get(self, url, timeout=None):
            if "/view?" in url:
                return FakeImageResponse(b"PNGDATA")
            raise RuntimeError(f"unexpected get: {url}")

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    path = image_gen.generate_image_comfyui(prompt="a cat", width=512, height=768)
    assert path.endswith(".png")


def test_generate_image_a1111_success(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"images": [b"PNGDATA1111"]}
        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, json=None, timeout=None):
            assert "/sdapi/v1/txt2img" in url
            return FakeResponse()

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    path = image_gen.generate_image_a1111(prompt="a dog", width=512, height=768)
    assert path.endswith(".png")
