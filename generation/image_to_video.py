"""Real image-to-video adapters plus explicitly labelled FFmpeg animation fallback."""
from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
from typing import Any

class VideoGenerationUnavailable(RuntimeError):
    pass


def video_capabilities() -> dict[str, Any]:
    try:
        import torch
        available = bool(torch.cuda.is_available())
        props = torch.cuda.get_device_properties(0) if available else None
        memory = round(props.total_memory / 1024**3, 2) if props else 0.0
        name = props.name if props else None
    except Exception:
        available, memory, name = False, 0.0, None
    cache_home = Path(__import__("os").environ.get("HF_HOME", str(Path.cwd())))
    try:
        free_disk_gb = round(shutil.disk_usage(cache_home if cache_home.exists() else Path.cwd()).free / 1024**3, 2)
    except Exception:
        free_disk_gb = None
    # The published 14B Diffusers-format repository is exceptionally large (listed at roughly 90 GB).
    # Do not start that download on an ordinary Colab disk or a GPU below a conservative VRAM tier.
    if available and memory >= 48 and free_disk_gb is not None and free_disk_gb >= 100:
        model, method, reason = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers", "wan_i2v", f"{memory:.1f} GB VRAM and {free_disk_gb:.1f} GB free cache space meet conservative Wan 14B preflight"
    elif available and memory >= 12:
        model, method, reason = "stabilityai/stable-video-diffusion-img2vid-xt", "svd_xt", f"{memory:.1f} GB VRAM meets conservative SVD-XT threshold; Wan tier skipped unless >=48 GB VRAM and >=100 GB free cache space"
    else:
        model, method, reason = None, "ffmpeg_animation", f"No compatible GPU/model tier (CUDA={available}, VRAM={memory:.1f} GB, free cache space={free_disk_gb} GB)"
    return {"cuda_available": available, "gpu_name": name, "gpu_memory_gb": memory, "free_cache_disk_gb": free_disk_gb, "selected_model": model, "method": method, "reason": reason}


def generate_wan_clip(image_path: str | Path, output_path: str | Path, prompt: str, frames: int = 49, fps: int = 16) -> Path:
    try:
        import torch
        from diffusers import WanImageToVideoPipeline
        from diffusers.utils import export_to_video, load_image
    except Exception as exc:
        raise VideoGenerationUnavailable("Wan image-to-video requires a Diffusers version exposing WanImageToVideoPipeline plus model dependencies.") from exc
    capability = video_capabilities()
    if not capability["cuda_available"] or capability["gpu_memory_gb"] < 48 or (capability.get("free_cache_disk_gb") or 0) < 100:
        raise VideoGenerationUnavailable(f"Wan 14B is disabled by conservative hardware preflight (requires >=48 GB VRAM and >=100 GB free cache space): {capability}")
    model_id = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"
    try:
        pipe = WanImageToVideoPipeline.from_pretrained(model_id, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
        try: pipe.vae.enable_tiling()
        except Exception: pass
        image = load_image(str(image_path)).convert("RGB")
        result = pipe(image=image, prompt=prompt, num_frames=frames, num_inference_steps=20, guidance_scale=5.0)
        frames_out = result.frames[0] if hasattr(result, "frames") else result.images[0]
        target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames_out, str(target), fps=fps)
        del pipe
        torch.cuda.empty_cache()
        return target
    except Exception as exc:
        raise VideoGenerationUnavailable(f"Wan I2V failed: {type(exc).__name__}: {exc}") from exc


def generate_svd_clip(image_path: str | Path, output_path: str | Path, prompt: str | None = None, frames: int = 25, fps: int = 7) -> Path:
    try:
        import torch
        from diffusers import StableVideoDiffusionPipeline
        from diffusers.utils import load_image, export_to_video
    except Exception as exc:
        raise VideoGenerationUnavailable("Stable Video Diffusion requires a compatible Diffusers install.") from exc
    capability = video_capabilities()
    if not capability["cuda_available"] or capability["gpu_memory_gb"] < 12:
        raise VideoGenerationUnavailable(f"SVD-XT is disabled by conservative hardware preflight: {capability}")
    model_id = "stabilityai/stable-video-diffusion-img2vid-xt"
    try:
        pipe = StableVideoDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float16, variant="fp16", low_cpu_mem_usage=True)
        pipe.enable_model_cpu_offload()
        try: pipe.unet.enable_forward_chunking()
        except Exception: pass
        image = load_image(str(image_path)).convert("RGB")
        # SVD is trained on landscape frames; final renderer crops to vertical after generation.
        image = image.resize((1024, 576))
        frames_out = pipe(image, num_frames=min(max(int(frames), 14), 25), decode_chunk_size=2, motion_bucket_id=127, noise_aug_strength=0.02).frames[0]
        target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames_out, str(target), fps=fps)
        del pipe
        torch.cuda.empty_cache()
        return target
    except Exception as exc:
        raise VideoGenerationUnavailable(f"SVD-XT failed: {type(exc).__name__}: {exc}") from exc


