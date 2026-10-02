"""Bridge validated Studio payloads to the config namespace used by the CLI."""

from __future__ import annotations

import os
from types import SimpleNamespace

from clipping.config import (
    AI_PROVIDER, ASS_ALIGN_169, ASS_ALIGN_916, ASS_FONT_169, ASS_FONT_916,
    ASS_MARGIN_169, ASS_MARGIN_916, BGM_BASE_VOLUME, BGM_DIR, BGM_MODE,
    BGM_MOODS, DAFTAR_FONT, DOWNLOAD_SOURCE_HEIGHT, GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL, NAMA_FONT_THUMBNAIL, NVIDIA_MODEL, RENDER_OUTPUT_HEIGHT,
    SCALE_KATA_KHUSUS_169, SCALE_KATA_KHUSUS_916, URL_FONT_THUMBNAIL,
    URL_GLITCH_VIDEO, URL_MEDIAPIPE_MODEL, VIDEO_PRESET, VIDEO_QUALITY_CQ,
    VIDEO_QUALITY_CRF, VIDEO_SCALE_ALGO, WARNA_KATA_KHUSUS,
    WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL,
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")


def _asset_path(filename: str | None) -> str | None:
    if not filename:
        return None
    if os.path.basename(filename) != filename or ".." in filename:
        raise ValueError("Invalid uploaded asset identifier")
    path = os.path.abspath(os.path.join(UPLOAD_DIR, filename))
    if os.path.commonpath((path, os.path.abspath(UPLOAD_DIR))) != os.path.abspath(UPLOAD_DIR):
        raise ValueError("Uploaded asset is outside the upload directory")
    return path


def _cookies_value(value: str | None) -> str | None:
    if not value:
        default_path = os.path.join(PROJECT_ROOT, "youtube_cookies.txt")
        return default_path if os.path.exists(default_path) else None
    if value.lower() in {"chrome", "firefox", "edge", "brave", "chromium"}:
        return value.lower()
    if os.path.basename(value) != value:
        raise ValueError("yt_cookies must be a browser name or server-side filename")
    path = os.path.join(PROJECT_ROOT, value)
    if not os.path.isfile(path):
        raise ValueError(f"Cookies file not found: {value}")
    return path


def build_config_from_payload(
    payload: dict,
    job_id: str,
    *,
    env_overrides: dict | None = None,
) -> SimpleNamespace:
    """Build the config shape consumed by clipping.runner."""
    env = env_overrides or {}
    outputs_dir = os.path.join(PROJECT_ROOT, "outputs", job_id)
    font_dir = os.path.join(PROJECT_ROOT, "custom_fonts")
    os.makedirs(outputs_dir, exist_ok=True)
    os.makedirs(font_dir, exist_ok=True)

    source_height = payload.get("source_height", DOWNLOAD_SOURCE_HEIGHT)
    source_height = source_height if source_height == "max" else int(source_height)
    render_height = payload.get("render_height", RENDER_OUTPUT_HEIGHT)
    render_height = render_height if render_height == "source" else int(render_height)

    upload_filename = payload.get("upload_filename")
    file_video_asli = _asset_path(upload_filename) if upload_filename else os.path.join(outputs_dir, "video_asli.mp4")
    hook_source = _asset_path(payload.get("hook_source_filename")) or payload.get("hook_source")
    story_subdir = payload.get("story_output_dir") or "story_clips"
    story_subdir = ("".join(ch for ch in story_subdir if ch.isalnum() or ch in "-_ ").strip() or "story_clips").replace(" ", "_")

    def secret(name: str) -> str:
        return env.get(name, os.environ.get(name, ""))

    yolo_size = payload.get("yolo_size", "8m")
    return SimpleNamespace(
        base_dir=PROJECT_ROOT,
        outputs_dir=outputs_dir,
        font_dir=font_dir,
        file_video_asli=os.path.abspath(file_video_asli),
        file_font_thumbnail=os.path.join(PROJECT_ROOT, NAMA_FONT_THUMBNAIL),
        file_mediapipe_model=os.path.join(PROJECT_ROOT, "blaze_face_full_range.tflite"),
        face_detector=payload.get("face_detector", "mediapipe"),
        yolo_size=yolo_size,
        url_yolo_model=f"https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov{yolo_size}.pt",
        file_yolo_model=os.path.join(PROJECT_ROOT, f"face_yolov{yolo_size}.pt"),
        api_key_gemini=secret("GOOGLE_API_KEY"),
        api_key_nvidia=secret("NVIDIA_API_KEY"),
        hf_token=secret("HF_TOKEN"),
        pixabay_api_key=secret("PIXABAY_API_KEY"),
        pexels_api_key=secret("PEXELS_API_KEY"),
        broll_provider=payload.get(
            "broll_provider",
            env.get("BROLL_PROVIDER", os.environ.get("BROLL_PROVIDER", "auto")),
        ).lower(),
        source_platform=payload.get("source", "youtube"),
        url_youtube=payload.get("url"),
        url_list=[payload["url"]] if payload.get("url") else [],
        upload_filename=upload_filename,
        reuse_job_id=payload.get("reuse_job_id"),
        input_is_local=bool(upload_filename or payload.get("reuse_job_id")),
        yt_cookies=_cookies_value(payload.get("yt_cookies")),
        cleanup_source=payload.get("cleanup_source", False),
        jumlah_clip=payload.get("clips", 7),
        pilihan_rasio=payload.get("ratio", "9:16"),
        download_source_height=source_height,
        render_output_height=render_height,
        max_kata_per_subtitle=payload.get("words_per_sub", 5),
        durasi_hook=payload.get("hook_duration", 3),
        hook_source=hook_source,
        hook_source_start=payload.get("hook_source_start", 0.0),
        hook_v2=payload.get("hook_v2", False),
        hook_v2_items=payload.get("hook_v2_items", 3),
        hook_v2_style=payload.get("hook_v2_style", "controversial_fast_glitch"),
        white_flash_duration=payload.get("white_flash_duration", 0.12),
        no_segment_trim=payload.get("no_segment_trim", False),
        silence_trim=payload.get("silence_trim", False),
        use_broll=payload.get("use_broll", True),
        use_hook_glitch=payload.get("use_hook_glitch", True),
        use_auto_bgm=payload.get("use_auto_bgm", True),
        use_karaoke_effect=payload.get("use_karaoke_effect", True),
        use_split_screen=payload.get("use_split_screen", False),
        use_dynamic_split=payload.get("use_dynamic_split", False),
        split_trigger=payload.get("split_trigger", "diarization"),
        use_camera_switch=payload.get("use_camera_switch", False),
        diarization_num_speakers=payload.get("diarization_speakers", "auto"),
        switch_hold_duration=payload.get("switch_hold_duration", 2.0),
        switch_blend_duration=payload.get("switch_blend_duration", 0.0),
        split_zoom=payload.get("split_zoom", 1.0),
        split_v_align=payload.get("split_v_align", 0.5),
        split_auto_zoom=payload.get("split_auto_zoom", False),
        split_max_zoom=payload.get("split_max_zoom", 2.5),
        no_subs=payload.get("no_subs", False),
        gaya_font_aktif=payload.get("font_style", "HORMOZI"),
        daftar_font=DAFTAR_FONT,
        use_advanced_text=payload.get("advanced_text", False),
        use_advanced_text_on_hook=payload.get("advanced_text_hook", False),
        ass_align_916=ASS_ALIGN_916,
        ass_margin_916=ASS_MARGIN_916,
        ass_font_916=ASS_FONT_916,
        scale_kata_khusus_916=SCALE_KATA_KHUSUS_916,
        ass_align_169=ASS_ALIGN_169,
        ass_margin_169=ASS_MARGIN_169,
        ass_font_169=ASS_FONT_169,
        scale_kata_khusus_169=SCALE_KATA_KHUSUS_169,
        warna_kata_khusus=WARNA_KATA_KHUSUS,
        url_font_thumbnail=URL_FONT_THUMBNAIL,
        url_glitch_video=URL_GLITCH_VIDEO,
        url_mediapipe_model=URL_MEDIAPIPE_MODEL,
        bgm_base_volume=payload.get("bgm_base_volume", BGM_BASE_VOLUME),
        bgm_mode=payload.get("bgm_mode", BGM_MODE),
        bgm_moods=BGM_MOODS,
        bgm_dir=BGM_DIR,
        use_dlp_subs=payload.get("use_dlp_subs", False),
        whisper_model=payload.get("whisper_model", WHISPER_MODEL),
        whisper_device=payload.get("whisper_device", WHISPER_DEVICE),
        whisper_compute_type=payload.get("whisper_compute_type", WHISPER_COMPUTE_TYPE),
        ai_provider=payload.get("ai_provider", AI_PROVIDER),
        nvidia_model=payload.get("nvidia_model", NVIDIA_MODEL),
        gemini_model=payload.get("gemini_model", GEMINI_MODEL),
        gemini_fallback_model=payload.get("gemini_fallback_model", GEMINI_FALLBACK_MODEL),
        load_gemini_json=payload.get("load_gemini_json", False),
        track_step=payload.get("track_step"),
        track_deadzone=payload.get("track_deadzone"),
        track_smooth=payload.get("track_smooth"),
        track_jitter=payload.get("track_jitter"),
        track_snap=payload.get("track_snap"),
        track_conf=payload.get("track_conf", 0.55),
        track_smooth_window=payload.get("track_smooth_window", 12),
        scene_cut_threshold=payload.get("scene_cut_threshold", 18),
        track_iou_threshold=payload.get("track_iou_threshold", 0.2),
        video_quality_cq=payload.get("video_cq", VIDEO_QUALITY_CQ),
        video_quality_crf=payload.get("video_crf", VIDEO_QUALITY_CRF),
        video_bitrate=payload.get("video_bitrate", "auto"),
        video_sharpen=payload.get("video_sharpen", False),
        video_preset=payload.get("video_preset", VIDEO_PRESET),
        video_scale_algo=payload.get("video_scale_algo", VIDEO_SCALE_ALGO),
        box_face_detection=payload.get("box_face_detection", False),
        dev_mode=payload.get("dev_mode", False),
        dev_mode_with_output=payload.get("dev_mode_with_output", False),
        dev_mode_with_output_merge=payload.get("dev_mode_with_output_merge", False),
        track_lines=payload.get("track_lines", False),
        static_crop=payload.get("static_crop", False),
        story_mode=payload.get("story_mode", False),
        story_recipe_path=_asset_path(payload.get("story_recipe_filename")),
        sources_json_path=_asset_path(payload.get("sources_json_filename")),
        story_output_dir=os.path.join(outputs_dir, story_subdir),
        skip_download=payload.get("skip_download", False),
        voiceover=payload.get("voiceover", False),
        voiceover_voice=payload.get("voiceover_voice", "en-GB-MaisieNeural"),
        voiceover_lang=payload.get("voiceover_lang", "en"),
        voiceover_style=payload.get("voiceover_style", "analysis"),
        voiceover_length=payload.get("voiceover_length", "short"),
        voiceover_volume=payload.get("voiceover_volume", 1.0),
        original_volume=payload.get("original_volume", 0.15),
        edge_glow=payload.get("edge_glow", False),
        edge_glow_mode=payload.get("edge_glow_mode", "smooth"),
        watermark_enabled=payload.get("watermark", False),
        watermark_text=payload.get("watermark_text"),
        watermark_image=_asset_path(payload.get("watermark_image_filename")),
        watermark_opacity=payload.get("watermark_opacity", 70),
        watermark_position=payload.get("watermark_position", "center-right"),
        watermark_padding=payload.get("watermark_padding", 0),
        watermark_font_size=payload.get("watermark_font_size", 0),
        watermark_scale=payload.get("watermark_scale", 15),
    )
