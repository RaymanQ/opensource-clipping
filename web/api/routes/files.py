"""Safe upload and output-file endpoints."""

from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".ts"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ASSET_RULES = {
    "video": (VIDEO_EXTS, 2 * 1024**3),
    "hook": (VIDEO_EXTS, 2 * 1024**3),
    "watermark": (IMAGE_EXTS, 20 * 1024**2),
    "story_recipe": ({".json"}, 5 * 1024**2),
    "sources_json": ({".json"}, 5 * 1024**2),
}


async def _save_upload(file: UploadFile, asset_type: str) -> dict:
    if asset_type not in ASSET_RULES:
        raise HTTPException(status_code=400, detail=f"Unsupported asset type: {asset_type}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    allowed_exts, max_size = ASSET_RULES[asset_type]
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {asset_type} file type. Allowed: {', '.join(sorted(allowed_exts))}",
        )

    stored_name = f"{asset_type}_{uuid.uuid4().hex}{ext}"
    destination = os.path.join(UPLOAD_DIR, stored_name)
    total = 0
    first = True
    try:
        with open(destination, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                if first and chunk.lstrip().lower().startswith((b"<html", b"<!doctype html")):
                    raise HTTPException(status_code=400, detail="Uploaded content is HTML, not the requested asset")
                first = False
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{asset_type} exceeds the {max_size // (1024**2)} MB limit",
                    )
                handle.write(chunk)
        if not total:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        if ext == ".json":
            try:
                with open(destination, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=400, detail="Uploaded JSON is invalid") from exc
            required = "clips" if asset_type == "story_recipe" else "sources"
            if not isinstance(data, dict) or required not in data:
                raise HTTPException(status_code=400, detail=f"{asset_type} JSON must contain '{required}'")
        elif asset_type == "watermark":
            try:
                from PIL import Image
                with Image.open(destination) as image:
                    image.verify()
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Watermark is not a valid image") from exc
    except Exception:
        if os.path.exists(destination):
            os.remove(destination)
        raise

    return {
        "asset_id": stored_name,
        "filename": stored_name,
        "original_filename": os.path.basename(file.filename),
        "asset_type": asset_type,
        "size_bytes": total,
        "size_mb": round(total / (1024 * 1024), 2),
    }


@router.post("/api/upload")
@router.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...)) -> dict:
    """Upload a source video (the legacy /api/upload route remains supported)."""
    return await _save_upload(file, "video")


@router.post("/api/upload/asset")
async def upload_asset(
    file: UploadFile = File(...),
    asset_type: str = Form(...),
) -> dict:
    """Upload a watermark, custom hook, or Story JSON asset."""
    return await _save_upload(file, asset_type)


def _safe_output_path(job_id: str, relative_path: str = "") -> str:
    if os.path.basename(job_id) != job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="Invalid job ID")
    job_dir = os.path.abspath(os.path.join(OUTPUTS_DIR, job_id))
    path = os.path.abspath(os.path.join(job_dir, relative_path.replace("/", os.sep)))
    if os.path.commonpath((path, job_dir)) != job_dir:
        raise HTTPException(status_code=400, detail="Invalid output path")
    return path


@router.get("/api/outputs/{job_id}/{filename:path}")
async def serve_output(job_id: str, filename: str):
    file_path = _safe_output_path(job_id, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    media_types = {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
        ".webm": "video/webm", ".json": "application/json", ".ass": "text/plain",
        ".srt": "text/plain", ".vtt": "text/vtt", ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    }
    return FileResponse(
        file_path,
        media_type=media_types.get(os.path.splitext(file_path)[1].lower(), "application/octet-stream"),
        filename=os.path.basename(file_path),
    )


@router.get("/api/outputs/{job_id}")
async def list_outputs(job_id: str) -> dict:
    job_dir = _safe_output_path(job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job output directory not found")
    files = []
    for root, _, names in os.walk(job_dir):
        for name in sorted(names):
            path = os.path.join(root, name)
            relative = os.path.relpath(path, job_dir).replace(os.sep, "/")
            size = os.path.getsize(path)
            files.append({
                "filename": relative,
                "size_bytes": size,
                "size_mb": round(size / (1024 * 1024), 2),
                "download_url": f"/api/outputs/{job_id}/{relative}",
            })
    return {"job_id": job_id, "files": files, "total": len(files)}
