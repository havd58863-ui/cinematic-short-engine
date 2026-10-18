from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json, uuid, os, shutil, hashlib

from .config import Settings
from .qa import write_job_report
from research.engine import research_topic
from research.idea_scoring import rank_topic_results
from director.scriptwriter_adapter import write_script, ScriptwriterUnavailable
from director.script_analysis import analyze_script
from director.storyboard import create_storyboard
from director.shot_planner import plan_asset_paths
from director.continuity_manager import build_continuity_report
from director.quality_control import write_quality_report
from generation.image_generation import generate_images_for_storyboard, environment_report, ImageGenerationUnavailable
from generation.image_to_video import generate_clips_for_storyboard, VideoGenerationUnavailable
from generation.voice_generation import generate_kokoro_paragraphs, VoiceGenerationUnavailable
from generation.subtitles import transcribe_to_subtitles, SubtitleGenerationUnavailable
from editing.audio_mixer import concatenate_audio_segments, normalize_audio, validate_audio, generate_procedural_sfx_track
from editing.render_video import render_video, validate_video, analyze_black_and_silence, RenderError
from editing.kinocut_adapter import write_kinocut_report

FOLDERS = ("research", "script", "storyboard", "references", "images", "video_clips", "audio", "subtitles", "intermediate")

class PipelineFailure(RuntimeError):
    pass


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _safe_job_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]


def _manifest_update(job: Path, manifest: dict[str, Any], stage: str, status: str, details: dict[str, Any] | None = None) -> None:
    manifest.setdefault("stages", {})[stage] = {"status": status, "updated_at_utc": datetime.now(timezone.utc).isoformat(), "details": details or {}}
    if status in {"success", "partial_success"}:
        completed = manifest.setdefault("completed_stages", [])
        if stage not in completed:
            completed.append(stage)
    manifest["current_stage"] = stage
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(job / "run_manifest.json", manifest)


def _topic_from_script(script: str) -> str:
    for line in script.strip().splitlines():
        line = line.strip()
        if line:
            return line[:120].rstrip(".!? ") or "User-provided TikTok script"
    return "User-provided TikTok script"


def _load_or_create_script(job: Path, topic: str, supplied_script: str | None, sources: list[dict[str, Any]], seconds: int, model: str | None = None) -> tuple[str, bool]:
    script_path = job / "script" / "approved_script.txt"
    if supplied_script is not None:
        script = supplied_script.strip()
        if not script:
            raise PipelineFailure("The supplied script file is empty.")
        script_path.write_text(script + "\n", encoding="utf-8")
        return script, True
    if script_path.exists() and script_path.read_text(encoding="utf-8").strip():
        return script_path.read_text(encoding="utf-8").strip(), False
    script = write_script(topic, sources, seconds=seconds, model=model).strip()
    if not script:
        raise PipelineFailure("Scriptwriter returned an empty script.")
    script_path.write_text(script + "\n", encoding="utf-8")
    return script, False


