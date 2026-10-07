"""
Local image generation backends.

Supported backends:
- comfyui: ComfyUI (http://127.0.0.1:8188)
- automatic1111: AUTOMATIC1111 Stable Diffusion WebUI (http://127.0.0.1:7860)

Each backend returns a local file path on success or raises on failure.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from config.settings import settings, resolve_project_path

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_ROOT = Path(settings.db_path).parent / "generated-images"
_DEFAULT_TIMEOUT = 300.0


def _get_output_root() -> Path:
    return _DEFAULT_OUTPUT_ROOT


def _ensure_output_dir() -> Path:
    root = _get_output_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _comfyui_base_url() -> str:
    return (settings.image_gen_base_url or "").strip().rstrip("/") or "http://127.0.0.1:8188"


def _a1111_base_url() -> str:
    return (settings.image_gen_base_url or "").strip().rstrip("/") or "http://127.0.0.1:7860"


def detect_local_backends(timeout: float = 3.0) -> dict[str, Any]:
    """Detect available local image generation backends on this machine."""
    results: dict[str, Any] = {
        "comfyui": {"detected": False, "url": _comfyui_base_url(), "error": ""},
        "automatic1111": {"detected": False, "url": _a1111_base_url(), "error": ""},
    }

    for backend, url in [
        ("comfyui", _comfyui_base_url()),
        ("automatic1111", _a1111_base_url()),
    ]:
        try:
            with httpx.Client(timeout=timeout) as client:
                if backend == "comfyui":
                    response = client.get(f"{url}/object_info")
                    if response.status_code == 200:
                        data = response.json()
                        models = []
                        if "CheckpointLoaderSimple" in data:
                            ckpt_info = data["CheckpointLoaderSimple"]
                            if isinstance(ckpt_info, dict) and "input" in ckpt_info:
                                ckpt_input = ckpt_info["input"]
                                if isinstance(ckpt_input, dict) and "required" in ckpt_input:
                                    ckpt_required = ckpt_input["required"]
                                    if isinstance(ckpt_required, dict) and "ckpt_name" in ckpt_required:
                                        models = [m[0] if isinstance(m, (list, tuple)) else str(m) for m in ckpt_required["ckpt_name"][0]]
                        results[backend] = {
                            "detected": True,
                            "url": url,
                            "models": models[:10],
                            "nodes": len(data) if isinstance(data, dict) else 0,
                        }
                        continue
                else:
                    response = client.get(f"{url}/sdapi/v1/sd-models")
                    if response.status_code == 200:
                        data = response.json()
                        models = [m.get("title") or m.get("model_name") for m in data] if isinstance(data, list) else []
                        results[backend] = {
                            "detected": True,
                            "url": url,
                            "models": models[:10],
                        }
                        continue
                results[backend]["error"] = f"HTTP {response.status_code}"
        except Exception as exc:
            results[backend]["error"] = str(exc)[:200]

    return results


def _post_json(base_url: str, path: str, payload: dict, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    url = f"{base_url}{path}"
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _post_multipart(base_url: str, path: str, files: dict, data: dict, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    url = f"{base_url}{path}"
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, files=files, data=data)
        response.raise_for_status()
        return response.json()


def _upload_comfyui_image(base_url: str, image_path: str) -> dict:
    """Upload an image to ComfyUI's input directory."""
    image_file = Path(image_path)
    if not image_file.exists():
        raise FileNotFoundError(f"Reference image not found: {image_path}")
    with image_file.open("rb") as fh:
        files = {"image": (image_file.name, fh, "application/octet-stream")}
        data = {"overwrite": "true"}
        return _post_multipart(base_url, "/upload/image", files=files, data=data)


