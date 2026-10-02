"""
web.api.routes.jobs — Job management endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models import (
    JobCreateRequest,
    JobListResponse,
    JobResponse,
    JobStatus,
    ClipDetail,
)
from .. import store
from .. import worker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_to_response(job: dict) -> JobResponse:
    """Convert internal job dict to API response model."""
    clips = job.get("clips", [])
    clip_list = []
    for c in clips:
        if isinstance(c, ClipDetail):
            clip_list.append(c)
        elif isinstance(c, dict):
            clip_list.append(ClipDetail(**c))

    progress = job.get("progress")
    if progress and isinstance(progress, dict):
        from ..models import JobProgressEvent
        # Convert timestamp strings back to datetime
        if isinstance(progress.get("timestamp"), str):
            progress["timestamp"] = datetime.fromisoformat(progress["timestamp"])
        progress = JobProgressEvent(**progress)

    return JobResponse(
        id=job["id"],
        status=job.get("status", JobStatus.QUEUED),
        created_at=job.get("created_at", datetime.utcnow()),
        updated_at=job.get("updated_at", datetime.utcnow()),
        url=job.get("url"),
        upload_filename=job.get("upload_filename"),
        source=job.get("source", "youtube"),
        config=job.get("config", {}),
        progress=progress,
        clips=clip_list,
        error=job.get("error"),
        log=job.get("log", []),
    )


@router.post("", status_code=201)
async def create_job(req: JobCreateRequest) -> JobResponse:
    """Create a new clipping job and submit it to the background queue."""
    payload = req.model_dump(mode="json")
    runtime = worker.get_settings_env()
    default_fields = {
        "broll_provider": "BROLL_PROVIDER", "clips": "DEFAULT_CLIPS",
        "ratio": "DEFAULT_RATIO", "font_style": "DEFAULT_FONT_STYLE",
        "whisper_model": "DEFAULT_WHISPER_MODEL", "whisper_device": "DEFAULT_WHISPER_DEVICE",
        "whisper_compute_type": "DEFAULT_WHISPER_COMPUTE_TYPE",
        "ai_provider": "DEFAULT_AI_PROVIDER", "gemini_model": "DEFAULT_GEMINI_MODEL",
        "gemini_fallback_model": "DEFAULT_GEMINI_FALLBACK_MODEL",
        "nvidia_model": "DEFAULT_NVIDIA_MODEL", "source_height": "DEFAULT_SOURCE_HEIGHT",
        "render_height": "DEFAULT_RENDER_HEIGHT", "video_preset": "DEFAULT_VIDEO_PRESET",
        "video_scale_algo": "DEFAULT_VIDEO_SCALE_ALGO", "bgm_mode": "DEFAULT_BGM_MODE",
    }
    for field, env_name in default_fields.items():
        if field not in req.model_fields_set:
            value = runtime[env_name] if env_name in runtime else os.environ.get(env_name)
            if value not in (None, ""):
                payload[field] = value
    payload = JobCreateRequest.model_validate(payload).model_dump(mode="json")
    reuse_job_id = payload.get("reuse_job_id")
    if reuse_job_id:
        previous = store.get_job(reuse_job_id)
        if previous is None:
            raise HTTPException(status_code=404, detail="Reusable job not found")
        payload["load_gemini_json"] = True
        
    job_id = store.create_job(
        url=req.url,
        upload_filename=req.upload_filename,
        source=req.source.value if hasattr(req.source, "value") else req.source,
        config=payload,
    )

    # Submit to background worker
    await worker.submit_job(job_id, payload)

    job = store.get_job(job_id)
    return _job_to_response(job)


@router.get("")
async def list_jobs() -> JobListResponse:
    """List all jobs (newest first)."""
    jobs = store.list_jobs()
    return JobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=len(jobs),
    )


@router.get("/{job_id}")
async def get_job(job_id: str) -> JobResponse:
    """Get job detail."""
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str) -> dict:
    """Cancel/delete a job."""
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # If running, mark as cancelled first
    running_states = {
        JobStatus.QUEUED.value,
        JobStatus.DOWNLOADING.value,
        JobStatus.TRANSCRIBING.value,
        JobStatus.ANALYZING.value,
        JobStatus.RENDERING.value,
    }
    if job.get("status") in running_states:
        store.set_status(job_id, JobStatus.CANCELLED)

    store.delete_job(job_id)
    return {"message": "Job deleted", "id": job_id}


@router.get("/{job_id}/status")
async def job_status_sse(job_id: str):
    """
    Server-Sent Events endpoint for real-time job progress.

    The client connects to this endpoint and receives progress updates
    as SSE events until the job completes or fails.
    """
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        last_progress = None
        terminal_states = {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }

        while True:
            current_job = store.get_job(job_id)
            if current_job is None:
                yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                break

            status = current_job.get("status", "")
            progress = current_job.get("progress")

            # Build event data
            progress_data = None
            if progress:
                if hasattr(progress, "model_dump"):
                    progress_data = progress.model_dump()
                    if isinstance(progress_data.get("timestamp"), datetime):
                        progress_data["timestamp"] = progress_data["timestamp"].isoformat()
                elif isinstance(progress, dict):
                    progress_data = progress

            event = {
                "type": "progress",
                "status": status,
                "progress": progress_data,
                "error": current_job.get("error"),
            }

            # Only send if something changed
            event_json = json.dumps(event, default=str)
            if event_json != last_progress:
                yield f"data: {event_json}\n\n"
                last_progress = event_json

            # Stop streaming on terminal states
            if status in terminal_states:
                # Send final event with clips if completed
                if status == JobStatus.COMPLETED.value:
                    clips = current_job.get("clips", [])
                    clip_data = []
                    for c in clips:
                        if hasattr(c, "model_dump"):
                            clip_data.append(c.model_dump())
                        elif isinstance(c, dict):
                            clip_data.append(c)
                    final_event = {
                        "type": "completed",
                        "status": status,
                        "clips": clip_data,
                    }
                    yield f"data: {json.dumps(final_event, default=str)}\n\n"
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