def run_job(topic: str | None = None, script: str | None = None, settings: Settings | None = None, resume_job: str | Path | None = None, run_media: bool = True) -> Path:
    """Execute a new end-to-end job, or resume one from its stored artifacts.

    Hard failures create a failed quality report and preserve completed assets for resume.
    Neural video can fall back to explicitly labelled FFmpeg animation; it is never misreported.
    """
    settings = settings or Settings.from_env()
    if resume_job:
        candidate = Path(resume_job)
        job = candidate if candidate.exists() and candidate.is_dir() else settings.output_root / str(resume_job)
        if not job.exists():
            raise PipelineFailure(f"Resume job directory does not exist: {job}")
        job_id = job.name
    else:
        job_id = _safe_job_id()
        job = settings.output_root / job_id
    job.mkdir(parents=True, exist_ok=True)
    for name in FOLDERS:
        (job / name).mkdir(parents=True, exist_ok=True)
    settings.model_cache_root.mkdir(parents=True, exist_ok=True)
    # Set model cache before Diffusers/Hugging Face loads any checkpoint.
    os.environ.setdefault("HF_HOME", str(settings.model_cache_root / "huggingface"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(settings.model_cache_root / "huggingface" / "hub"))
    env_report = environment_report()
    manifest_path = job / "run_manifest.json"
    if manifest_path.exists():
        try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception: manifest = {}
    else:
        manifest = {}
    manifest.update({
        "job_id": job_id,
        "created_at_utc": manifest.get("created_at_utc") or datetime.now(timezone.utc).isoformat(),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_region": settings.target_region,
        "target_audience": settings.target_audience,
        "settings": settings.model_dump(mode="json"),
        "runtime_environment": env_report,
        "status": "running",
        "completed_stages": manifest.get("completed_stages", []),
        "limitations": [
            "TikTok Creative Center metrics are only reported when actually accessible and retrieved.",
            "Heuristic idea scores do not predict virality or retention.",
            "A final MP4 may use FFmpeg animation for some shots when neural image-to-video is unavailable or fails.",
        ],
    })
    _write_json(manifest_path, manifest)
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        _manifest_update(job, manifest, "preflight", "success", env_report)
        checks.append({"name": "runtime preflight", "status": "success", "detail": f"Python {env_report.get('python')}; CUDA={env_report.get('cuda_available')}; GPU={env_report.get('gpu_name')}; FFmpeg={bool(env_report.get('ffmpeg'))}."})

        effective_topic = topic.strip() if topic and topic.strip() else (str(manifest.get("topic")).strip() if resume_job and manifest.get("topic") else (_topic_from_script(script) if script else None))
        existing_research = job / "research" / "research_report.json"
        if existing_research.exists() and resume_job:
            research_report = json.loads(existing_research.read_text(encoding="utf-8"))
        else:
            research_report = research_topic(effective_topic, max_results=settings.research_max_results, region=settings.target_region, extract_top_n=settings.extract_top_sources, output_dir=job / "research")
        sources = research_report.get("sources", [])
        candidates = research_report.get("candidate_ideas", [])
        if effective_topic is None:
            ranked = rank_topic_results(candidates)
            if not ranked:
                raise PipelineFailure("Automatic topic selection failed: no grounded candidate ideas were returned by accessible public research. Enter a topic or retry when web research is available.")
            effective_topic = ranked[0]["title"]
        manifest["topic"] = effective_topic
        manifest["candidate_ideas"] = candidates[:8]
        _manifest_update(job, manifest, "research", "success" if sources else "partial_success", {"source_count": len(sources), "candidate_count": len(candidates), "topic_selected": effective_topic})
        checks.append({"name": "public research and idea selection", "status": "success" if sources else "warning", "detail": f"{len(sources)} accessible sources; {len(candidates)} candidates; selected: {effective_topic}."})
        if not sources:
            warnings.append("Research produced no accessible source results. No external metric or factual claim was fabricated.")

        # Competitor and trend metadata are already saved by research engine. Script can be supplied without rewriting.
        script_text, supplied = _load_or_create_script(job, effective_topic, script, sources, settings.video_seconds, settings.omniroute_model)
        analysis = analyze_script(script_text, target_seconds=settings.video_seconds)
        _write_json(job / "script" / "script_analysis.json", analysis)
        _manifest_update(job, manifest, "script", "success", {"supplied_by_user": supplied, "word_count": analysis["word_count"], "estimated_duration_seconds": analysis["estimated_duration_seconds"]})
        checks.append({"name": "scriptwriting and pacing analysis", "status": "success", "detail": f"{analysis['word_count']} words; estimated {analysis['estimated_duration_seconds']} seconds; user script preserved={supplied}."})
        if analysis.get("pacing_warning"):
            warnings.append(analysis["pacing_warning"])
        if analysis.get("hook_warning"):
            warnings.append(analysis["hook_warning"])
        for check_name, check_passed in analysis.get("retention_structure_checklist", {}).items():
            checks.append({"name": f"Script structure: {check_name}", "status": "success" if check_passed else "warning", "detail": "Heuristic script check; human review may still be needed."})
            if not check_passed:
                warnings.append(f"Script review requested: retention-structure heuristic `{check_name}` did not pass.")

        board_path = job / "storyboard" / "storyboard.json"
        if board_path.exists() and resume_job and not script:
            from director.storyboard import Storyboard
            board = Storyboard.model_validate_json(board_path.read_text(encoding="utf-8"))
            board.validate_timeline()
        else:
            board = create_storyboard(script_text, title=effective_topic, seconds=settings.video_seconds, model=settings.omniroute_model)
        board = plan_asset_paths(board, job)
        board_path.write_text(board.model_dump_json(indent=2), encoding="utf-8")
        continuity = build_continuity_report(board, job)
        _write_json(job / "storyboard" / "continuity_report.json", continuity)
        _manifest_update(job, manifest, "storyboard", "success", {"shot_count": len(board.shots), "duration_seconds": board.shots[-1].end_seconds, "continuity_passed": continuity["passed"]})
        checks.append({"name": "storyboard schema and timeline", "status": "success", "detail": f"{len(board.shots)} ordered shots; visual identity recorded; no overlap/gap validation errors."})
        if continuity["missing_reference_assets"]:
            warnings.append(f"{len(continuity['missing_reference_assets'])} reference assets are missing; prompt-based continuity will be used unless supplied.")

        if not run_media:
            manifest["status"] = "partial_success"
            manifest["current_stage"] = "planning_complete"
            manifest["completed_stages"] = ["preflight", "research", "script", "storyboard"]
            _write_json(manifest_path, manifest)
            write_quality_report(job, "partial_success", "Planning completed. Image/audio/video generation and final rendering were deliberately not run in plan-only mode.", checks, warnings, {"job_id": job_id, "topic": effective_topic})
            return job

        # Images: one model instance for the whole storyboard; cached files are not regenerated when hashes match.
        refs = job / "references" / "character_reference.png"
        reference = refs if refs.is_file() else None
        # Persist reference sheets by stable visual-identity hash across jobs.
        persistent_reference_dir = settings.output_root.parent / "character_references"
        identity_key = hashlib.sha256((board.visual_identity or effective_topic).strip().encode("utf-8")).hexdigest()[:16]
        persistent_reference = persistent_reference_dir / f"{identity_key}.png"
        reference_prompt = None
        if board.character_reference_required:
            reference_prompt = (
                "Create a professional cinematic character/subject reference sheet for consistent later image generation. "
                "Show the same single clearly identifiable subject in front view, three-quarter view, and profile view; "
                "keep face, body proportions, age, hair, outfit, accessories, and distinctive silhouette consistent. "
                "Use a plain neutral studio background, even soft lighting, a full subject view, high-detail realistic textures, "
                "no labels, no captions, no text, no watermark, no unrelated people. Visual identity: "
                + (board.visual_identity or effective_topic)
            )
        _manifest_update(job, manifest, "images", "running", {"character_reference_required": board.character_reference_required})
        image_result: dict[str, Any]
        diffusion_error = None
        try:
            image_result = generate_images_for_storyboard(
                board.shots,
                cache_root=settings.model_cache_root,
                primary_model=settings.image_model,
                fallback_model=settings.image_fallback_model,
                use_ip_adapter=settings.use_ip_adapter,
                character_reference=reference,
                reference_sheet_prompt=reference_prompt,
                reference_sheet_path=persistent_reference if board.character_reference_required else None,
            )
            if board.character_reference_required and image_result.get("reference_sheet_path"):
                generated_reference = Path(image_result["reference_sheet_path"])
                if generated_reference.is_file():
                    refs.parent.mkdir(parents=True, exist_ok=True)
                    if generated_reference.resolve() != refs.resolve():
                        shutil.copy2(generated_reference, refs)
                    for shot in board.shots:
                        if not shot.reference_assets:
                            shot.reference_assets = [str(refs)]
                    board_path.write_text(board.model_dump_json(indent=2), encoding="utf-8")
                else:
                    warnings.append("A recurring subject was identified but its reference sheet was not created; consistent textual prompts are retained.")
            elif board.character_reference_required:
                warnings.append("A recurring subject was identified but its reference sheet was unavailable; consistent textual prompts are retained.")
        except ImageGenerationUnavailable as exc:
            diffusion_error = f"{type(exc).__name__}: {exc}"
            image_result = {"status": "unavailable", "selected_model": None, "error": diffusion_error, "images": {}, "errors": {}}
        if image_result.get("cached_stock_ids"):
            prior_stock_report = job / "images" / "stock_fallback_report.json"
            try:
                stock_details = json.loads(prior_stock_report.read_text(encoding="utf-8")) if prior_stock_report.is_file() else {"status": "success", "method": "stock_image_fallback", "assets": {}, "warning": "Cached stock assets; original provider report was not present."}
            except Exception:
                stock_details = {"status": "success", "method": "stock_image_fallback", "assets": {}, "warning": "Cached stock assets; prior provider report could not be parsed."}
            image_result["stock_fallback"] = stock_details
            image_result["status"] = "partial_success"
            if not any("stock fallback" in item.lower() for item in warnings):
                warnings.append("Previously cached stock images were reused; they are provider-sourced, not AI-generated. See images/stock_fallback_report.json for available provenance.")
        if board.character_reference_required and not (refs.is_file() and refs.stat().st_size > 1024):
            warning = "A recurring subject needs a reference sheet, but a validated sheet was not available; prompts retain the visual identity, with no claim of perfect character consistency."
            if warning not in warnings:
                warnings.append(warning)
        missing_images = [shot.shot_id for shot in board.shots if not shot.image_path or not Path(shot.image_path).exists()]
        if missing_images:
            try:
                from generation.stock_images import generate_stock_fallback
                stock_report = generate_stock_fallback([shot for shot in board.shots if shot.shot_id in missing_images], report_path=job / "images" / "stock_fallback_report.json")
                image_result["stock_fallback"] = stock_report
                image_result["images"] = {**image_result.get("images", {}), **{sid: item.get("path") for sid, item in stock_report.get("assets", {}).items()}}
                image_result["status"] = "partial_success" if image_result.get("selected_model") else stock_report.get("status", "failed")
                if stock_report.get("assets"):
                    warnings.append("Some images came from optional Pixabay/Pexels stock fallback, not AI generation; provenance is in images/stock_fallback_report.json.")
            except Exception as stock_exc:
                image_result["stock_fallback_error"] = f"{type(stock_exc).__name__}: {stock_exc}"
        missing_images = [shot.shot_id for shot in board.shots if not shot.image_path or not Path(shot.image_path).exists()]
        _write_json(job / "images" / "generation_report.json", image_result)
        board_path.write_text(board.model_dump_json(indent=2), encoding="utf-8")
        if missing_images:
            raise PipelineFailure(f"Image stage could not supply real assets for every required shot: {missing_images}. Diffusion error={diffusion_error}; stock fallback details are in images/stock_fallback_report.json if a provider key was configured.")
        checks.append({"name": "Diffusers image generation or disclosed stock fallback", "status": "success" if not image_result.get("stock_fallback") else "warning", "detail": f"{len(image_result.get('images', {}))} validated images; model={image_result.get('selected_model') or 'none (stock fallback)'}; stock fallback used={bool(image_result.get('stock_fallback'))}."})
        _manifest_update(job, manifest, "images", image_result["status"], image_result)
        if image_result.get("ip_adapter_status", "not_requested").startswith("unavailable"):
            warnings.append("IP-Adapter was unavailable; reference-image continuity was not applied to the image model.")

        # Narration: separate paragraph files and a combined, normalized narration track.
        _manifest_update(job, manifest, "narration", "running", {})
        paragraphs = analysis.get("narration_paragraphs", []) or [script_text]
        voice_result = generate_kokoro_paragraphs(paragraphs, job / "audio" / "segments", voice=settings.tts_voice, language_code=settings.tts_language_code, speed=settings.tts_speed)
        (job / "audio" / "narration_segments.json").write_text(json.dumps(voice_result, ensure_ascii=False, indent=2), encoding="utf-8")
        combined = concatenate_audio_segments(voice_result["segments"], job / "audio" / "narration.wav", pause_seconds=0.18)
        narration = normalize_audio(combined, job / "audio" / "narration_normalized.wav")
        audio_report = validate_audio(narration)
        _write_json(job / "audio" / "audio_validation.json", audio_report)
        checks.append({"name": "Kokoro narration", "status": "success", "detail": f"Generated {len(voice_result['segments'])} paragraphs; final narration {audio_report['duration_seconds']:.2f}s, {audio_report['sample_rate']} Hz."})
        _manifest_update(job, manifest, "narration", "success", {"voice": settings.tts_voice, "path": str(narration), **audio_report})

        # Match the visual timeline to the actual generated narration duration to avoid truncating speech.
        actual_audio_duration = float(audio_report["duration_seconds"])
        original_timeline_duration = float(max(shot.end_seconds for shot in board.shots))
        if original_timeline_duration > 0 and abs(actual_audio_duration - original_timeline_duration) > 0.5:
            factor = actual_audio_duration / original_timeline_duration
            for shot in board.shots:
                shot.start_seconds = round(shot.start_seconds * factor, 3)
                shot.end_seconds = round(shot.end_seconds * factor, 3)
            board.target_duration_seconds = round(actual_audio_duration, 3)
            board.validate_timeline()
            board_path.write_text(board.model_dump_json(indent=2), encoding="utf-8")
            warnings.append(f"Visual shot timings were scaled by {factor:.3f} to match the measured narration duration ({actual_audio_duration:.2f}s); review pacing if the change is large.")
            _manifest_update(job, manifest, "storyboard_retiming", "success", {"original_timeline_seconds": original_timeline_duration, "measured_narration_seconds": actual_audio_duration, "scale_factor": factor})

        # Subtitle times are transcribed from the actual generated narration, not guessed from word counts.
        _manifest_update(job, manifest, "subtitles", "running", {})
        subtitle_result = transcribe_to_subtitles(narration, job / "subtitles" / "captions.srt", ass_path=job / "subtitles" / "captions.ass", model_name=settings.whisper_model, approved_script=script_text, download_root=settings.model_cache_root / "whisper")
        _write_json(job / "subtitles" / "subtitle_report.json", subtitle_result)
        checks.append({"name": "Whisper speech transcription and captions", "status": "success", "detail": f"{subtitle_result['phrase_count']} timed caption phrases from actual audio using {settings.whisper_model}."})
        _manifest_update(job, manifest, "subtitles", "success", subtitle_result)

        # Real neural video is attempted according to resource capability; FFmpeg fallback is explicitly labelled.
        _manifest_update(job, manifest, "video_clips", "running", {})
        video_result = generate_clips_for_storyboard(
            board.shots,
            try_neural=settings.enable_real_image_to_video,
            max_neural_shots=settings.max_neural_video_shots,
            width=settings.width,
            height=settings.height,
            fallback_fps=settings.fps,
        )
        _write_json(job / "video_clips" / "generation_report.json", video_result)
        if video_result["warnings"]:
            warnings.extend(video_result["warnings"])
        if video_result.get("clips") and any(x.get("method") == "ffmpeg_animation" for x in video_result["clips"].values()):
            warnings.append("One or more shots use FFmpeg image animation. This is not AI image-to-video generation.")
        board_path.write_text(board.model_dump_json(indent=2), encoding="utf-8")
        checks.append({"name": "image-to-video / FFmpeg clip generation", "status": "success" if video_result["clips"] else "failed", "detail": f"{video_result.get('neural_clips_generated', 0)} neural clips; {sum(x.get('method') == 'ffmpeg_animation' for x in video_result['clips'].values())} FFmpeg animation clips."})
        _manifest_update(job, manifest, "video_clips", video_result["status"], video_result)

        shot_media = []
        for shot in sorted(board.shots, key=lambda item: item.sequence_number):
            if not shot.video_path or not Path(shot.video_path).exists():
                raise PipelineFailure(f"Required final shot clip is missing for {shot.shot_id}")
            shot_media.append((shot.video_path, float(shot.duration)))

        music = settings.music_file if settings.music_file and settings.music_file.exists() else None
        if settings.music_file and not music:
            warnings.append(f"Configured music file does not exist and was not used: {settings.music_file}")
        _manifest_update(job, manifest, "sound_effects", "running", {})
        total_visual_duration = max(float(shot.end_seconds) for shot in board.shots)
        sfx_result = generate_procedural_sfx_track(board.shots, total_visual_duration, job / "audio" / "sfx")
        _write_json(job / "audio" / "sfx" / "sfx_report.json", sfx_result)
        sfx_path = sfx_result.get("track_path")
        if sfx_result.get("errors"):
            warnings.append(f"{len(sfx_result['errors'])} procedural sound-effect event(s) could not be generated; see audio/sfx/sfx_report.json.")
        checks.append({"name": "Storyboard-timed procedural sound effects", "status": "success" if sfx_path else ("skipped" if sfx_result.get("status") == "no_supported_cues" else "warning"), "detail": f"{len(sfx_result.get('effects', []))} synthesized cues; track={'available' if sfx_path else 'not available'}; source=FFmpeg lavfi."})
        _manifest_update(job, manifest, "sound_effects", "success" if sfx_path else sfx_result.get("status", "skipped"), sfx_result)
        _manifest_update(job, manifest, "render", "running", {"shot_count": len(shot_media), "target_duration_seconds": sum(x[1] for x in shot_media)})
        final_path = job / "final_video.mp4"
        rendered = render_video(shot_media, str(narration), final_path, subtitles_path=subtitle_result["ass"], music_path=str(music) if music else None, sfx_path=str(sfx_path) if sfx_path else None, width=settings.width, height=settings.height, fps=settings.fps, music_volume=settings.music_volume)
        validation = validate_video(rendered, expected_width=settings.width, expected_height=settings.height, require_audio=True)
        _write_json(job / "intermediate" / "final_video_validation.json", validation)
        checks.append({"name": "FFmpeg final rendering and ffprobe validation", "status": "success", "detail": f"{validation['width']}x{validation['height']} H.264 MP4; {validation['duration_seconds']:.2f}s; audio={validation['has_audio']}."})
        if settings.run_black_silence_checks:
            diagnostic = analyze_black_and_silence(rendered)
            _write_json(job / "intermediate" / "black_silence_diagnostics.json", diagnostic)
            warnings.extend(diagnostic.get("warnings", []))

        # Kinocut is an optional second-line check; the required FFmpeg/ffprobe
        # validation above remains authoritative and always runs.
        kinocut_result = write_kinocut_report(rendered, job / "intermediate" / "kinocut_qc.json")
        kinocut_status = kinocut_result.get("status", "unknown")
        checks.append({
            "name": "Kinocut optional diagnostics",
            "status": "skipped" if kinocut_status == "not_installed" else ("success" if kinocut_status == "success" else "warning"),
            "detail": "Kinocut CLI diagnostic report saved to intermediate/kinocut_qc.json; see report for individual command output."
                      if kinocut_status != "not_installed" else "Kinocut is not installed in this runtime; mandatory FFmpeg/ffprobe checks passed independently.",
        })
        if kinocut_status not in {"success", "not_installed"}:
            warnings.append("Optional Kinocut diagnostics did not fully pass; inspect intermediate/kinocut_qc.json. Mandatory FFmpeg/ffprobe validation remains available.")

        # Fully successful means all required stages completed and no declared fallback/quality warning remains.
        used_fallback = any(x.get("method") == "ffmpeg_animation" for x in video_result["clips"].values())
        overall = "success" if not used_fallback and not warnings else "partial_success"
        manifest.update({
            "status": overall,
            "current_stage": "complete",
            "completed_stages": ["preflight", "research", "script", "storyboard", "images", "narration", "subtitles", "video_clips", "render", "quality_control"],
            "final_video": str(rendered),
            "video_methods": {sid: clip.get("method") for sid, clip in video_result["clips"].items()},
            "selected_image_model": image_result.get("selected_model"),
            "neural_video_model": video_result.get("capabilities", {}).get("selected_model"),
            "warnings": warnings,
        })
        _write_json(manifest_path, manifest)
        write_quality_report(job, overall, "Production rendered and technical validation completed." if overall == "success" else "A playable MP4 was rendered, but one or more stages used a documented fallback or raised a review warning.", checks, warnings, {"job_id": job_id, "topic": effective_topic, "final_video": str(rendered), "video_methods": manifest["video_methods"], "runtime_environment": env_report})
        return job
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(manifest_path, manifest)
        write_quality_report(job, "failed", f"Pipeline stopped at `{manifest.get('current_stage','unknown')}`: {type(exc).__name__}: {exc}. Completed assets are preserved for resume.", checks, warnings, {"job_id": job_id, "failure": manifest["failure"], "current_stage": manifest.get("current_stage")})
        raise


def run_planning_job(topic: str | None = None, script: str | None = None, settings: Settings | None = None, research_max: int = 6) -> Path:
    """Compatibility API for users who explicitly want research/script/storyboard only."""
    if settings is None:
        settings = Settings.from_env()
    settings.research_max_results = research_max
    return run_job(topic=topic, script=script, settings=settings, run_media=False)