def _get_bytes(base_url: str, path: str, timeout: float = _DEFAULT_TIMEOUT) -> bytes:
    url = f"{base_url}{path}"
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _comfyui_workflow(
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 768,
    steps: int = 30,
    cfg_scale: float = 7.0,
    seed: int = -1,
    sampler: str = "euler",
    scheduler: str = "normal",
    model: str = "",
    reference_image_path: str = "",
    ip_adapter: bool = False,
    ip_adapter_model: str = "ip-adapter-plus_sd15.bin",
) -> dict:
    """Build a minimal ComfyUI API workflow for txt2img or img2img.

    If `reference_image_path` is provided, builds an img2img-style workflow.
    If `ip_adapter=True`, includes optional IP-Adapter nodes (requires custom nodes).
    Falls back to standard img2img when IP-Adapter nodes are unavailable.
    """
    if seed == -1:
        seed = int(time.time() * 1000) % (2**32)

    checkpoint = model or "v1-5-pruned-emaonly.safetensors"

    if reference_image_path:
        base = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": Path(reference_image_path).name},
            },
            "2": {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["1", 0], "vae": ["4", 2]},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "denoise": 0.6,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["2", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative_prompt or "bad quality, blurry, distorted", "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "AI-Influencer-Farm", "images": ["8", 0]},
            },
        }

        if ip_adapter:
            base.update({
                "10": {
                    "class_type": "IPAdapterModelLoader",
                    "inputs": {"ipadapter_file": ip_adapter_model},
                },
                "11": {
                    "class_type": "IPAdapterApply",
                    "inputs": {
                        "ipadapter": ["10", 0],
                        "clip_vision": ["4", 1],
                        "image": ["1", 0],
                        "model": ["4", 0],
                    },
                },
            })
            base["3"]["inputs"]["model"] = ["11", 0]

        return base

    base = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg_scale,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt or "bad quality, blurry, distorted", "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "AI-Influencer-Farm", "images": ["8", 0]},
        },
    }

    if ip_adapter:
        base.update({
            "10": {
                "class_type": "IPAdapterModelLoader",
                "inputs": {"ipadapter_file": ip_adapter_model},
            },
            "11": {
                "class_type": "IPAdapterApply",
                "inputs": {
                    "ipadapter": ["10", 0],
                    "clip_vision": ["4", 1],
                    "image": ["5", 0],
                    "model": ["4", 0],
                },
            },
        })
        base["3"]["inputs"]["model"] = ["11", 0]

    return base


def generate_image_comfyui(
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 768,
    steps: int = 30,
    cfg_scale: float = 7.0,
    seed: int = -1,
    model: str = "",
    influencer_id: Optional[int] = None,
    reference_image_path: str = "",
    ip_adapter: bool = False,
    ip_adapter_model: str = "ip-adapter-plus_sd15.bin",
) -> str:
    """Generate an image using ComfyUI and return the local file path."""
    base_url = _comfyui_base_url()

    if reference_image_path:
        logger.info("Uploading reference image to ComfyUI: %s", reference_image_path)
        _upload_comfyui_image(base_url, reference_image_path)

    workflow = _comfyui_workflow(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        model=model,
        reference_image_path=reference_image_path,
        ip_adapter=ip_adapter,
        ip_adapter_model=ip_adapter_model,
    )

    logger.info("Submitting ComfyUI workflow to %s", base_url)
    payload = {"prompt": workflow}
    result = _post_json(base_url, "/prompt", payload)

    prompt_id = result.get("prompt_id") or result.get("number")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return a prompt ID: {result}")

    logger.info("ComfyUI prompt submitted: %s", prompt_id)

    max_wait = 120.0
    start = time.time()
    while time.time() - start < max_wait:
        try:
            history = _post_json(base_url, f"/history/{prompt_id}", {}, timeout=10.0)
            if isinstance(history, dict) and prompt_id in history:
                entry = history[prompt_id]
            elif isinstance(history, list):
                entry = next((h for h in history if h.get("prompt_id") == prompt_id), None)
            else:
                entry = None

            if entry:
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") == "success":
                    break
                if status.get("status_str") in {"error", "failed"}:
                    raise RuntimeError(f"ComfyUI generation failed: {status}")
        except httpx.HTTPStatusError:
            pass
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(2.0)
    else:
        raise TimeoutError(f"ComfyUI generation timed out after {max_wait}s")

    outputs = (entry or {}).get("outputs", {})
    output_images = []
    for node_id, node_output in outputs.items():
        if "images" in node_output:
            output_images.extend(node_output["images"])

    if not output_images:
        raise RuntimeError("ComfyUI returned no images in outputs")

    image_info = output_images[0]
    filename = image_info.get("filename") or image_info.get("name", "output.png")
    subfolder = image_info.get("subfolder", "")
    image_type = image_info.get("type", "output")

    params = {"filename": filename, "subfolder": subfolder, "type": image_type}
    view_url = f"/view?{httpx.QueryParams(params)}"
    image_bytes = _get_bytes(base_url, view_url)

    output_dir = _ensure_output_dir()
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = output_dir / f"{int(time.time()*1000)}_{safe_name}"
    dest.write_bytes(image_bytes)
    logger.info("ComfyUI image saved: %s (%d bytes)", dest, len(image_bytes))
    return str(dest)


