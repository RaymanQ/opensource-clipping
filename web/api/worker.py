"""
web.api.worker — Background task runner for the clipping pipeline.

Wraps ``clipping.runner.run_pipeline()`` in an asyncio task with
progress reporting via the job store.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import shutil
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .config_adapter import build_config_from_payload
from .models import ClipDetail, JobStatus
from . import store

# Semaphore to control max concurrent jobs
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "1"))
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

# Store settings overrides (API keys etc.) in memory
_settings_env: dict[str, str] = {}


def set_settings_env(env: dict[str, str]) -> None:
    """Update runtime settings environment."""
    global _settings_env
    _settings_env.update(env)


def get_settings_env() -> dict[str, str]:
    """Get current settings environment."""
    return dict(_settings_env)


def _run_pipeline_sync(job_id: str, payload: dict) -> None:
    """
    Run the clipping pipeline synchronously (called from thread pool).

    This function updates the job store at each pipeline step so the
    frontend can poll or receive SSE progress updates.
    """
    try:
        # Build config from API payload
        cfg = build_config_from_payload(
            payload, job_id, env_overrides=_settings_env
        )

        if not shutil.which("ffmpeg"):
            store.set_error(job_id, "FFmpeg tidak ditemukan pada backend.")
            return
        if cfg.whisper_device == "cuda":
            try:
                import torch
                cuda_ready = torch.cuda.is_available()
            except ImportError:
                cuda_ready = False
            if not cuda_ready:
                store.set_error(job_id, "Whisper CUDA dipilih tetapi CUDA tidak tersedia. Pilih auto atau cpu.")
                return

        # Story mode is a separate, non-Gemini pipeline.
        if cfg.story_mode:
            # Resolve uploaded local Story sources by asset ID; never trust paths from JSON.
            if payload.get("sources_json_filename"):
                with open(cfg.sources_json_path, "r", encoding="utf-8") as handle:
                    sources_doc = json.load(handle)
                uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads"))
                for source in sources_doc.get("sources", []):
                    if source.get("platform") != "local":
                        continue
                    asset_id = source.get("local_path", "")
                    if not asset_id or os.path.basename(asset_id) != asset_id or ".." in asset_id:
                        raise ValueError("Local Story sources must use an uploaded video asset ID")
                    resolved = os.path.join(uploads_dir, asset_id)
                    if not os.path.isfile(resolved):
                        raise ValueError(f"Uploaded Story source not found: {asset_id}")
                    source["local_path"] = resolved
                resolved_sources = os.path.join(cfg.outputs_dir, "sources.resolved.json")
                with open(resolved_sources, "w", encoding="utf-8") as handle:
                    json.dump(sources_doc, handle, ensure_ascii=False, indent=2)
                cfg.sources_json_path = resolved_sources
            store.set_status(job_id, JobStatus.RENDERING)
            store.update_progress(job_id, "story", 1, 2, "Menjalankan Story pipeline...", 10.0)
            from clipping.story_runner import run_story_pipeline

            manifest = run_story_pipeline(cfg)
            clips: list[ClipDetail] = []
            for entry in manifest:
                for kind, path_key in (("Hook", "hook_path"), ("Highlight", "highlight_path")):
                    path = entry.get(path_key)
                    if not path:
                        continue
                    relative = os.path.relpath(path, cfg.outputs_dir).replace(os.sep, "/")
                    clips.append(ClipDetail(
                        rank=int(entry.get("clip_id", 0)),
                        title=f"{entry.get('title', 'Story clip')} — {kind}",
                        filename=relative,
                        download_url=f"/api/outputs/{job_id}/{relative}",
                        metadata=entry,
                    ))
            store.set_clips(job_id, clips)
            store.update_progress(job_id, "done", 2, 2, f"Story selesai: {len(clips)} file.", 100.0)
            return

        # Validate the selected AI provider only.
        if cfg.ai_provider == "gemini" and not cfg.api_key_gemini:
            store.set_error(
                job_id,
                "GOOGLE_API_KEY tidak ditemukan. Set via Settings atau .env file.",
            )
            return
        if cfg.ai_provider == "nvidia" and not cfg.api_key_nvidia:
            store.set_error(job_id, "NVIDIA_API_KEY tidak ditemukan. Set via Settings atau .env file.")
            return
        if cfg.voiceover and not cfg.api_key_gemini:
            store.set_error(job_id, "Voiceover membutuhkan GOOGLE_API_KEY untuk membuat naskah.")
            return
        if (
            (cfg.use_camera_switch or (cfg.use_split_screen and cfg.split_trigger == "diarization"))
            and not cfg.hf_token
        ):
            store.set_error(job_id, "HF_TOKEN diperlukan untuk speaker diarization.")
            return

        # --- Step 1: Download ---
        store.set_status(job_id, JobStatus.DOWNLOADING)
        store.update_progress(
            job_id,
            step="download",
            step_number=1,
            total_steps=7,
            message="Mengunduh video...",
            percent=5.0,
        )

        from clipping import engine

        source_platform = getattr(cfg, "source_platform", "youtube")

        # Reuse a prior job's cached source and optional AI response.
        reuse_job_id = payload.get("reuse_job_id")
        if reuse_job_id:
            previous = store.get_job(reuse_job_id)
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            candidates = []
            if previous and previous.get("upload_filename"):
                candidates.append(os.path.join(project_root, "uploads", previous["upload_filename"]))
            candidates.append(os.path.join(project_root, "outputs", reuse_job_id, "video_asli.mp4"))
            reused_source = next((path for path in candidates if os.path.isfile(path)), None)
            if not reused_source:
                store.set_error(job_id, "Video sumber dari job yang dipilih tidak ditemukan.")
                return
            cfg.file_video_asli = reused_source
            old_json = os.path.join(project_root, "outputs", reuse_job_id, "gemini_response.json")
            if payload.get("load_gemini_json") and os.path.isfile(old_json):
                shutil.copy2(old_json, os.path.join(cfg.outputs_dir, "gemini_response.json"))
            store.update_progress(job_id, "download", 1, 7, "Menggunakan cache dari job sebelumnya.", 14.0)
        # If upload file, skip download
        if payload.get("upload_filename"):
            # Resolve absolute path to the project root (2 levels up from web/api)
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            upload_path = os.path.join(project_root, "uploads", payload["upload_filename"])
            if not os.path.exists(upload_path):
                store.set_error(job_id, f"File upload tidak ditemukan: {payload['upload_filename']}")
                return
            cfg.file_video_asli = upload_path
            store.update_progress(
                job_id,
                step="download",
                step_number=1,
                total_steps=7,
                message="Menggunakan file upload.",
                percent=14.0,
            )
        elif not reuse_job_id:
            if not cfg.url_youtube:
                if os.path.exists(cfg.file_video_asli):
                    store.update_progress(
                        job_id,
                        step="download",
                        step_number=1,
                        total_steps=7,
                        message="Bypass download: menggunakan video lama.",
                        percent=14.0,
                    )
                else:
                    store.set_error(job_id, "Video asli tidak ditemukan di Job ID tersebut. File mungkin sudah terhapus.")
                    return
            else:
                engine.download_video(
                    cfg.url_youtube,
                    cfg.file_video_asli,
                    getattr(cfg, "use_dlp_subs", False),
                    getattr(cfg, "download_source_height", "max"),
                    source_platform=source_platform,
                    yt_cookies=getattr(cfg, "yt_cookies", None),
                )
                store.update_progress(
                    job_id,
                    step="download",
                    step_number=1,
                    total_steps=7,
                    message="Video berhasil diunduh.",
                    percent=14.0,
                )

        # --- Step 2: Transcribe ---
        store.set_status(job_id, JobStatus.TRANSCRIBING)
        store.update_progress(
            job_id,
            step="transcribe",
            step_number=2,
            total_steps=7,
            message="Memulai transkripsi...",
            percent=15.0,
        )

        transkrip_lengkap = ""
        data_segmen = []

        # Try YouTube JSON3 subs first
        json3_files = glob.glob(cfg.file_video_asli.replace(".mp4", ".*.json3"))
        file_json3 = json3_files[0] if json3_files else None

        if source_platform == "youtube" and getattr(cfg, "use_dlp_subs", False) and file_json3 and os.path.exists(file_json3):
            transkrip_lengkap, data_segmen = engine.parse_youtube_json3_subs(
                file_json3, max_words_per_subtitle=cfg.max_kata_per_subtitle
            )

        if not transkrip_lengkap or not data_segmen:
            transkrip_lengkap, data_segmen = engine.transcribe_video(
                cfg.file_video_asli,
                max_words_per_subtitle=cfg.max_kata_per_subtitle,
                model_size=cfg.whisper_model,
                device=cfg.whisper_device,
                compute_type=cfg.whisper_compute_type,
            )

        store.update_progress(
            job_id,
            step="transcribe",
            step_number=2,
            total_steps=7,
            message="Transkripsi selesai.",
            percent=35.0,
        )

        # --- Step 3: AI Analysis ---
        store.set_status(job_id, JobStatus.ANALYZING)
        store.update_progress(
            job_id,
            step="analyze",
            step_number=3,
            total_steps=7,
            message="Menganalisis dengan AI...",
            percent=36.0,
        )

        gemini_output_path = os.path.join(cfg.outputs_dir, "gemini_response.json")

        if getattr(cfg, "load_gemini_json", False) and os.path.exists(gemini_output_path):
            with open(gemini_output_path, "r", encoding="utf-8") as f:
                hasil_json = json.load(f)
        else:
            hasil_json = engine.analyze_with_ai(transkrip_lengkap, cfg)
            with open(gemini_output_path, "w", encoding="utf-8") as f:
                json.dump(hasil_json, f, indent=4, ensure_ascii=False)

        store.update_progress(
            job_id,
            step="analyze",
            step_number=3,
            total_steps=7,
            message=f"AI menemukan {len(hasil_json)} klip viral.",
            percent=50.0,
        )

        # --- Step 4: Metadata ---
        from clipping import metadata

        hasil_json = metadata.normalize_and_validate(hasil_json)
        metadata_path = os.path.join(cfg.outputs_dir, "metadata_preview.json")
        metadata.save_metadata_preview(hasil_json, path=metadata_path)

        store.update_progress(
            job_id,
            step="metadata",
            step_number=4,
            total_steps=7,
            message="Metadata dinormalisasi.",
            percent=55.0,
        )

        # --- Step 5: Diarization (optional) ---
        diarization_data = None
        from clipping import studio, diarization as diarization_mod

        if (
            (getattr(cfg, "use_split_screen", False) and cfg.split_trigger == "diarization")
            or getattr(cfg, "use_camera_switch", False)
        ) and studio._is_vertical_ratio(cfg.pilihan_rasio):
            try:
                store.update_progress(
                    job_id,
                    step="diarization",
                    step_number=5,
                    total_steps=7,
                    message="Menjalankan speaker diarization...",
                    percent=56.0,
                )
                audio_path = cfg.file_video_asli.replace(".mp4", "_audio.wav")
                diarization_mod.extract_audio(cfg.file_video_asli, audio_path)
                num_speakers_arg = getattr(cfg, "diarization_num_speakers", 2)
                min_spk = None
                max_spk = None

                if str(num_speakers_arg).lower() == "auto":
                    max_faces = studio.estimate_speaker_count_from_video(cfg.file_video_asli, cfg)
                    num_speakers_arg = "auto"
                    min_spk = max(1, max_faces)
                    max_spk = min_spk + 2

                diarization_data = diarization_mod.run_diarization(
                    audio_path,
                    hf_token=cfg.hf_token,
                    num_speakers=num_speakers_arg,
                    min_speakers=min_spk,
                    max_speakers=max_spk,
                )
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception as e:
                store.update_progress(
                    job_id,
                    step="diarization",
                    step_number=5,
                    total_steps=7,
                    message=f"Diarization gagal: {e}. Fallback ke mode biasa.",
                    percent=58.0,
                )
                diarization_data = None

        # --- Step 6: Render Preparation ---
        store.set_status(job_id, JobStatus.RENDERING)
        store.update_progress(
            job_id,
            step="render",
            step_number=6,
            total_steps=7,
            message="Menyiapkan rendering...",
            percent=60.0,
        )

        os.environ["OSC_VIDEO_SCALE_ALGO"] = str(getattr(cfg, "video_scale_algo", "lanczos"))

        import cv2

        cap_e = cv2.VideoCapture(cfg.file_video_asli)
        src_h_e = int(cap_e.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap_e.release()

        target_w_e, target_h_e = studio._get_render_dims(cfg, cfg.pilihan_rasio, source_h=src_h_e)
        video_encoder = studio.detect_video_encoder(cfg, target_h=target_h_e)

        file_glitch_ts = None
        if cfg.use_hook_glitch:
            cap_g = cv2.VideoCapture(cfg.file_video_asli)
            source_h_g = int(cap_g.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap_g.release()
            file_glitch_ts = studio.siapkan_glitch_video(
                cfg.pilihan_rasio, cfg, video_encoder, source_h=source_h_g
            )

        # --- Step 7: Render Each Clip ---
        from clipping import hook_manager

        render_manifest: list[dict] = []
        total_clips = len(hasil_json)

        custom_hook_path = None
        if getattr(cfg, "hook_source", None):
            custom_hook_path = hook_manager.download_custom_hook(cfg)

        if getattr(cfg, "voiceover", False):
            from clipping import voiceover
            for klip in hasil_json:
                try:
                    start = float(klip["start_time"])
                    end = float(klip["end_time"])
                    snippet = " ".join(
                        seg.get("text") or " ".join(word["word"] for word in seg.get("words", []))
                        for seg in data_segmen
                        if float(seg["end"]) > start and float(seg["start"]) < end
                    )
                    script = voiceover.generate_commentary_script(
                        snippet, cfg, cfg.voiceover_style, cfg.voiceover_lang, cfg.voiceover_length
                    )
                    if script:
                        audio_path, segments = voiceover.synthesize_voice(
                            script, cfg.voiceover_voice, cfg.outputs_dir, str(klip["rank"])
                        )
                        klip["voiceover"] = {
                            "script": script, "audio_path": audio_path,
                            "segments": segments, "voice": cfg.voiceover_voice,
                        }
                except Exception as exc:
                    store.update_progress(
                        job_id, "voiceover", 5, 7,
                        f"Voiceover clip {klip.get('rank', '?')} dilewati: {exc}", 59.0,
                    )

        for idx, klip in enumerate(sorted(hasil_json, key=lambda x: x["rank"])):
            clip_num = idx + 1
            store.update_progress(
                job_id,
                step="render",
                step_number=6,
                total_steps=7,
                message=f"Merender klip {clip_num}/{total_clips}...",
                percent=60.0 + (35.0 * clip_num / total_clips),
            )

            if custom_hook_path:
                klip["custom_hook_info"] = {"file_path": custom_hook_path}

            hasil_render = studio.proses_klip(
                klip["rank"],
                klip,
                cfg.pilihan_rasio,
                file_glitch_ts,
                data_segmen,
                cfg,
                video_encoder,
                diarization_data=diarization_data,
            )
            if hasil_render:
                render_manifest.append(hasil_render)

        # --- Save manifest ---
        manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(render_manifest, f, ensure_ascii=False, indent=2)

        # --- Build clip details for the job store ---
        clips: list[ClipDetail] = []
        for entry in render_manifest:
            filename = os.path.basename(entry.get("output_file") or entry.get("video_path") or "")
            clips.append(
                ClipDetail(
                    rank=entry.get("rank", 0),
                    viral_score=entry.get("viral_score"),
                    title=entry.get("title_indonesia", ""),
                    title_en=entry.get("title_inggris", ""),
                    filename=filename,
                    duration=entry.get("duration"),
                    start_time=entry.get("start_time"),
                    end_time=entry.get("end_time"),
                    download_url=f"/api/outputs/{job_id}/{filename}",
                    thumbnail_url=(
                        f"/api/outputs/{job_id}/{os.path.basename(entry['thumbnail_path'])}"
                        if entry.get("thumbnail_path") else None
                    ),
                    metadata=entry,
                )
            )

        if cfg.cleanup_source and not payload.get("upload_filename") and not reuse_job_id:
            if os.path.isfile(cfg.file_video_asli):
                os.remove(cfg.file_video_asli)

        store.set_clips(job_id, clips)
        store.update_progress(
            job_id,
            step="done",
            step_number=7,
            total_steps=7,
            message=f"Selesai! {len(clips)} klip berhasil dirender.",
            percent=100.0,
        )

    except Exception as exc:
        tb = traceback.format_exc()
        error_msg = f"{type(exc).__name__}: {exc}"
        store.set_error(job_id, error_msg)
        store.update_progress(
            job_id,
            step="error",
            step_number=0,
            total_steps=7,
            message=f"Pipeline gagal: {error_msg}",
            percent=0.0,
        )
        print(f"[Worker] Job {job_id} failed:\n{tb}", file=sys.stderr)


async def submit_job(job_id: str, payload: dict) -> None:
    """
    Submit a job to the background worker queue.

    Uses a semaphore to limit concurrency and runs the pipeline
    in a thread pool to avoid blocking the async event loop.
    """
    async def _run():
        async with _semaphore:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _executor, _run_pipeline_sync, job_id, payload
            )

    asyncio.create_task(_run())
