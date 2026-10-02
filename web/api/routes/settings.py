"""Runtime settings, health, and backend capability endpoints."""

from __future__ import annotations

import importlib.util
import os
import shutil

from fastapi import APIRouter

from clipping import __version__
from clipping.config import (
    AI_PROVIDER, BGM_MODE, DAFTAR_FONT, DOWNLOAD_SOURCE_HEIGHT,
    GAYA_FONT_AKTIF, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, JUMLAH_CLIP,
    NVIDIA_MODEL, PILIHAN_RASIO, RENDER_OUTPUT_HEIGHT, VIDEO_PRESET,
    VIDEO_SCALE_ALGO, WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL,
)
from .. import store as job_store
from .. import worker
from ..models import SettingsRequest, SettingsResponse, SystemHealthResponse

router = APIRouter(tags=["settings"])


def _check_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _value(value):
    return value.value if hasattr(value, "value") else value


def _effective(env: dict[str, str], name: str, default: str = "") -> str:
    return env[name] if name in env else os.environ.get(name, default)


@router.get("/api/settings")
async def get_settings() -> SettingsResponse:
    """Return runtime defaults and secret presence only, never secret values."""
    env = worker.get_settings_env()
    return SettingsResponse(
        google_api_key_set=bool(_effective(env, "GOOGLE_API_KEY")),
        pixabay_api_key_set=bool(_effective(env, "PIXABAY_API_KEY")),
        pexels_api_key_set=bool(_effective(env, "PEXELS_API_KEY")),
        hf_token_set=bool(_effective(env, "HF_TOKEN")),
        nvidia_api_key_set=bool(_effective(env, "NVIDIA_API_KEY")),
        default_broll_provider=_effective(env, "BROLL_PROVIDER", "auto"),
        default_clips=int(_effective(env, "DEFAULT_CLIPS", str(JUMLAH_CLIP))),
        default_ratio=_effective(env, "DEFAULT_RATIO", PILIHAN_RASIO),
        default_font_style=_effective(env, "DEFAULT_FONT_STYLE", GAYA_FONT_AKTIF),
        default_whisper_model=_effective(env, "DEFAULT_WHISPER_MODEL", WHISPER_MODEL),
        default_whisper_device=_effective(env, "DEFAULT_WHISPER_DEVICE", WHISPER_DEVICE),
        default_whisper_compute_type=_effective(env, "DEFAULT_WHISPER_COMPUTE_TYPE", WHISPER_COMPUTE_TYPE),
        default_ai_provider=_effective(env, "DEFAULT_AI_PROVIDER", AI_PROVIDER),
        default_gemini_model=_effective(env, "DEFAULT_GEMINI_MODEL", GEMINI_MODEL),
        default_gemini_fallback_model=_effective(env, "DEFAULT_GEMINI_FALLBACK_MODEL", GEMINI_FALLBACK_MODEL),
        default_nvidia_model=_effective(env, "DEFAULT_NVIDIA_MODEL", NVIDIA_MODEL),
        default_source_height=_effective(env, "DEFAULT_SOURCE_HEIGHT", str(DOWNLOAD_SOURCE_HEIGHT)),
        default_render_height=_effective(env, "DEFAULT_RENDER_HEIGHT", str(RENDER_OUTPUT_HEIGHT)),
        default_video_preset=_effective(env, "DEFAULT_VIDEO_PRESET", VIDEO_PRESET),
        default_video_scale_algo=_effective(env, "DEFAULT_VIDEO_SCALE_ALGO", VIDEO_SCALE_ALGO),
        default_bgm_mode=_effective(env, "DEFAULT_BGM_MODE", BGM_MODE),
        gpu_available=_check_gpu(),
        ffmpeg_available=_check_ffmpeg(),
        backend_version=__version__,
        jobs_running=job_store.get_running_count(),
        jobs_queued=job_store.get_queued_count(),
    )


