# License and commercial-use review

This project code is intended to be released under the MIT License (see `LICENSE`). That does not grant rights to third-party models, weights, datasets, voices, stock media, or provider services.

Before monetized publication, review the current model card and terms for the exact versions you downloaded:

- Stable Diffusion XL Base 1.0: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- Stable Diffusion 1.5 fallback: https://huggingface.co/runwayml/stable-diffusion-v1-5
- Stable Video Diffusion XT: https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt — the current model card points to the Stable Video Diffusion Community License; confirm the exact license file for the revision you download and your monetization context.
- Wan 2.1 I2V: https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P-Diffusers — the model card lists Apache-2.0; model repository size is very large, so the runtime gates on >=48 GB VRAM and >=100 GB free cache storage before selecting it.
- Kokoro: https://github.com/hexgrad/kokoro
- IP-Adapter implementation: https://github.com/tencent-ailab/IP-Adapter
- IP-Adapter weights: https://huggingface.co/h94/IP-Adapter
- Pixabay Content License summary: https://pixabay.com/service/license-summary/
- Pexels license: https://www.pexels.com/license/
- DDGS, Trafilatura, pytrends, Whisper, Diffusers, FFmpeg, and Ollama each retain their own software licenses.

The pipeline records model IDs and fallback methods. It does **not** claim it has legally certified any model or asset for commercial use. Review the current terms when running the notebook; model-card and service terms can change. Stock fallback assets include creator/source URLs so they can be audited. Do not redistribute stock images as a standalone asset pack.
