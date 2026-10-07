import io
import json
from pathlib import Path
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


def test_comfyui_workflow_with_reference_image():
    workflow = image_gen._comfyui_workflow(
        prompt="test prompt",
        negative_prompt="bad quality",
        width=512,
        height=768,
        steps=20,
        cfg_scale=6.5,
        seed=42,
        model="test_model.safetensors",
        reference_image_path="storage/reference-images/ref_test.png",
    )
    assert "1" in workflow
    assert "2" in workflow
    assert workflow["1"]["class_type"] == "LoadImage"
    assert workflow["2"]["class_type"] == "VAEEncode"
    assert workflow["3"]["inputs"]["latent_image"] == ["2", 0]
    assert workflow["3"]["inputs"]["denoise"] == 0.6


def test_comfyui_workflow_with_ip_adapter():
    workflow = image_gen._comfyui_workflow(
        prompt="test prompt",
        reference_image_path="storage/reference-images/ref_test.png",
        ip_adapter=True,
        ip_adapter_model="ip-adapter-plus_sd15.bin",
    )
    assert "10" in workflow
    assert "11" in workflow
    assert workflow["10"]["class_type"] == "IPAdapterModelLoader"
    assert workflow["10"]["inputs"]["ipadapter_file"] == "ip-adapter-plus_sd15.bin"
    assert workflow["3"]["inputs"]["model"] == ["11", 0]


def test_comfyui_workfallback_without_ip_adapter_nodes():
    workflow = image_gen._comfyui_workflow(
        prompt="test prompt",
        reference_image_path="storage/reference-images/ref_test.png",
        ip_adapter=False,
    )
    assert "10" not in workflow
    assert "11" not in workflow
    assert workflow["3"]["inputs"]["model"] == ["4", 0]


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


def test_detect_local_backends(monkeypatch):
    class FakeComfyResponse:
        status_code = 200
        def json(self):
            return {
                "CheckpointLoaderSimple": {
                    "input": {
                        "required": {
                            "ckpt_name": [["v1-5-pruned-emaonly.safetensors", "other.safetensors"]]
                        }
                    }
                }
            }
        def raise_for_status(self):
            pass

    class FakeA1111Response:
        status_code = 200
        def json(self):
            return [{"title": "sd_v1", "model_name": "sd_v1.safetensors"}]
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
            if "/object_info" in url:
                return FakeComfyResponse()
            if "/sdapi/v1/sd-models" in url:
                return FakeA1111Response()
            raise RuntimeError(f"unexpected get: {url}")

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    result = image_gen.detect_local_backends(timeout=1.0)
    assert result["comfyui"]["detected"] is True
    assert "v1-5-pruned-emaonly.safetensors" in result["comfyui"]["models"]
    assert result["automatic1111"]["detected"] is True
    assert "sd_v1" in result["automatic1111"]["models"]


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
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


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
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_generate_image_comfyui_with_reference(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    ref_dir = tmp_path / "reference-images"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_file = ref_dir / "ref.png"
    ref_file.write_bytes(b"REFDATA")

    upload_called = False

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
        def post(self, url, json=None, timeout=None, files=None, data=None):
            nonlocal upload_called
            if url.endswith("/upload/image"):
                upload_called = True
                return FakeResponse()
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
    path = image_gen.generate_image_comfyui(prompt="a cat", reference_image_path=str(ref_file))
    assert path.endswith(".png")
    assert upload_called is True


def test_generate_image_a1111_with_reference(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    ref_dir = tmp_path / "reference-images"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_file = ref_dir / "ref.png"
    ref_file.write_bytes(b"REFDATA")

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
        def post(self, url, json=None, timeout=None, files=None, data=None):
            assert "/sdapi/v1/txt2img" in url
            assert "init_images" in json
            return FakeResponse()

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    path = image_gen.generate_image_a1111(prompt="a dog", reference_image_path=str(ref_file))
    assert path.endswith(".png")


def test_generate_image_comfyui_timeout(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"prompt_id": "abc123"}
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
                raise ConnectionError("connection reset")
            raise RuntimeError("unexpected post")
        def get(self, url, timeout=None):
            raise RuntimeError("unexpected get")

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    monkeypatch.setattr(image_gen.time, "sleep", lambda s: None)
    current = [1000.0]
    def fake_time():
        current[0] += 50.0
        return current[0]
    monkeypatch.setattr(image_gen.time, "time", fake_time)
    with pytest.raises(TimeoutError, match="timed out"):
        image_gen.generate_image_comfyui(prompt="a cat")


def test_generate_image_comfyui_failed_status(monkeypatch, tmp_path):
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
                    "status": {"status_str": "error", "error": "OOM"},
                }
            }
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
            raise RuntimeError("unexpected get")

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    with pytest.raises(RuntimeError, match="ComfyUI generation failed"):
        image_gen.generate_image_comfyui(prompt="a cat")


def test_generate_image_a1111_no_images(monkeypatch, tmp_path):
    db_path = tmp_path / "storage" / "viralstack.db"
    monkeypatch.setattr(image_gen.settings, "db_path", str(db_path))

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"images": []}
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
            return FakeResponse()

    monkeypatch.setattr(image_gen.httpx, "Client", lambda timeout=None: FakeClient())
    with pytest.raises(RuntimeError, match="A1111 returned no images"):
        image_gen.generate_image_a1111(prompt="a dog")
