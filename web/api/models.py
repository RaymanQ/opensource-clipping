"""Pydantic schemas shared by the Studio API and static web client."""

from __future__ import annotations

import enum
import os
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from clipping.config import (
    AI_PROVIDER,
    BGM_BASE_VOLUME,
    BGM_MODE,
    DOWNLOAD_SOURCE_HEIGHT,
    DURASI_HOOK,
    GAYA_FONT_AKTIF,
    GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL,
    JUMLAH_CLIP,
    MAX_KATA_PER_SUBTITLE,
    NVIDIA_MODEL,
    PILIHAN_RASIO,
    RENDER_OUTPUT_HEIGHT,
    VIDEO_PRESET,
    VIDEO_QUALITY_CQ,
    VIDEO_QUALITY_CRF,
    VIDEO_SCALE_ALGO,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourcePlatform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    GDRIVE = "gdrive"


class AspectRatio(str, enum.Enum):
    RATIO_9_16 = "9:16"
    RATIO_16_9 = "16:9"
    RATIO_1_1 = "1:1"
    RATIO_3_4 = "3:4"
    RATIO_4_5 = "4:5"


class FontStyle(str, enum.Enum):
    DEFAULT = "DEFAULT"
    STORYTELLER = "STORYTELLER"
    HORMOZI = "HORMOZI"
    CINEMATIC = "CINEMATIC"


class FaceDetector(str, enum.Enum):
    MEDIAPIPE = "mediapipe"
    YOLO = "yolo"


class AIProvider(str, enum.Enum):
    GEMINI = "gemini"
    NVIDIA = "nvidia"


class WhisperDevice(str, enum.Enum):
    CUDA = "cuda"
    CPU = "cpu"
    AUTO = "auto"


class BrollProvider(str, enum.Enum):
    AUTO = "auto"
    PIXABAY = "pixabay"
    PEXELS = "pexels"


class JobCreateRequest(BaseModel):
    """Complete web representation of the clipping CLI configuration."""

    # Source
    url: Optional[str] = Field(None, description="Video URL to process")
    upload_filename: Optional[str] = Field(None, description="Uploaded source video identifier")
    source: SourcePlatform = Field(SourcePlatform.YOUTUBE, description="Source platform")
    reuse_job_id: Optional[str] = Field(None, description="Existing job whose cached input may be reused")
    yt_cookies: Optional[str] = Field(None, description="Browser name or server-side cookies filename")
    source_height: str | int = Field(DOWNLOAD_SOURCE_HEIGHT, description="'max' or a positive source height")
    cleanup_source: bool = False

    # Output
    clips: int = Field(JUMLAH_CLIP, ge=1, le=30)
    ratio: AspectRatio = AspectRatio(PILIHAN_RASIO)
    render_height: str | int = Field(RENDER_OUTPUT_HEIGHT, description="'source' or a positive output height")

    # Subtitles / Whisper
    words_per_sub: int = Field(MAX_KATA_PER_SUBTITLE, ge=1, le=15)
    no_subs: bool = False
    font_style: FontStyle = FontStyle(GAYA_FONT_AKTIF)
    use_karaoke_effect: bool = True
    advanced_text: bool = False
    advanced_text_hook: bool = False
    use_dlp_subs: bool = False
    whisper_model: str = Field(WHISPER_MODEL, min_length=1, max_length=100)
    whisper_device: WhisperDevice = WhisperDevice(WHISPER_DEVICE)
    whisper_compute_type: str = Field(WHISPER_COMPUTE_TYPE, min_length=1, max_length=40)

    # AI
    ai_provider: AIProvider = AIProvider(AI_PROVIDER)
    gemini_model: str = Field(GEMINI_MODEL, min_length=1, max_length=200)
    gemini_fallback_model: str = Field(GEMINI_FALLBACK_MODEL, min_length=1, max_length=200)
    nvidia_model: str = Field(NVIDIA_MODEL, min_length=1, max_length=200)
    load_gemini_json: bool = False

    # Hook / segment trimming
    hook_duration: int = Field(DURASI_HOOK, ge=1, le=30)
    hook_source: Optional[str] = Field(None, description="HTTP(S) custom hook URL")
    hook_source_filename: Optional[str] = Field(None, description="Uploaded custom hook identifier")
    hook_source_start: float = Field(0.0, ge=0)
    use_hook_glitch: bool = True
    hook_v2: bool = False
    hook_v2_items: int = Field(3, ge=2, le=6)
    hook_v2_style: str = Field("controversial_fast_glitch", min_length=1, max_length=100)
    white_flash_duration: float = Field(0.12, ge=0.01, le=2.0)
    no_segment_trim: bool = False
    silence_trim: bool = False

    # B-roll / BGM
    use_broll: bool = True
    broll_provider: BrollProvider = BrollProvider.AUTO
    use_auto_bgm: bool = True
    bgm_mode: Literal["ducking", "background"] = BGM_MODE
    bgm_base_volume: float = Field(BGM_BASE_VOLUME, ge=0, le=2)

    # Podcast / split screen
    use_split_screen: bool = False
    use_dynamic_split: bool = False
    split_trigger: Literal["diarization", "face"] = "diarization"
    diarization_speakers: str | int = "auto"
    use_camera_switch: bool = False
    switch_hold_duration: float = Field(2.0, ge=0, le=60)
    switch_blend_duration: float = Field(0.0, ge=0, le=5)
    split_zoom: float = Field(1.0, ge=1, le=5)
    split_v_align: float = Field(0.5, ge=0, le=1)
    split_auto_zoom: bool = False
    split_max_zoom: float = Field(2.5, ge=1, le=6)

    # Detection / tracking
    face_detector: FaceDetector = FaceDetector.MEDIAPIPE
    yolo_size: Literal["8n", "8s", "8m", "8n_v2", "9c"] = "8m"
    static_crop: bool = False
    track_step: Optional[float] = Field(None, gt=0, le=10)
    track_deadzone: Optional[float] = Field(None, ge=0, le=1)
    track_smooth: Optional[float] = Field(None, gt=0, le=1)
    track_jitter: Optional[int] = Field(None, ge=0, le=500)
    track_snap: Optional[float] = Field(None, ge=0, le=2)
    track_conf: float = Field(0.55, ge=0, le=1)
    track_smooth_window: int = Field(12, ge=1, le=300)
    scene_cut_threshold: int = Field(18, ge=0, le=255)
    track_iou_threshold: float = Field(0.2, ge=0, le=1)

    # Video quality
    video_bitrate: str = Field("auto", pattern=r"^(auto|\d+(?:\.\d+)?[kKmM])$")
    video_sharpen: bool = False
    video_cq: int = Field(VIDEO_QUALITY_CQ, ge=0, le=51)
    video_crf: int = Field(VIDEO_QUALITY_CRF, ge=0, le=51)
    video_preset: str = Field(VIDEO_PRESET, min_length=1, max_length=30)
    video_scale_algo: Literal["lanczos", "bicubic", "bilinear", "area"] = VIDEO_SCALE_ALGO

    # Voiceover / effects
    voiceover: bool = False
    voiceover_voice: str = Field("en-GB-MaisieNeural", min_length=1, max_length=100)
    voiceover_lang: Literal["id", "en"] = "en"
    voiceover_style: Literal["analysis", "reaction", "lesson", "summary"] = "analysis"
    voiceover_length: Literal["short", "normal", "long"] = "short"
    voiceover_volume: float = Field(1.0, ge=0, le=3)
    original_volume: float = Field(0.15, ge=0, le=3)
    edge_glow: bool = False
    edge_glow_mode: Literal["default", "smooth", "full"] = "smooth"

    # Watermark
    watermark: bool = False
    watermark_text: Optional[str] = Field(None, max_length=300)
    watermark_image_filename: Optional[str] = Field(None, description="Uploaded watermark image identifier")
    watermark_opacity: int = Field(70, ge=1, le=100)
    watermark_position: Literal[
        "top-left", "top-center", "top-right", "center-left", "center",
        "center-right", "bottom-left", "bottom-center", "bottom-right",
    ] = "center-right"
    watermark_padding: int = Field(0, ge=0, le=4000)
    watermark_font_size: int = Field(0, ge=0, le=1000)
    watermark_scale: int = Field(15, ge=1, le=100)

    # Debug
    box_face_detection: bool = False
    dev_mode: bool = False
    dev_mode_with_output: bool = False
    dev_mode_with_output_merge: bool = False
    track_lines: bool = False

    # Story mode
    story_mode: bool = False
    story_recipe_filename: Optional[str] = None
    sources_json_filename: Optional[str] = None
    story_output_dir: Optional[str] = Field(None, max_length=100)
    skip_download: bool = False

    @field_validator(
        "upload_filename", "hook_source_filename", "watermark_image_filename",
        "story_recipe_filename", "sources_json_filename", "reuse_job_id",
    )
    @classmethod
    def safe_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value and (value != value.strip() or any(ch in value for ch in ("/", "\\", ".."))):
            raise ValueError("Asset and job identifiers must be plain filenames/IDs")
        return value

    @field_validator("source_height")
    @classmethod
    def valid_source_height(cls, value: str | int) -> str | int:
        if isinstance(value, str) and value.lower() == "max":
            return "max"
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("source_height must be 'max' or a positive integer") from exc
        if parsed <= 0:
            raise ValueError("source_height must be positive")
        return parsed

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a valid HTTP(S) URL")
        return value

    @field_validator("yt_cookies")
    @classmethod
    def valid_cookies_reference(cls, value: Optional[str]) -> Optional[str]:
        if value and (os.path.basename(value) != value or ".." in value):
            raise ValueError("yt_cookies must be a browser name or server-side filename")
        return value

    @field_validator("render_height")
    @classmethod
    def valid_render_height(cls, value: str | int) -> str | int:
        if isinstance(value, str) and value.lower() == "source":
            return "source"
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("render_height must be 'source' or a positive integer") from exc
        if parsed <= 0:
            raise ValueError("render_height must be positive")
        return parsed

    @field_validator("diarization_speakers")
    @classmethod
    def valid_speakers(cls, value: str | int) -> str | int:
        if isinstance(value, str) and value.lower() == "auto":
            return "auto"
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("diarization_speakers must be 'auto' or a positive integer") from exc
        if parsed <= 0:
            raise ValueError("diarization_speakers must be positive")
        return parsed

    @model_validator(mode="after")
    def validate_mode(self) -> "JobCreateRequest":
        if self.story_mode:
            if not self.story_recipe_filename or not self.sources_json_filename:
                raise ValueError("Story mode requires uploaded story recipe and sources JSON files")
        elif not (self.url or self.upload_filename or self.reuse_job_id):
            raise ValueError("Provide a URL, uploaded video, or reusable job")
        if self.hook_source and urlparse(self.hook_source).scheme not in {"http", "https"}:
            raise ValueError("hook_source must be an HTTP(S) URL; upload local hooks as assets")
        if self.watermark and not (self.watermark_text or self.watermark_image_filename):
            raise ValueError("Watermark requires text or an uploaded image")
        if self.use_split_screen and self.use_camera_switch:
            raise ValueError("Split-screen and camera-switch are mutually exclusive")
        return self


class JobProgressEvent(BaseModel):
    step: str
    step_number: int
    total_steps: int
    message: str
    percent: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ClipDetail(BaseModel):
    rank: int
    viral_score: Optional[int] = None
    title: Optional[str] = None
    title_en: Optional[str] = None
    filename: str
    duration: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    download_url: str
    thumbnail_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    url: Optional[str] = None
    upload_filename: Optional[str] = None
    source: SourcePlatform = SourcePlatform.YOUTUBE
    config: dict = Field(default_factory=dict)
    progress: Optional[JobProgressEvent] = None
    clips: list[ClipDetail] = Field(default_factory=list)
    error: Optional[str] = None
    log: list[str] = Field(default_factory=list)


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int


class SettingsRequest(BaseModel):
    google_api_key: Optional[str] = None
    pixabay_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    hf_token: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    clear_keys: list[Literal["google", "pixabay", "pexels", "hf", "nvidia"]] = Field(default_factory=list)
    default_broll_provider: Optional[BrollProvider] = None
    default_clips: Optional[int] = Field(None, ge=1, le=30)
    default_ratio: Optional[AspectRatio] = None
    default_font_style: Optional[FontStyle] = None
    default_whisper_model: Optional[str] = Field(None, min_length=1)
    default_whisper_device: Optional[WhisperDevice] = None
    default_whisper_compute_type: Optional[str] = Field(None, min_length=1)
    default_ai_provider: Optional[AIProvider] = None
    default_gemini_model: Optional[str] = Field(None, min_length=1)
    default_gemini_fallback_model: Optional[str] = Field(None, min_length=1)
    default_nvidia_model: Optional[str] = Field(None, min_length=1)
    default_source_height: Optional[str | int] = None
    default_render_height: Optional[str | int] = None
    default_video_preset: Optional[str] = Field(None, min_length=1)
    default_video_scale_algo: Optional[Literal["lanczos", "bicubic", "bilinear", "area"]] = None
    default_bgm_mode: Optional[Literal["ducking", "background"]] = None


class SettingsResponse(BaseModel):
    google_api_key_set: bool = False
    pixabay_api_key_set: bool = False
    pexels_api_key_set: bool = False
    hf_token_set: bool = False
    nvidia_api_key_set: bool = False
    default_broll_provider: str = "auto"
    default_clips: int = JUMLAH_CLIP
    default_ratio: str = PILIHAN_RASIO
    default_font_style: str = GAYA_FONT_AKTIF
    default_whisper_model: str = WHISPER_MODEL
    default_whisper_device: str = WHISPER_DEVICE
    default_whisper_compute_type: str = WHISPER_COMPUTE_TYPE
    default_ai_provider: str = AI_PROVIDER
    default_gemini_model: str = GEMINI_MODEL
    default_gemini_fallback_model: str = GEMINI_FALLBACK_MODEL
    default_nvidia_model: str = NVIDIA_MODEL
    default_source_height: str | int = DOWNLOAD_SOURCE_HEIGHT
    default_render_height: str | int = RENDER_OUTPUT_HEIGHT
    default_video_preset: str = VIDEO_PRESET
    default_video_scale_algo: str = VIDEO_SCALE_ALGO
    default_bgm_mode: str = BGM_MODE
    gpu_available: bool = False
    ffmpeg_available: bool = False
    backend_version: str = ""
    jobs_running: int = 0
    jobs_queued: int = 0


class SystemHealthResponse(BaseModel):
    status: str = "ok"
    version: str
    gpu_available: bool
    cuda_available: bool
    ffmpeg_available: bool
    jobs_running: int
    jobs_queued: int