def generate_image_a1111(
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 768,
    steps: int = 30,
    cfg_scale: float = 7.0,
    seed: int = -1,
    sampler_name: str = "Euler a",
    model: str = "",
    influencer_id: Optional[int] = None,
    reference_image_path: str = "",
) -> str:
    """Generate an image using AUTOMATIC1111 Stable Diffusion WebUI and return the local file path."""
    base_url = _a1111_base_url()
    payload: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "bad quality, blurry, distorted",
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "seed": seed if seed != -1 else int(time.time() * 1000) % (2**32),
        "sampler_name": sampler_name,
        "batch_size": 1,
    }
    if model:
        payload["override_settings"] = {"sd_model_checkpoint": model}

    if reference_image_path:
        ref_path = Path(reference_image_path)
        if not ref_path.exists():
            raise FileNotFoundError(f"Reference image not found: {reference_image_path}")
        payload["init_images"] = [ref_path.read_bytes()]

    logger.info("Submitting A1111 txt2img to %s", base_url)
    start = time.time()
    response = _post_json(base_url, "/sdapi/v1/txt2img", payload)
    elapsed_ms = int((time.time() - start) * 1000)

    images = response.get("images", [])
    if not images:
        raise RuntimeError("A1111 returned no images")

    output_dir = _ensure_output_dir()
    safe_name = f"a1111_{int(time.time()*1000)}.png"
    dest = output_dir / safe_name
    image_data = httpx.bytes(images[0]) if hasattr(httpx, "bytes") else images[0]
    if hasattr(images[0], "read"):
        image_data = images[0].read()
    dest.write_bytes(image_data)
    logger.info("A1111 image saved: %s (%d bytes, %dms)", dest, len(image_data), elapsed_ms)
    return str(dest)


def generate_image(
    backend: str,
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 768,
    steps: int = 30,
    cfg_scale: float = 7.0,
    seed: int = -1,
    model: str = "",
    influencer_id: Optional[int] = None,
    reference_image_path: str = "",
    ip_adapter: bool = False,
    ip_adapter_model: str = "ip-adapter-plus_sd15.bin",
) -> str:
    """Generate an image using the specified local backend.

    Supported backends: comfyui, automatic1111
    Returns the local file path on success.
    """
    backend = (backend or "").strip().lower()
    if backend == "comfyui":
        return generate_image_comfyui(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            model=model,
            influencer_id=influencer_id,
            reference_image_path=reference_image_path,
            ip_adapter=ip_adapter,
            ip_adapter_model=ip_adapter_model,
        )
    if backend in {"a1111", "automatic1111", "stable-diffusion-webui"}:
        return generate_image_a1111(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            model=model,
            influencer_id=influencer_id,
            reference_image_path=reference_image_path,
        )
    raise ValueError(f"Unsupported image generation backend: {backend}")


def check_backend_health(backend: str) -> dict[str, Any]:
    """Check if a local image generation backend is reachable."""
    backend = (backend or "").strip().lower()
    if backend == "comfyui":
        base_url = _comfyui_base_url()
    elif backend in {"a1111", "automatic1111", "stable-diffusion-webui"}:
        base_url = _a1111_base_url()
    else:
        return {"backend": backend, "ok": False, "error": "unsupported backend"}

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{base_url}/object_info" if backend == "comfyui" else f"{base_url}/sdapi/v1/sd-models")
            if response.status_code == 200:
                data = response.json()
                if backend == "comfyui":
                    return {"backend": backend, "ok": True, "url": base_url, "nodes": len(data) if isinstance(data, dict) else 0}
                models = [m.get("title") or m.get("model_name") for m in data] if isinstance(data, list) else []
                return {"backend": backend, "ok": True, "url": base_url, "models": models[:10]}
            return {"backend": backend, "ok": False, "url": base_url, "status_code": response.status_code}
    except Exception as exc:
        return {"backend": backend, "ok": False, "url": base_url, "error": str(exc)[:200]}
