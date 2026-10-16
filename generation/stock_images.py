"""Optional visual fallback via Pixabay/Pexels APIs when diffusion hardware is unavailable.

Images are explicitly labelled stock assets in the job manifest; they are never claimed to be AI-generated.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen
from typing import Any
import json, os, re, time

class StockImageUnavailable(RuntimeError):
    pass


def _fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "TikTokAIDirector/1.0", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_image(url: str, output_path: Path) -> None:
    try:
        from PIL import Image
        from io import BytesIO
    except Exception as exc:
        raise StockImageUnavailable("Pillow is required to validate/download stock images.") from exc
    request = Request(url, headers={"User-Agent": "TikTokAIDirector/1.0"})
    with urlopen(request, timeout=30) as response:
        content = response.read()
    if len(content) < 512:
        raise StockImageUnavailable("Stock provider returned an empty or implausibly small image.")
    try:
        im = Image.open(BytesIO(content)).convert("RGB")
        if im.width < 320 or im.height < 320:
            raise StockImageUnavailable(f"Stock image is too small ({im.width}x{im.height}).")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(output_path, format="PNG", optimize=True)
    except StockImageUnavailable:
        raise
    except Exception as exc:
        raise StockImageUnavailable(f"Downloaded asset is not a valid image: {type(exc).__name__}: {exc}") from exc


def search_pixabay(query: str, api_key: str, orientation: str = "vertical") -> dict[str, Any]:
    params = urlencode({"key": api_key, "q": query[:100], "image_type": "photo", "orientation": orientation, "safesearch": "true", "per_page": 8, "editors_choice": "false"})
    data = _fetch_json(f"https://pixabay.com/api/?{params}")
    hits = data.get("hits") or []
    if not hits:
        raise StockImageUnavailable(f"Pixabay returned no image results for query: {query}")
    hit = max(hits, key=lambda item: int(item.get("imageWidth", 0)) * int(item.get("imageHeight", 0)))
    return {"provider": "Pixabay", "image_url": hit.get("largeImageURL") or hit.get("webformatURL"), "source_page": hit.get("pageURL"), "creator": hit.get("user"), "license_reference": "https://pixabay.com/service/license-summary/"}


def search_pexels(query: str, api_key: str) -> dict[str, Any]:
    data = _fetch_json(f"https://api.pexels.com/v1/search?{urlencode({'query': query[:100], 'per_page': 8, 'orientation': 'portrait'})}", headers={"Authorization": api_key})
    photos = data.get("photos") or []
    if not photos:
        raise StockImageUnavailable(f"Pexels returned no image results for query: {query}")
    photo = max(photos, key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)))
    sources = photo.get("src") or {}
    return {"provider": "Pexels", "image_url": sources.get("large2x") or sources.get("large") or sources.get("original"), "source_page": photo.get("url"), "creator": (photo.get("photographer") or ""), "license_reference": "https://www.pexels.com/license/"}


def query_from_prompt(prompt: str) -> str:
    # Keep search terms descriptive, not entire prompt or negative prompts.
    text = re.sub(r"[^a-zA-Z0-9 ,'-]", " ", prompt)
    words = [w for w in text.replace(",", " ").split() if len(w) > 2]
    return " ".join(words[:10])[:90] or "cinematic documentary scene"


def generate_stock_fallback(shots: list[Any], report_path: str | Path | None = None) -> dict[str, Any]:
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
    pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not pixabay_key and not pexels_key:
        raise StockImageUnavailable("No diffusion model generated the required images and neither PIXABAY_API_KEY nor PEXELS_API_KEY is configured. Add a provider key as a Colab Secret or enable a compatible GPU; no fake images were created.")
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for index, shot in enumerate(shots):
        path = Path(str(getattr(shot, "image_path", "") or f"images/{getattr(shot,'shot_id',index)}.png"))
        if path.exists() and path.stat().st_size > 1024:
            try:
                from PIL import Image
                with Image.open(path) as im: im.verify()
                results[str(shot.shot_id)] = {"path": str(path), "provider": "existing_cached_asset", "source_page": None, "method": "cached_asset"}
                continue
            except Exception:
                pass
        query = query_from_prompt(str(getattr(shot, "visual_prompt", "")))
        errors_for_shot = []
        choices = []
        if pixabay_key:
            choices.append(("Pixabay", lambda: search_pixabay(query, pixabay_key)))
        if pexels_key:
            choices.append(("Pexels", lambda: search_pexels(query, pexels_key)))
        done = False
        for provider, search_fn in choices:
            try:
                asset = search_fn()
                if not asset.get("image_url"):
                    raise StockImageUnavailable("Provider returned no direct image URL.")
                _download_image(asset["image_url"], path)
                asset.update({"path": str(path), "method": "stock_image_fallback", "search_query": query, "asset_retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                results[str(shot.shot_id)] = asset
                shot.image_path = str(path)
                shot.generation_status = "stock_image_fallback"
                done = True
                break
            except Exception as exc:
                errors_for_shot.append(f"{provider}: {type(exc).__name__}: {exc}")
        if not done:
            errors[str(shot.shot_id)] = "; ".join(errors_for_shot) or "No configured stock provider."
    report = {"status": "success" if results and not errors else ("partial_success" if results else "failed"), "method": "stock_image_fallback", "assets": results, "errors": errors, "warning": "These are provider-sourced stock images, not AI-generated images. Review source/creator and each provider's license before commercial use."}
    if report_path:
        out = Path(report_path); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
