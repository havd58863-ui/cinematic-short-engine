from __future__ import annotations
from pathlib import Path
import torch

class ImageGenerationUnavailable(RuntimeError): pass

def environment_report() -> dict:
    available = torch.cuda.is_available()
    report = {"cuda_available": available, "device": "cuda" if available else "cpu", "gpu_name": None, "gpu_memory_gb": None}
    if available:
        report["gpu_name"] = torch.cuda.get_device_name(0)
        report["gpu_memory_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
    return report

def generate_image(prompt: str, negative_prompt: str, output_path: str | Path, model_id: str = "stabilityai/stable-diffusion-xl-base-1.0", seed: int = 42, width: int = 1024, height: int = 1024) -> Path:
    try:
        from diffusers import StableDiffusionXLPipeline
    except Exception as exc:
        raise ImageGenerationUnavailable("Diffusers/SDXL is unavailable. Install the image dependencies first.") from exc
    env = environment_report()
    dtype = torch.float16 if env["cuda_available"] else torch.float32
    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(model_id, torch_dtype=dtype, use_safetensors=True)
        if env["cuda_available"]:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cpu")
        generator = torch.Generator(device="cpu").manual_seed(seed)
        image = pipe(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height, generator=generator, num_inference_steps=25).images[0]
        path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True); image.save(path)
        del pipe
        if torch.cuda.is_available(): torch.cuda.empty_cache()
        return path
    except Exception as exc:
        raise ImageGenerationUnavailable(f"SDXL image generation failed on {env}: {type(exc).__name__}: {exc}") from exc
