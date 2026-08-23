from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    projects_root = tmp_path / "projects"
    sessions_root = tmp_path / "investigation_sessions"
    monkeypatch.setattr(api, "PROJECT_STORE", api.ProjectStore(projects_root))
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", api.ProjectActivityStore(projects_root, api.PROJECT_STORE))
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", api.CheckpointProposalStore(projects_root, api.PROJECT_STORE, api.PROJECT_ACTIVITY_STORE))
    monkeypatch.setattr(api, "SESSION_STORE", api.InvestigationSessionStore(sessions_root))
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(api.SESSION_STORE))
    return TestClient(api.app)


def _project(client: TestClient, name: str) -> str:
    response = client.post("/projects", json={"name": name, "goal": "Review retained evidence"})
    assert response.status_code == 201
    return response.json()["project_id"]


def _session_with_image(client: TestClient, project_id: str) -> tuple[str, str, bytes]:
    created = client.post(f"/projects/{project_id}/investigation-sessions", json={})
    session_id = created.json()["session_id"]
    content = b"\x89PNG\r\n\x1a\nretained-image"
    uploaded = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": ("retained.png", content, "image/png")},
        data={"source": "android", "normalized_text": "saved explanation"},
    )
    assert uploaded.status_code == 201
    return session_id, uploaded.json()["evidence_id"], content


def test_project_owned_evidence_metadata_and_content_are_read_only(client: TestClient):
    project_id = _project(client, "A")
    session_id, evidence_id, content = _session_with_image(client, project_id)
    before = client.get(f"/projects/{project_id}").json()

    metadata = client.get(f"/projects/{project_id}/investigation-sessions/{session_id}/evidence")
    downloaded = client.get(f"/projects/{project_id}/investigation-sessions/{session_id}/evidence/{evidence_id}/content")

    assert metadata.status_code == 200
    assert metadata.json()[0]["normalized_text"] == "saved explanation"
    assert "storage_ref" in metadata.json()[0]
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.content == content
    assert client.get(f"/projects/{project_id}").json() == before


def test_cross_project_evidence_review_is_not_found(client: TestClient):
    project_a = _project(client, "A")
    project_b = _project(client, "B")
    session_id, evidence_id, _ = _session_with_image(client, project_a)

    assert client.get(f"/projects/{project_b}/investigation-sessions/{session_id}/evidence").status_code == 404
    assert client.get(
        f"/projects/{project_b}/investigation-sessions/{session_id}/evidence/{evidence_id}/content"
    ).status_code == 404


def test_missing_and_invalid_evidence_are_safe(client: TestClient):
    project_id = _project(client, "A")
    session_id, _, _ = _session_with_image(client, project_id)

    invalid = client.get(f"/projects/{project_id}/investigation-sessions/{session_id}/evidence/not-a-uuid/content")
    missing = client.get(
        f"/projects/{project_id}/investigation-sessions/{session_id}/evidence/11111111-1111-1111-1111-111111111111/content"
    )
    assert invalid.status_code == 422
    assert missing.status_code == 404
