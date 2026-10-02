import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.api.app import app, _parse_allowed_origins
from web.api.routes.files import UPLOAD_DIR


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("OSC_API_TOKEN", raising=False)
    return TestClient(app)


def test_health_capabilities_and_jobs(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["version"]
    capabilities = client.get("/api/capabilities")
    assert capabilities.status_code == 200
    assert "pixabay" in capabilities.json()["broll_providers"]
    assert client.get("/api/jobs").status_code == 200


def test_settings_are_presence_only(client):
    response = client.put("/api/settings", json={
        "google_api_key": "test-secret",
        "pixabay_api_key": "test-pixabay",
        "default_clips": 4,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["google_api_key_set"] is True
    assert body["pixabay_api_key_set"] is True
    assert body["default_clips"] == 4
    assert "test-secret" not in response.text


def test_upload_and_job_validation(client):
    response = client.post(
        "/api/upload/video",
        files={"file": ("sample.mp4", b"not-html-video-placeholder", "video/mp4")},
    )
    assert response.status_code == 200
    stored = response.json()["filename"]
    assert "/" not in stored and "\\" not in stored
    Path(UPLOAD_DIR, stored).unlink(missing_ok=True)

    invalid = client.post("/api/jobs", json={})
    assert invalid.status_code == 422


def test_cors_origin_parser():
    origins = _parse_allowed_origins(
        "https://example.github.io, https://example.github.io/, invalid, https://bad.example/path"
    )
    assert origins.count("https://example.github.io") == 1
    assert "https://bad.example/path" not in origins


def test_optional_bearer_auth(monkeypatch):
    monkeypatch.setenv("OSC_API_TOKEN", "unit-token")
    with TestClient(app) as secured:
        assert secured.get("/api/health").status_code == 200
        assert secured.get("/api/settings").status_code == 401
        response = secured.get(
            "/api/settings",
            headers={"Authorization": "Bearer unit-token"},
        )
        assert response.status_code == 200