def generate_neural_clip(image_path: str | Path, output_path: str | Path, prompt: str | None = None, frames: int = 25, fps: int = 7) -> Path:
    capability = video_capabilities()
    if capability["method"] == "wan_i2v":
        return generate_wan_clip(image_path, output_path, prompt or "Cinematic continuous movement, natural motion, preserve the subject's identity and composition.", frames=max(frames, 25), fps=max(fps, 12))
    if capability["method"] == "svd_xt":
        return generate_svd_clip(image_path, output_path, prompt, frames=frames, fps=fps)
    raise VideoGenerationUnavailable(f"No compatible neural image-to-video model available. Use ffmpeg_animation fallback. Details: {capability}")


def animate_image_ffmpeg(image_path: str | Path, output_path: str | Path, duration: float = 3.0, width: int = 1080, height: int = 1920, fps: int = 30, movement: str = "push_in") -> Path:
    """Generate a real FFmpeg pan/zoom clip; never described as neural image-to-video."""
    if not shutil.which("ffmpeg"):
        raise VideoGenerationUnavailable("ffmpeg executable not found.")
    source = Path(image_path)
    if not source.exists():
        raise VideoGenerationUnavailable(f"Image asset not found: {source}")
    target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(round(duration * fps)))
    if movement in {"pan_left", "pan_right", "tilt_up", "tilt_down"}:
        # Slow crop-window movement; a padded high-resolution canvas provides movement without neural synthesis.
        x_expr = "(iw-iw/zoom)*(1-on/{frames})".format(frames=max(frames-1, 1)) if movement == "pan_right" else "(iw-iw/zoom)*on/{frames}".format(frames=max(frames-1, 1))
        y_expr = "(ih-ih/zoom)*(1-on/{frames})".format(frames=max(frames-1, 1)) if movement == "tilt_down" else "(ih-ih/zoom)*on/{frames}".format(frames=max(frames-1, 1))
    else:
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if movement in {"pull_out"}:
        z_expr = "max(1.0,1.08-0.08*on/{frames})".format(frames=max(frames-1, 1))
    else:
        z_expr = "min(zoom+0.0009,1.08)"
    vf = f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(source), "-vf", vf, "-t", f"{duration:.3f}", "-r", str(fps), "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoGenerationUnavailable(f"FFmpeg image animation failed: {proc.stderr[-2000:]}")
    return target


def generate_shot_clip(image_path: str | Path, output_path: str | Path, duration: float, prompt: str, fps: int = 7, width: int = 1080, height: int = 1920, try_neural: bool = True, movement: str = "push_in") -> dict[str, Any]:
    errors: list[str] = []
    if try_neural:
        try:
            target = generate_neural_clip(image_path, output_path, prompt=prompt, frames=25, fps=fps)
            return {"path": str(target), "method": "neural_image_to_video", "model": video_capabilities().get("selected_model"), "errors": errors}
        except Exception as exc:
            errors.append(f"Neural generation unavailable: {type(exc).__name__}: {exc}")
    target = animate_image_ffmpeg(image_path, output_path, duration=duration, width=width, height=height, fps=max(fps, 24), movement=movement)
    return {"path": str(target), "method": "ffmpeg_animation", "model": "FFmpeg", "reason": errors[-1] if errors else "Neural generation disabled by settings", "errors": errors}


def _valid_video_file(path: Path) -> bool:
    """Check a clip has a decodable video stream before accepting it as cached."""
    if not path.exists() or path.stat().st_size < 1024:
        return False
    if not shutil.which("ffprobe"):
        return True
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return False
        import json
        data = json.loads(proc.stdout)
        stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
        duration = float(data.get("format", {}).get("duration") or (stream or {}).get("duration") or 0)
        return bool(stream) and duration > 0
    except Exception:
        return False