@router.put("/api/settings")
async def update_settings(req: SettingsRequest) -> SettingsResponse:
    """Update in-memory settings; blank secret inputs leave existing values alone."""
    updates: dict[str, str] = {}
    secret_fields = {
        "google_api_key": "GOOGLE_API_KEY",
        "pixabay_api_key": "PIXABAY_API_KEY",
        "pexels_api_key": "PEXELS_API_KEY",
        "hf_token": "HF_TOKEN",
        "nvidia_api_key": "NVIDIA_API_KEY",
    }
    for field, env_name in secret_fields.items():
        value = getattr(req, field)
        if value:
            updates[env_name] = value.strip()

    clear_map = {
        "google": "GOOGLE_API_KEY", "pixabay": "PIXABAY_API_KEY",
        "pexels": "PEXELS_API_KEY", "hf": "HF_TOKEN", "nvidia": "NVIDIA_API_KEY",
    }
    for key in req.clear_keys:
        updates[clear_map[key]] = ""

    defaults = {
        "default_broll_provider": "BROLL_PROVIDER",
        "default_clips": "DEFAULT_CLIPS",
        "default_ratio": "DEFAULT_RATIO",
        "default_font_style": "DEFAULT_FONT_STYLE",
        "default_whisper_model": "DEFAULT_WHISPER_MODEL",
        "default_whisper_device": "DEFAULT_WHISPER_DEVICE",
        "default_whisper_compute_type": "DEFAULT_WHISPER_COMPUTE_TYPE",
        "default_ai_provider": "DEFAULT_AI_PROVIDER",
        "default_gemini_model": "DEFAULT_GEMINI_MODEL",
        "default_gemini_fallback_model": "DEFAULT_GEMINI_FALLBACK_MODEL",
        "default_nvidia_model": "DEFAULT_NVIDIA_MODEL",
        "default_source_height": "DEFAULT_SOURCE_HEIGHT",
        "default_render_height": "DEFAULT_RENDER_HEIGHT",
        "default_video_preset": "DEFAULT_VIDEO_PRESET",
        "default_video_scale_algo": "DEFAULT_VIDEO_SCALE_ALGO",
        "default_bgm_mode": "DEFAULT_BGM_MODE",
    }
    for field, env_name in defaults.items():
        value = getattr(req, field)
        if value is not None:
            updates[env_name] = str(_value(value))

    worker.set_settings_env(updates)
    return await get_settings()


@router.get("/api/health")
async def health_check() -> SystemHealthResponse:
    gpu = _check_gpu()
    return SystemHealthResponse(
        status="ok",
        version=__version__,
        gpu_available=gpu,
        cuda_available=gpu,
        ffmpeg_available=_check_ffmpeg(),
        jobs_running=job_store.get_running_count(),
        jobs_queued=job_store.get_queued_count(),
    )


@router.get("/api/capabilities")
async def capabilities() -> dict:
    """Return choices and optional feature availability for dynamic Studio controls."""
    env = worker.get_settings_env()
    gpu = _check_gpu()
    return {
        "version": __version__,
        "aspect_ratios": ["9:16", "16:9", "1:1", "3:4", "4:5"],
        "source_platforms": ["youtube", "tiktok", "instagram", "gdrive"],
        "font_styles": list(DAFTAR_FONT),
        "ai_providers": ["gemini", "nvidia"],
        "broll_providers": ["auto", "pixabay", "pexels"],
        "face_detectors": ["mediapipe", "yolo"],
        "yolo_sizes": ["8n", "8s", "8m", "8n_v2", "9c"],
        "whisper_devices": ["cuda", "cpu", "auto"],
        "bgm_modes": ["ducking", "background"],
        "video_presets": ["auto", "p1", "p4", "p7", "ultrafast", "veryfast", "fast", "medium", "slow"],
        "video_scale_algorithms": ["lanczos", "bicubic", "bilinear", "area"],
        "hook_v2_styles": ["controversial_fast_glitch"],
        "edge_glow_modes": ["default", "smooth", "full"],
        "watermark_positions": [
            "top-left", "top-center", "top-right", "center-left", "center",
            "center-right", "bottom-left", "bottom-center", "bottom-right",
        ],
        "voiceover_styles": ["analysis", "reaction", "lesson", "summary"],
        "voiceover_languages": ["id", "en"],
        "gpu_available": gpu,
        "cuda_available": gpu,
        "ffmpeg_available": _check_ffmpeg(),
        "optional_features": {
            "pixabay": bool(_effective(env, "PIXABAY_API_KEY")),
            "pexels": bool(_effective(env, "PEXELS_API_KEY")),
            "diarization": bool(_effective(env, "HF_TOKEN")),
            "nvidia": bool(_effective(env, "NVIDIA_API_KEY")),
            "voiceover": importlib.util.find_spec("edge_tts") is not None,
        },
    }
