from __future__ import annotations
from pathlib import Path
import subprocess, shutil

class VideoGenerationUnavailable(RuntimeError): pass

def generate_neural_clip(image_path: str | Path, output_path: str | Path, prompt: str | None = None, model_id: str = "stabilityai/stable-video-diffusion-img2vid-xt", frames: int = 25, fps: int = 7) -> Path:
    """Optional real neural I2V. SVD generates its documented clip format; final 9:16 crop is handled by the editor."""
    try:
        import torch
        from diffusers import StableVideoDiffusionPipeline
        from diffusers.utils import load_image, export_to_video
    except Exception as exc:
        raise VideoGenerationUnavailable("Diffusers Stable Video Diffusion dependencies are unavailable.") from exc
    if not torch.cuda.is_available():
        raise VideoGenerationUnavailable("Real neural I2V disabled: no CUDA GPU detected. Use the labelled FFmpeg fallback.")
    try:
        props = torch.cuda.get_device_properties(0)
        if props.total_memory < 10 * 1024**3:
            raise VideoGenerationUnavailable(f"GPU memory is {props.total_memory/1024**3:.1f} GB; configured SVD path requires a conservative 10 GB preflight threshold. Use fallback or a different tested model.")
        pipe = StableVideoDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float16, variant="fp16")
        pipe.enable_model_cpu_offload()
        pipe.unet.enable_forward_chunking()
        image = load_image(str(image_path)).convert("RGB")
        # The checkpoint is trained for a wide input. Keep the main subject centered; renderer crops to portrait later.
        image = image.resize((1024, 576))
        frames_out = pipe(image, num_frames=frames, decode_chunk_size=2, motion_bucket_id=127, noise_aug_strength=0.02).frames[0]
        path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
        export_to_video(frames_out, str(path), fps=fps)
        del pipe; torch.cuda.empty_cache()
        return path
    except VideoGenerationUnavailable:
        raise
    except Exception as exc:
        raise VideoGenerationUnavailable(f"Neural I2V generation failed: {type(exc).__name__}: {exc}") from exc

def animate_image_ffmpeg(image_path: str | Path, output_path: str | Path, duration: float = 3.0, width: int = 1080, height: int = 1920, fps: int = 30) -> Path:
    """Actual FFmpeg pan/zoom animation. This is not neural video generation."""
    if not shutil.which("ffmpeg"):
        raise VideoGenerationUnavailable("ffmpeg executable not found.")
    path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(duration * fps))
    # Fit then gently zoom using a centered portrait canvas; crop is deterministic.
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},zoompan=z='min(zoom+0.0007,1.08)':d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
    command = ["ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-vf", vf, "-t", str(duration), "-r", str(fps), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoGenerationUnavailable(f"FFmpeg image animation failed: {proc.stderr[-1500:]}")
    return path
