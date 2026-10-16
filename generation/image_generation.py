"""Diffusers image generation with resource preflight, caching and optional IP-Adapter."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

class ImageGenerationUnavailable(RuntimeError):
    pass


def environment_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": __import__("sys").version.split()[0],
        "cuda_available": False,
        "device": "cpu",
        "gpu_name": None,
        "gpu_memory_gb": None,
        "ram_gb": None,
        "free_disk_gb": None,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "torch_version": None,
        "cuda_version": None,
    }
    try:
        import torch
        report["torch_version"] = torch.__version__
        report["cuda_version"] = getattr(torch.version, "cuda", None)
        report["cuda_available"] = bool(torch.cuda.is_available())
        if report["cuda_available"]:
            props = torch.cuda.get_device_properties(0)
            report.update({"device": "cuda", "gpu_name": props.name, "gpu_memory_gb": round(props.total_memory / 1024**3, 2)})
    except Exception as exc:
        report["torch_error"] = f"{type(exc).__name__}: {exc}"
    try:
        import psutil
        report["ram_gb"] = round(psutil.virtual_memory().total / 1024**3, 2)
    except Exception:
        pass
    try:
        report["free_disk_gb"] = round(shutil.disk_usage(Path.cwd()).free / 1024**3, 2)
    except Exception:
        pass
    return report


def select_image_model(primary_model: str, fallback_model: str | None = "runwayml/stable-diffusion-v1-5", min_sdxl_vram_gb: float = 12.0, min_light_vram_gb: float = 6.0) -> dict[str, Any]:
    env = environment_report()
    if not env["cuda_available"]:
        if os.getenv("ALLOW_CPU_IMAGE_GENERATION", "false").lower() == "true":
            return {"model_id": fallback_model or primary_model, "reason": "CPU mode explicitly enabled; generation may be very slow", "device": "cpu", "resolution": [512, 768], "steps": 12}
        raise ImageGenerationUnavailable("No CUDA GPU is available. Enable a Colab GPU (Runtime > Change runtime type > T4 GPU) or explicitly set ALLOW_CPU_IMAGE_GENERATION=true; CPU diffusion can be very slow.")
    vram = float(env.get("gpu_memory_gb") or 0)
    if vram >= min_sdxl_vram_gb:
        return {"model_id": primary_model, "reason": f"GPU has {vram:.1f} GB VRAM; primary SDXL route selected", "device": "cuda", "resolution": [768, 1344], "steps": 25}
    if fallback_model and vram >= min_light_vram_gb:
        return {"model_id": fallback_model, "reason": f"GPU has {vram:.1f} GB VRAM; lighter Diffusers checkpoint selected", "device": "cuda", "resolution": [512, 896], "steps": 18}
    raise ImageGenerationUnavailable(f"Detected {vram:.1f} GB GPU memory; below the configured image model minimum. No image was generated.")


def _cache_fingerprint(prompt: str, negative_prompt: str, model_id: str, seed: int, width: int, height: int, steps: int) -> str:
    material = json.dumps({"prompt": prompt, "negative": negative_prompt, "model": model_id, "seed": seed, "width": width, "height": height, "steps": steps}, sort_keys=True).encode()
    return hashlib.sha256(material).hexdigest()


def _valid_image(path: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return path.stat().st_size > 1024
    except Exception:
        return False


def generate_images_for_storyboard(shots: list[Any], cache_root: str | Path | None = None, primary_model: str = "stabilityai/stable-diffusion-xl-base-1.0", fallback_model: str | None = "runwayml/stable-diffusion-v1-5", use_ip_adapter: bool = False, character_reference: str | Path | None = None, reference_sheet_prompt: str | None = None, reference_sheet_path: str | Path | None = None) -> dict[str, Any]:
    """Generate all storyboard images with one loaded pipeline; reuse complete cache without loading weights."""
    # A fully valid fingerprinted cache must remain usable even when this session has no GPU.
    cached: dict[str, str] = {}
    cached_stock: dict[str, str] = {}
    cached_diffusion: dict[str, str] = {}
    pending: list[Any] = []
    for idx, shot in enumerate(shots):
        sid = str(getattr(shot, "shot_id", f"shot_{idx+1:03d}"))
        existing_path = getattr(shot, "image_path", None)
        if not existing_path:
            pending.append(shot)
            continue
        path = Path(existing_path)
        settings = getattr(shot, "image_settings", {}) or {}
        model_for_cache = str(getattr(shot, "image_model", primary_model) or primary_model)
        seed_for_cache = int(settings.get("seed", 1337 + idx))
        width_for_cache = int(settings.get("width", 768 if "xl" in model_for_cache.lower() else 512))
        height_for_cache = int(settings.get("height", 1344 if "xl" in model_for_cache.lower() else 896))
        steps_for_cache = int(settings.get("steps", 25))
        marker = path.with_suffix(path.suffix + ".sha256")
        expected = _cache_fingerprint(shot.visual_prompt, shot.negative_prompt, model_for_cache, seed_for_cache, width_for_cache, height_for_cache, steps_for_cache)
        if _valid_image(path) and marker.exists() and marker.read_text(encoding="utf-8").strip() == expected:
            cached[sid] = str(path)
            cached_diffusion[sid] = str(path)
        elif _valid_image(path) and str(getattr(shot, "generation_status", "")) == "stock_image_fallback":
            # A verified provider asset is a legitimate cache item, not a reason to redownload diffusion weights.
            cached[sid] = str(path)
            cached_stock[sid] = str(path)
        else:
            pending.append(shot)
    reference_needs_generation = bool(
        reference_sheet_prompt and reference_sheet_path
        and not (Path(reference_sheet_path).is_file() and _valid_image(Path(reference_sheet_path)))
        and not (character_reference and Path(character_reference).is_file() and _valid_image(Path(character_reference)))
    )
    if not pending and not reference_needs_generation:
        models = sorted({str(getattr(shot, "image_model", primary_model) or primary_model) for shot in shots})
        ref_path = Path(reference_sheet_path) if reference_sheet_path and Path(reference_sheet_path).is_file() and _valid_image(Path(reference_sheet_path)) else None
        if ref_path is None and character_reference and Path(character_reference).is_file() and _valid_image(Path(character_reference)):
            ref_path = Path(character_reference)
        selected_model = (models[0] if len(models) == 1 else models) if cached_diffusion else None
        method_note = "Cached generated images were reused; no model weights were loaded." if cached_diffusion else "Verified provider-sourced stock images were reused; no model weights were loaded."
        return {"status": "partial_success" if cached_stock else "success", "selected_model": selected_model, "selection_reason": method_note, "images": cached, "asset_methods": {**{sid: "diffusers_cached" for sid in cached_diffusion}, **{sid: "stock_image_fallback" for sid in cached_stock}}, "cached_stock_ids": sorted(cached_stock), "cached_diffusion_ids": sorted(cached_diffusion), "errors": {}, "ip_adapter_status": "not_needed_for_cached_images", "reference_sheet_path": str(ref_path) if ref_path else None, "reference_sheet_status": "cached_or_not_needed", "cached": True, "hardware": environment_report()}
    try:
        import torch
        from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline
    except Exception as exc:
        if not pending:
            methods = {**{sid: "diffusers_cached" for sid in cached_diffusion}, **{sid: "stock_image_fallback" for sid in cached_stock}}
            return {"status": "partial_success" if cached_stock else "success", "selected_model": None, "selection_reason": "Cached shot images were preserved; reference sheet could not be generated because Diffusers is unavailable.", "images": cached, "asset_methods": methods, "cached_stock_ids": sorted(cached_stock), "cached_diffusion_ids": sorted(cached_diffusion), "errors": {}, "ip_adapter_status": "unavailable:diffusers_missing", "reference_sheet_path": None, "reference_sheet_status": f"not_generated:{type(exc).__name__}", "cached": True, "hardware": environment_report()}
        raise ImageGenerationUnavailable("PyTorch and Diffusers are required for image generation of missing shots.") from exc
    try:
        selection = select_image_model(primary_model, fallback_model)
    except ImageGenerationUnavailable as exc:
        if not pending:
            methods = {**{sid: "diffusers_cached" for sid in cached_diffusion}, **{sid: "stock_image_fallback" for sid in cached_stock}}
            return {"status": "partial_success" if cached_stock else "success", "selected_model": None, "selection_reason": "Cached shot images were preserved; reference sheet was not generated because hardware preflight failed.", "images": cached, "asset_methods": methods, "cached_stock_ids": sorted(cached_stock), "cached_diffusion_ids": sorted(cached_diffusion), "errors": {}, "ip_adapter_status": "not_available_without_generation", "reference_sheet_path": None, "reference_sheet_status": f"not_generated:{type(exc).__name__}:{exc}", "cached": True, "hardware": environment_report()}
        raise
    model_id = selection["model_id"]
    width, height = selection["resolution"]
    steps = selection["steps"]
    if cache_root:
        os.environ.setdefault("HF_HOME", str(Path(cache_root) / "huggingface"))
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(Path(cache_root) / "huggingface" / "hub"))
        Path(os.environ["HF_HOME"]).mkdir(parents=True, exist_ok=True)
    is_sdxl = "stable-diffusion-xl" in model_id
    dtype = torch.float16 if selection["device"] == "cuda" else torch.float32
    try:
        if is_sdxl:
            pipe = StableDiffusionXLPipeline.from_pretrained(model_id, torch_dtype=dtype, use_safetensors=True, low_cpu_mem_usage=True)
        else:
            pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False, use_safetensors=True)
        if selection["device"] == "cuda":
            pipe.enable_model_cpu_offload()
            try: pipe.enable_vae_slicing()
            except Exception: pass
            try: pipe.enable_vae_tiling()
            except Exception: pass
        else:
            pipe.to("cpu")
        reference_target = Path(reference_sheet_path) if reference_sheet_path else None
        reference_to_use = Path(character_reference) if character_reference and Path(character_reference).is_file() and _valid_image(Path(character_reference)) else None
        reference_status = "provided_reference" if reference_to_use else "not_requested"
        if reference_to_use is None and reference_target and reference_target.is_file() and _valid_image(reference_target):
            reference_to_use = reference_target
            reference_status = "reused_persistent_reference"
        elif reference_target and reference_target.exists() and not _valid_image(reference_target):
            reference_target.unlink(missing_ok=True)
        if reference_to_use is None and reference_target and reference_sheet_prompt:
            try:
                reference_target.parent.mkdir(parents=True, exist_ok=True)
                ref_w = min(width, 768)
                ref_h = min(height, 1024)
                ref_w = max(384, (ref_w // 8) * 8)
                ref_h = max(512, (ref_h // 8) * 8)
                ref_seed = torch.Generator(device="cpu").manual_seed(7654321)
                ref_image = pipe(
                    prompt=reference_sheet_prompt,
                    negative_prompt="unrelated subjects, inconsistent faces, different outfits, text, labels, watermark, duplicate limbs, malformed anatomy, blurry, low quality",
                    width=ref_w, height=ref_h, num_inference_steps=min(20, steps), generator=ref_seed,
                ).images[0]
                ref_image.save(reference_target)
                if _valid_image(reference_target):
                    reference_to_use = reference_target
                    reference_status = "generated_persistent_reference_sheet"
                else:
                    reference_status = "generation_failed_validation"
                    reference_target.unlink(missing_ok=True)
            except Exception as exc:
                reference_status = f"generation_failed:{type(exc).__name__}:{exc}"
        adapter_status = "not_requested"
        if use_ip_adapter and reference_to_use and reference_to_use.exists() and is_sdxl:
            try:
                pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models", weight_name="ip-adapter_sdxl.bin")
                pipe.set_ip_adapter_scale(0.6)
                adapter_status = "enabled"
            except Exception as exc:
                adapter_status = f"unavailable:{type(exc).__name__}:{exc}"
        elif use_ip_adapter and reference_to_use and not is_sdxl:
            adapter_status = "unavailable:IP-Adapter reference conditioning is configured only for the selected SDXL path; stable descriptions remain in prompts."
        root = Path(cache_root) if cache_root else None
        generated: dict[str, str] = dict(cached)
        errors: dict[str, str] = {}
        for idx, shot in enumerate(shots):
            sid = str(getattr(shot, "shot_id", f"shot_{idx+1:03d}"))
            existing_path = getattr(shot, "image_path", None)
            path = Path(existing_path) if existing_path else (root / "images" / f"{sid}.png" if root else Path("images") / f"{sid}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            seed = int(getattr(shot, "image_settings", {}).get("seed", 1337 + idx))
            shot_width = int(getattr(shot, "image_settings", {}).get("width", width))
            shot_height = int(getattr(shot, "image_settings", {}).get("height", height))
            # Do not let the LLM's requested size override the resource-selected fallback resolution.
            shot_width = min(shot_width, width)
            shot_height = min(shot_height, height)
            shot_width = max(512 if is_sdxl else 384, (shot_width // 8) * 8)
            shot_height = max(768 if is_sdxl else 512, (shot_height // 8) * 8)
            shot_steps = min(int(getattr(shot, "image_settings", {}).get("steps", steps)), steps)
            shot_model = model_id
            shot.image_model = model_id
            shot.image_settings = {**getattr(shot, "image_settings", {}), "width": shot_width, "height": shot_height, "steps": shot_steps, "seed": seed}
            fingerprint = _cache_fingerprint(shot.visual_prompt, shot.negative_prompt, shot_model, seed, shot_width, shot_height, shot_steps)
            marker = path.with_suffix(path.suffix + ".sha256")
            if _valid_image(path) and marker.exists() and marker.read_text(encoding="utf-8").strip() == fingerprint:
                generated[sid] = str(path)
                continue
            try:
                generator = torch.Generator(device="cpu").manual_seed(seed)
                kwargs: dict[str, Any] = {
                    "prompt": shot.visual_prompt,
                    "negative_prompt": shot.negative_prompt,
                    "width": shot_width,
                    "height": shot_height,
                    "num_inference_steps": shot_steps,
                    "generator": generator,
                }
                if adapter_status == "enabled":
                    from diffusers.utils import load_image
                    kwargs["ip_adapter_image"] = load_image(str(reference_to_use))
                image = pipe(**kwargs).images[0]
                image.save(path)
                if not _valid_image(path):
                    raise ImageGenerationUnavailable("Generated file failed image validation.")
                marker.write_text(fingerprint + "\n", encoding="utf-8")
                generated[sid] = str(path)
                shot.image_path = str(path)
                shot.generation_status = "image_success"
            except Exception as exc:
                errors[sid] = f"{type(exc).__name__}: {exc}"
                shot.generation_status = "image_failed"
                shot.generation_error = errors[sid]
        del pipe
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        if not generated:
            raise ImageGenerationUnavailable(f"No storyboard images were generated. Errors: {errors}")
        return {"status": "success" if not errors else "partial_success", "selected_model": model_id, "selection_reason": selection["reason"], "image_resolution": [width, height], "images": generated, "asset_methods": {sid: ("stock_image_fallback" if sid in cached_stock else ("diffusers_cached" if sid in cached_diffusion else "diffusers_generated")) for sid in generated}, "cached_stock_ids": sorted(cached_stock), "cached_diffusion_ids": sorted(cached_diffusion), "errors": errors, "ip_adapter_status": adapter_status, "reference_sheet_path": str(reference_to_use) if reference_to_use else None, "reference_sheet_status": reference_status, "hardware": environment_report()}
    except ImageGenerationUnavailable:
        raise
    except Exception as exc:
        raise ImageGenerationUnavailable(f"Diffusers image generation failed using {model_id}: {type(exc).__name__}: {exc}") from exc


def generate_image(prompt: str, negative_prompt: str, output_path: str | Path, model_id: str = "stabilityai/stable-diffusion-xl-base-1.0", seed: int = 42, width: int = 768, height: int = 1344, steps: int = 25) -> Path:
    """Single-image convenience interface, with the same preflight safeguards."""
    from types import SimpleNamespace
    shot = SimpleNamespace(
        shot_id=Path(output_path).stem,
        visual_prompt=prompt,
        negative_prompt=negative_prompt,
        image_settings={"width": width, "height": height, "steps": steps, "seed": seed},
        image_model=model_id,
        image_path=str(output_path),
        generation_status="pending",
        generation_error=None,
    )
    result = generate_images_for_storyboard([shot], primary_model=model_id, fallback_model=None)
    return Path(result["images"][shot.shot_id])