def generate_clips_for_storyboard(shots: list[Any], try_neural: bool = True, max_neural_shots: int = 0, width: int = 1080, height: int = 1920, fallback_fps: int = 30) -> dict[str, Any]:
    """Generate shots, reuse valid cache first, and load the neural model only for pending shots.

    Cache metadata includes image digest, prompt, duration, target frame settings and the
    selected hardware/model tier. Moving to a better GPU therefore invalidates old
    FFmpeg fallback clips and permits a real neural generation retry on resume.
    """
    import hashlib, json
    capability = video_capabilities()
    selected_method = capability["method"] if try_neural else "ffmpeg_animation"
    neural_model = capability.get("selected_model") if try_neural else None
    eligible = [shot for shot in sorted(shots, key=lambda x: getattr(x, "sequence_number", 0)) if getattr(shot, "image_path", None)]
    image_errors = [getattr(shot, "shot_id", "unknown") for shot in shots if not getattr(shot, "image_path", None) or not Path(str(getattr(shot, "image_path", ""))).exists()]
    if image_errors:
        raise VideoGenerationUnavailable(f"Missing generated images for shots: {image_errors}")
    if not eligible:
        raise VideoGenerationUnavailable("No storyboard shots have generated image assets.")
    if max_neural_shots <= 0:
        max_neural_shots = len(eligible)

    expected_by_sid: dict[str, dict[str, Any]] = {}
    output_by_sid: dict[str, Path] = {}
    metadata_by_sid: dict[str, Path] = {}
    results: dict[str, Any] = {}
    pending: list[Any] = []
    warnings: list[str] = []

    # Pre-scan cache before model loading; a completed job should not download or load
    # multi-GB checkpoints just to discover that every clip already exists.
    for index, shot in enumerate(eligible):
        sid = str(getattr(shot, "shot_id", f"shot_{index+1:03d}"))
        image_path = Path(str(shot.image_path))
        output_path = Path(str(getattr(shot, "video_path", "") or image_path.parent.parent / "video_clips" / f"{sid}.mp4"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path = output_path.with_suffix(output_path.suffix + ".json")
        image_digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        requested = {
            "shot_id": sid,
            "image_sha256": image_digest,
            "prompt": str(getattr(shot, "visual_prompt", "")),
            "target_duration": round(float(shot.duration), 3),
            "requested_mode": "neural" if try_neural else "animation",
            "requested_capability": selected_method,
            "requested_model": neural_model,
            "width": int(width),
            "height": int(height),
            "fps": int(fallback_fps),
        }
        expected_by_sid[sid] = requested
        output_by_sid[sid] = output_path
        metadata_by_sid[sid] = metadata_path
        cache_hit = False
        if metadata_path.exists() and _valid_video_file(output_path):
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                cache_hit = all(meta.get(key) == val for key, val in requested.items())
                if cache_hit:
                    result = {**meta, "path": str(output_path), "cached": True}
                    results[sid] = result
                    shot.video_path = str(output_path)
                    shot.video_method = meta.get("method", "ffmpeg_animation")
            except Exception:
                cache_hit = False
        if not cache_hit:
            pending.append(shot)

    if not pending:
        methods = {sid: item.get("method") for sid, item in results.items()}
        fallback_count = sum(method == "ffmpeg_animation" for method in methods.values())
        if fallback_count:
            warnings.append("Reused cached FFmpeg animation clips. They are not neural image-to-video outputs.")
        return {
            "status": "success" if fallback_count == 0 and results else ("partial_success" if results else "failed"),
            "capabilities": capability,
            "neural_budget": 0,
            "neural_clips_generated": sum(method == "neural_image_to_video" for method in methods.values()),
            "clips": results,
            "warnings": warnings,
            "pipeline_load_error": None,
            "cached_all": True,
        }

    neural_budget = min(max_neural_shots, len(pending)) if selected_method in {"wan_i2v", "svd_xt"} and try_neural else 0
    pipe = None
    pipe_load_error: str | None = None
    method = selected_method
    if neural_budget:
        try:
            import torch
            if method == "wan_i2v":
                from diffusers import WanImageToVideoPipeline
                pipe = WanImageToVideoPipeline.from_pretrained(neural_model, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
                pipe.enable_model_cpu_offload()
                try:
                    pipe.vae.enable_tiling()
                except Exception:
                    pass
            elif method == "svd_xt":
                from diffusers import StableVideoDiffusionPipeline
                pipe = StableVideoDiffusionPipeline.from_pretrained(neural_model, torch_dtype=torch.float16, variant="fp16", low_cpu_mem_usage=True)
                pipe.enable_model_cpu_offload()
                try:
                    pipe.unet.enable_forward_chunking()
                except Exception:
                    pass
        except Exception as exc:
            pipe_load_error = f"{type(exc).__name__}: {exc}"
            pipe = None
            neural_budget = 0
            warnings.append(f"Neural video model could not be loaded; pending shots use labelled FFmpeg animation: {pipe_load_error}")

    neural_used = 0
    for index, shot in enumerate(pending):
        sid = str(getattr(shot, "shot_id", f"shot_{index+1:03d}"))
        image_path = Path(str(shot.image_path))
        output_path = output_by_sid[sid]
        metadata_path = metadata_by_sid[sid]
        expected = expected_by_sid[sid]
        use_neural = pipe is not None and neural_used < neural_budget
        result: dict[str, Any]
        if use_neural:
            try:
                import torch
                from diffusers.utils import load_image, export_to_video
                frames_n = max(14, min(49, int(getattr(shot, "video_settings", {}).get("frames", 25))))
                frame_rate = max(7, min(16, int(getattr(shot, "video_settings", {}).get("fps", 7))))
                if method == "wan_i2v":
                    image = load_image(str(image_path)).convert("RGB")
                    generated = pipe(image=image, prompt=expected["prompt"], num_frames=frames_n, num_inference_steps=20, guidance_scale=5.0)
                    frames_out = generated.frames[0] if hasattr(generated, "frames") else generated.images[0]
                else:
                    image = load_image(str(image_path)).convert("RGB").resize((1024, 576))
                    # SVD does not accept a text motion prompt; the prompt is preserved in sidecar metadata.
                    frames_out = pipe(image, num_frames=min(frames_n, 25), decode_chunk_size=2, motion_bucket_id=127, noise_aug_strength=0.02).frames[0]
                export_to_video(frames_out, str(output_path), fps=frame_rate)
                if not _valid_video_file(output_path):
                    raise VideoGenerationUnavailable("Neural pipeline returned without a valid, probeable video file.")
                neural_used += 1
                result = {**expected, "method": "neural_image_to_video", "model": neural_model, "model_api": method, "motion_prompt_conditioned": method == "wan_i2v", "status": "success", "errors": []}
                shot.video_method = "neural_image_to_video"
                shot.generation_status = "video_success"
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                warnings.append(f"{sid}: neural generation failed; used FFmpeg animation. {message}")
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                pipe = None
                result = {**expected, "method": "ffmpeg_animation", "model": "FFmpeg", "status": "fallback", "neural_error": message}
        else:
            reason = pipe_load_error or capability.get("reason") or "Neural generation disabled"
            result = {**expected, "method": "ffmpeg_animation", "model": "FFmpeg", "status": "fallback", "neural_error": reason}
        if result.get("method") == "ffmpeg_animation":
            movement = str(getattr(shot, "camera_movement", "slow push-in")).lower()
            movement_key = "pull_out" if "pull" in movement or "zoom out" in movement else "pan_left" if "left" in movement else "pan_right" if "right" in movement else "push_in"
            animate_image_ffmpeg(image_path, output_path, duration=float(shot.duration), width=width, height=height, fps=fallback_fps, movement=movement_key)
            shot.video_method = "ffmpeg_animation"
            shot.generation_status = "video_fallback"
            if not result.get("neural_error"):
                result["neural_error"] = "Neural generation disabled by configuration."
        if not _valid_video_file(output_path):
            raise VideoGenerationUnavailable(f"Clip for {sid} failed FFmpeg/video validation: {output_path}")
        shot.video_path = str(output_path)
        metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results[sid] = {**result, "path": str(output_path), "cached": False}

    if pipe is not None:
        del pipe
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    methods = {sid: item.get("method") for sid, item in results.items()}
    fallback_count = sum(method_name == "ffmpeg_animation" for method_name in methods.values())
    neural_count = sum(method_name == "neural_image_to_video" for method_name in methods.values())
    return {
        "status": "success" if results and fallback_count == 0 and not warnings and len(results) == len(eligible) else ("partial_success" if results else "failed"),
        "capabilities": capability,
        "neural_budget": neural_budget,
        "neural_clips_generated": neural_count,
        "clips": results,
        "warnings": warnings,
        "pipeline_load_error": pipe_load_error,
        "cached_all": False,
    }

