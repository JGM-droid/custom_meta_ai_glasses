from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
import investigations.evidence_store as evidence_store_module
from investigations import (
    EVIDENCE_SCHEMA_VERSION,
    InvestigationEvidence,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSessionStatus,
    InvestigationSessionStore,
    MAX_AUDIO_UPLOAD_BYTES,
    MAX_IMAGE_UPLOAD_BYTES,
    UPLOAD_CHUNK_SIZE,
    create_new_investigation_session,
)


@pytest.fixture
def evidence_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    evidence_store = InvestigationEvidenceStore(store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", root)
    monkeypatch.setattr(api, "SESSION_STORE", store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", evidence_store)
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    client = TestClient(api.app)
    return client, store, evidence_store, root


def _image_part(name: str, content: bytes, content_type: str = "image/png") -> tuple[str, io.BytesIO, str]:
    return (name, io.BytesIO(content), content_type)


def _audio_part(name: str, content: bytes, content_type: str = "audio/wav") -> tuple[str, io.BytesIO, str]:
    return (name, io.BytesIO(content), content_type)


def _create_session(client: TestClient) -> str:
    response = client.post("/investigation-sessions", json={})
    assert response.status_code == 201
    return response.json()["session_id"]


def _create_collecting_session(client: TestClient) -> str:
    session_id = _create_session(client)
    paused = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": 0})
    assert paused.status_code == 200
    resumed = client.post(f"/investigation-sessions/{session_id}/resume", json={"expected_revision": 1})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "collecting"
    return session_id


def _base_evidence_payload() -> dict[str, object]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": str(create_new_investigation_session().session_id),
        "session_id": str(create_new_investigation_session().session_id),
        "evidence_type": "image",
        "source": "desktop",
        "created_at_utc": datetime.now(timezone.utc),
        "validation_status": "accepted",
        "sequence_number": 1,
        "client_timestamp_utc": datetime.now(timezone.utc),
        "filename": "screen.png",
        "mime_type": "image/png",
        "storage_ref": "evidence/payloads/11111111-1111-1111-1111-111111111111_screen.png",
        "content_hash": "a" * 64,
        "width": 1920,
        "height": 1080,
        "metadata": {"device": "desktop"},
    }


def test_evidence_model_validation_and_bounds():
    image = InvestigationEvidence.model_validate(_base_evidence_payload())
    assert image.schema_version == EVIDENCE_SCHEMA_VERSION
    assert image.validation_status == InvestigationEvidenceValidationStatus.ACCEPTED

    audio_payload = _base_evidence_payload()
    audio_payload.update(
        {
            "evidence_id": str(create_new_investigation_session().session_id),
            "session_id": str(create_new_investigation_session().session_id),
            "evidence_type": "audio",
            "filename": "note.wav",
            "mime_type": "audio/wav",
            "storage_ref": "evidence/payloads/22222222-2222-2222-2222-222222222222_note.wav",
            "duration_seconds": 2.5,
            "width": None,
            "height": None,
        }
    )
    audio = InvestigationEvidence.model_validate(audio_payload)
    assert audio.evidence_type == InvestigationEvidenceType.AUDIO

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "created_at_utc": datetime.now()})

    with pytest.raises(ValidationError):
        payload = _base_evidence_payload()
        payload["client_timestamp_utc"] = datetime.now()
        InvestigationEvidence.model_validate(payload)

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "filename": "../escape.png"})

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "storage_ref": "/tmp/escape.png"})

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "width": 0})

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "duration_seconds": 0})

    with pytest.raises(ValidationError):
        InvestigationEvidence.model_validate({**_base_evidence_payload(), "extra": "nope"})


def test_evidence_upload_list_delete_and_layout(evidence_test_context):
    client, _, _, root = evidence_test_context
    session_id = _create_collecting_session(client)

    first = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"source": "desktop", "metadata": json.dumps({"device": "laptop"}), "width": 1920, "height": 1080},
        files={"file": _image_part("first.png", b"first-image")},
    )
    assert first.status_code == 201
    first_payload = first.json()
    assert first_payload["sequence_number"] == 1

    second = client.post(
        f"/investigation-sessions/{session_id}/evidence/audio",
        data={"source": "mobile", "normalized_text": "spoken summary", "duration_seconds": 2.5},
        files={"file": _audio_part("voice.wav", b"voice-bytes")},
    )
    assert second.status_code == 201
    second_payload = second.json()
    assert second_payload["sequence_number"] == 2

    listed = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert listed.status_code == 200
    payload = listed.json()
    assert [item["sequence_number"] for item in payload] == [1, 2]
    assert [item["evidence_id"] for item in payload] == [first_payload["evidence_id"], second_payload["evidence_id"]]
    assert payload[0]["filename"] == "first.png"
    assert payload[0]["mime_type"] == "image/png"
    assert payload[0]["width"] == 1920
    assert payload[1]["duration_seconds"] == 2.5

    workspace = root / session_id / "evidence"
    assert workspace.exists()
    assert len([path for path in workspace.glob("*.json") if path.name != "_evidence_manifest.json"]) == 2
    assert len(list((workspace / "payloads").glob("*"))) == 2

    deleted = client.delete(f"/investigation-sessions/{session_id}/evidence/{first_payload['evidence_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["evidence_id"] == first_payload["evidence_id"]

    listed_after_delete = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert listed_after_delete.status_code == 200
    remaining = listed_after_delete.json()
    assert [item["sequence_number"] for item in remaining] == [2]

    third = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("third.png", b"third-image")},
    )
    assert third.status_code == 201
    assert third.json()["sequence_number"] == 3


def test_evidence_state_gating_and_listing_rules(evidence_test_context):
    client, store, _, _ = evidence_test_context

    created_id = _create_session(client)
    created_list = client.get(f"/investigation-sessions/{created_id}/evidence")
    assert created_list.status_code == 200
    assert created_list.json() == []

    created_upload = client.post(
        f"/investigation-sessions/{created_id}/evidence/image",
        files={"file": _image_part("blocked.png", b"bytes")},
    )
    assert created_upload.status_code == 201
    created_session = store.load_session(created_id)
    assert created_session.status == InvestigationSessionStatus.COLLECTING
    assert created_session.revision == 1

    paused_id = _create_session(client)
    paused = client.post(f"/investigation-sessions/{paused_id}/pause", json={"expected_revision": 0})
    assert paused.status_code == 200
    paused_list = client.get(f"/investigation-sessions/{paused_id}/evidence")
    assert paused_list.status_code == 200

    paused_upload = client.post(
        f"/investigation-sessions/{paused_id}/evidence/image",
        files={"file": _image_part("blocked.png", b"bytes")},
    )
    assert paused_upload.status_code == 409

    resumed = client.post(f"/investigation-sessions/{paused_id}/resume", json={"expected_revision": 1})
    assert resumed.status_code == 200
    collecting_upload = client.post(
        f"/investigation-sessions/{paused_id}/evidence/image",
        files={"file": _image_part("allowed.png", b"bytes")},
    )
    assert collecting_upload.status_code == 201

    cancelled_id = _create_session(client)
    cancel = client.post(f"/investigation-sessions/{cancelled_id}/cancel", json={"expected_revision": 0})
    assert cancel.status_code == 200
    cancelled_list = client.get(f"/investigation-sessions/{cancelled_id}/evidence")
    assert cancelled_list.status_code == 200
    cancelled_upload = client.post(
        f"/investigation-sessions/{cancelled_id}/evidence/image",
        files={"file": _image_part("blocked.png", b"bytes")},
    )
    assert cancelled_upload.status_code == 409

    delete_created = client.delete(f"/investigation-sessions/{created_id}/evidence/00000000-0000-0000-0000-000000000000")
    assert delete_created.status_code == 404
    assert delete_created.json()["detail"]["category"] == "evidence_not_found"

    collecting_session_id = _create_collecting_session(client)
    upload = client.post(
        f"/investigation-sessions/{collecting_session_id}/evidence/image",
        files={"file": _image_part("delete.png", b"delete-bytes")},
    )
    assert upload.status_code == 201
    evidence_id = upload.json()["evidence_id"]
    deleted = client.delete(f"/investigation-sessions/{collecting_session_id}/evidence/{evidence_id}")
    assert deleted.status_code == 200

    paused_again = client.post(f"/investigation-sessions/{collecting_session_id}/pause", json={"expected_revision": 2})
    assert paused_again.status_code == 200
    paused_delete = client.delete(f"/investigation-sessions/{collecting_session_id}/evidence/{evidence_id}")
    assert paused_delete.status_code == 409

    cancelled_session_id = _create_collecting_session(client)
    cancel_upload = client.post(f"/investigation-sessions/{cancelled_session_id}/evidence/image", files={"file": _image_part("delete2.png", b"delete-two")})
    assert cancel_upload.status_code == 201
    cancel_evidence_id = cancel_upload.json()["evidence_id"]
    cancelled = client.post(f"/investigation-sessions/{cancelled_session_id}/cancel", json={"expected_revision": 2})
    assert cancelled.status_code == 200
    cancelled_delete = client.delete(f"/investigation-sessions/{cancelled_session_id}/evidence/{cancel_evidence_id}")
    assert cancelled_delete.status_code == 409

    for session_id in [created_id, paused_id, cancelled_id]:
        response = client.delete(f"/investigation-sessions/{session_id}/evidence/{evidence_id}")
        assert response.status_code in {404, 409}


def test_evidence_duplicate_uploads_do_not_consume_sequence_or_cross_type_collide(evidence_test_context):
    client, store, evidence_store, root = evidence_test_context
    session_id = _create_collecting_session(client)

    first = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("same.png", b"same-bytes")},
    )
    assert first.status_code == 201
    first_id = first.json()["evidence_id"]

    duplicate = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("same-again.png", b"same-bytes")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["evidence_id"] == first_id

    audio = client.post(
        f"/investigation-sessions/{session_id}/evidence/audio",
        data={"duration_seconds": 1.5},
        files={"file": _audio_part("same.wav", b"same-bytes")},
    )
    assert audio.status_code == 201
    assert audio.json()["sequence_number"] == 2

    listed = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert [item["sequence_number"] for item in listed.json()] == [1, 2]

    restart_store = InvestigationSessionStore(root)
    restart_evidence_store = InvestigationEvidenceStore(restart_store)
    loaded = restart_evidence_store.list_evidence(session_id)
    assert [item.sequence_number for item in loaded] == [1, 2]

    duplicate_after_restart, created = restart_evidence_store.upload_evidence(
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=b"same-bytes",
        mime_type="image/png",
        original_filename="same-again.png",
        request=InvestigationEvidenceCreateRequest(
            source="desktop",
            client_timestamp_utc=datetime.now(timezone.utc),
            normalized_text=None,
            metadata=None,
            filename="same-again.png",
            mime_type="image/png",
            width=800,
            height=600,
            duration_seconds=None,
        ),
    )
    assert created is False
    assert duplicate_after_restart.evidence_id == first_id

    new_record, created = restart_evidence_store.upload_evidence(
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=b"new-bytes",
        mime_type="image/png",
        original_filename="new.png",
        request=InvestigationEvidenceCreateRequest(
            source="desktop",
            client_timestamp_utc=datetime.now(timezone.utc),
            normalized_text=None,
            metadata=None,
            filename="new.png",
            mime_type="image/png",
            width=800,
            height=600,
            duration_seconds=None,
        ),
    )
    assert created is True
    assert new_record.sequence_number == 3


def test_evidence_sequence_survives_restart_and_deletion_does_not_renumber(evidence_test_context):
    client, store, _, root = evidence_test_context
    session_id = _create_collecting_session(client)

    first = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("first.png", b"one")})
    second = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("second.png", b"two")})
    assert first.status_code == 201 and second.status_code == 201

    restart_store = InvestigationSessionStore(root)
    restart_evidence_store = InvestigationEvidenceStore(restart_store)
    loaded = restart_evidence_store.list_evidence(session_id)
    assert [item.sequence_number for item in loaded] == [1, 2]

    delete_response = client.delete(f"/investigation-sessions/{session_id}/evidence/{first.json()['evidence_id']}")
    assert delete_response.status_code == 200

    after_delete = restart_evidence_store.list_evidence(session_id)
    assert [item.sequence_number for item in after_delete] == [2]

    third = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("third.png", b"three")})
    assert third.status_code == 201
    assert third.json()["sequence_number"] == 3


def test_evidence_upload_size_limits_and_sequence_non_consumption(evidence_test_context):
    client, _, _, root = evidence_test_context
    image_session = _create_collecting_session(client)

    exact = client.post(
        f"/investigation-sessions/{image_session}/evidence/image",
        files={"file": _image_part("exact.png", b"a" * MAX_IMAGE_UPLOAD_BYTES)},
    )
    assert exact.status_code == 201
    assert exact.json()["sequence_number"] == 1

    oversized = client.post(
        f"/investigation-sessions/{image_session}/evidence/image",
        files={"file": _image_part("too-big.png", b"b" * (MAX_IMAGE_UPLOAD_BYTES + 1))},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["category"] == "upload_too_large"

    followup = client.post(
        f"/investigation-sessions/{image_session}/evidence/image",
        files={"file": _image_part("after.png", b"c")},
    )
    assert followup.status_code == 201
    assert followup.json()["sequence_number"] == 2

    oversized_session = _create_collecting_session(client)
    oversized = client.post(
        f"/investigation-sessions/{oversized_session}/evidence/image",
        files={"file": _image_part("too-big.png", b"b" * (MAX_IMAGE_UPLOAD_BYTES + 1))},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["category"] == "upload_too_large"
    assert not list((root / oversized_session / "evidence").glob("*.json"))
    assert not list((root / oversized_session / "evidence" / "payloads").glob("*"))

    followup_after_oversize = client.post(
        f"/investigation-sessions/{oversized_session}/evidence/image",
        files={"file": _image_part("after.png", b"c")},
    )
    assert followup_after_oversize.status_code == 201
    assert followup_after_oversize.json()["sequence_number"] == 1

    audio_exact_session = _create_collecting_session(client)
    exact_audio = client.post(
        f"/investigation-sessions/{audio_exact_session}/evidence/audio",
        files={"file": _audio_part("exact.wav", b"d" * MAX_AUDIO_UPLOAD_BYTES)},
    )
    assert exact_audio.status_code == 201
    assert exact_audio.json()["sequence_number"] == 1

    audio_oversize_session = _create_collecting_session(client)
    oversized_audio = client.post(
        f"/investigation-sessions/{audio_oversize_session}/evidence/audio",
        files={"file": _audio_part("too-big.wav", b"e" * (MAX_AUDIO_UPLOAD_BYTES + 1))},
    )
    assert oversized_audio.status_code == 413
    assert oversized_audio.json()["detail"]["category"] == "upload_too_large"
    assert not list((root / audio_oversize_session / "evidence").glob("*.json"))
    assert not list((root / audio_oversize_session / "evidence" / "payloads").glob("*"))

    next_audio = client.post(
        f"/investigation-sessions/{audio_oversize_session}/evidence/audio",
        files={"file": _audio_part("next.wav", b"f")},
    )
    assert next_audio.status_code == 201
    assert next_audio.json()["sequence_number"] == 1


def test_evidence_rollback_on_payload_and_metadata_failure(evidence_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _, root = evidence_test_context
    session_id = _create_collecting_session(client)
    original_replace = evidence_store_module.os.replace

    payload_fail_calls = {"count": 0}

    def _fail_first_replace(src: str, dst: str):
        payload_fail_calls["count"] += 1
        raise OSError("simulated payload replace failure")

    monkeypatch.setattr(evidence_store_module.os, "replace", _fail_first_replace)
    payload_failed = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("fail.png", b"payload")},
    )
    assert payload_failed.status_code == 500
    assert payload_failed.json()["detail"]["category"] == "evidence_storage_error"
    assert not list((root / session_id / "evidence" / "payloads").glob("*"))
    assert not list((root / session_id / "evidence").glob("*.json"))

    monkeypatch.setattr(evidence_store_module.os, "replace", original_replace)
    counter = {"count": 0}

    def _fail_on_second_replace(src: str, dst: str):
        counter["count"] += 1
        if counter["count"] == 2:
            raise OSError("simulated metadata replace failure")
        return original_replace(src, dst)

    first_ok = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("ok.png", b"one")},
    )
    assert first_ok.status_code == 201

    monkeypatch.setattr(evidence_store_module.os, "replace", _fail_on_second_replace)

    failed = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("fail-two.png", b"two")},
    )
    assert failed.status_code == 500
    assert failed.json()["detail"]["category"] == "evidence_storage_error"

    listed = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert [item["sequence_number"] for item in listed.json()] == [1]


def test_evidence_delete_safety_and_tampered_paths(evidence_test_context):
    client, _, _, root = evidence_test_context
    for unsafe in ["../escape.bin", "/abs/escape.bin", "C:/escape.bin"]:
        session_id = _create_collecting_session(client)
        upload = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("safe.png", b"bytes")})
        assert upload.status_code == 201
        evidence_id = upload.json()["evidence_id"]
        metadata_path = root / session_id / "evidence" / f"{evidence_id}.json"
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload["storage_ref"] = unsafe
        metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        response = client.delete(f"/investigation-sessions/{session_id}/evidence/{evidence_id}")
        assert response.status_code == 404
        assert not metadata_path.exists()
        assert list((root / "corrupt").glob("*.json"))

    session_a = _create_collecting_session(client)
    session_b = _create_collecting_session(client)
    a = client.post(f"/investigation-sessions/{session_a}/evidence/image", files={"file": _image_part("a.png", b"a")})
    b = client.post(f"/investigation-sessions/{session_b}/evidence/image", files={"file": _image_part("b.png", b"b")})
    assert a.status_code == 201 and b.status_code == 201
    metadata_path_b = root / session_a / "evidence" / f"{a.json()['evidence_id']}.json"
    payload = json.loads(metadata_path_b.read_text(encoding="utf-8"))
    payload["storage_ref"] = f"../{session_b}/evidence/escape.bin"
    metadata_path_b.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    response = client.delete(f"/investigation-sessions/{session_a}/evidence/{a.json()['evidence_id']}")
    assert response.status_code == 404
    assert (root / session_b / "evidence" / "payloads").exists()

    sentinel = root.parent / "outside.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    safe_session = _create_collecting_session(client)
    safe_upload = client.post(f"/investigation-sessions/{safe_session}/evidence/image", files={"file": _image_part("safe2.png", b"safe2")})
    assert safe_upload.status_code == 201
    safe_metadata = root / safe_session / "evidence" / f"{safe_upload.json()['evidence_id']}.json"
    payload = json.loads(safe_metadata.read_text(encoding="utf-8"))
    payload["storage_ref"] = str(sentinel)
    safe_metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    response = client.delete(f"/investigation-sessions/{safe_session}/evidence/{safe_upload.json()['evidence_id']}")
    assert response.status_code == 404
    assert sentinel.exists()


def test_evidence_corruption_quarantine_and_stable_listing(evidence_test_context):
    client, _, _, root = evidence_test_context
    session_id = _create_collecting_session(client)

    valid = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("ok.png", b"ok")})
    assert valid.status_code == 201
    valid_id = valid.json()["evidence_id"]
    valid_metadata = root / session_id / "evidence" / f"{valid_id}.json"

    corrupt_json = root / session_id / "evidence" / "corrupt.json"
    corrupt_json.write_text("{ broken", encoding="utf-8")

    invalid_schema = root / session_id / "evidence" / "invalid.json"
    invalid_schema.write_text(json.dumps({"schema_version": "1.0", "evidence_id": "bad"}, ensure_ascii=False), encoding="utf-8")

    unsafe = json.loads(valid_metadata.read_text(encoding="utf-8"))
    unsafe["storage_ref"] = "../escape.bin"
    valid_metadata.write_text(json.dumps(unsafe, ensure_ascii=False, indent=2), encoding="utf-8")

    first = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert first.status_code == 200
    assert first.json() == []
    assert not corrupt_json.exists()
    assert not invalid_schema.exists()
    assert list((root / "corrupt").glob("*.json"))

    second = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert second.status_code == 200
    assert second.json() == []


def test_evidence_authentication_and_zero_call_guarantee(evidence_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _, _ = evidence_test_context
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "phase2b-token")

    unauthorized_upload = client.post(
        "/investigation-sessions/00000000-0000-0000-0000-000000000000/evidence/image",
        files={"file": _image_part("a.png", b"a")},
    )
    assert unauthorized_upload.status_code == 401

    unauthorized_list = client.get("/investigation-sessions/00000000-0000-0000-0000-000000000000/evidence")
    assert unauthorized_list.status_code == 401

    unauthorized_delete = client.delete("/investigation-sessions/00000000-0000-0000-0000-000000000000/evidence/00000000-0000-0000-0000-000000000000")
    assert unauthorized_delete.status_code == 401

    by_query = client.get(
        "/investigation-sessions/00000000-0000-0000-0000-000000000000/evidence",
        params={"token": "phase2b-token"},
    )
    assert by_query.status_code == 404

    by_bearer = client.get(
        "/investigation-sessions/00000000-0000-0000-0000-000000000000/evidence",
        headers={"Authorization": "Bearer phase2b-token"},
    )
    assert by_bearer.status_code == 404

    counters = {"openai": 0, "context": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            counters["openai"] += 1

    def _forbidden_context_loader():
        counters["context"] += 1
        return None

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)
    monkeypatch.setattr(api, "_load_investigation_context_snapshot_from_context_fusion", _forbidden_context_loader)
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    session_id = _create_collecting_session(client)
    upload = client.post(f"/investigation-sessions/{session_id}/evidence/image", files={"file": _image_part("ok.png", b"ok")})
    assert upload.status_code == 201
    listed = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert listed.status_code == 200
    deleted = client.delete(f"/investigation-sessions/{session_id}/evidence/{upload.json()['evidence_id']}")
    assert deleted.status_code == 200
    assert counters["openai"] == 0
    assert counters["context"] == 0


def test_evidence_concurrent_uploads_receive_unique_sequences(evidence_test_context):
    client, _, evidence_store, _ = evidence_test_context
    session_id = _create_collecting_session(client)

    barrier = threading.Barrier(3)
    results: list[tuple[str, int]] = []
    errors: list[BaseException] = []

    def _worker(payload: bytes, filename: str):
        try:
            barrier.wait(timeout=5)
            record, created = evidence_store.upload_evidence(
                session_id=session_id,
                evidence_type=InvestigationEvidenceType.IMAGE,
                raw_bytes=payload,
                mime_type="image/png",
                original_filename=filename,
                request=InvestigationEvidenceCreateRequest(
                    source="desktop",
                    client_timestamp_utc=datetime.now(timezone.utc),
                    normalized_text=None,
                    metadata=None,
                    filename=filename,
                    mime_type="image/png",
                    width=800,
                    height=600,
                    duration_seconds=None,
                ),
            )
            assert created is True
            results.append((record.evidence_id, record.sequence_number))
        except BaseException as exc:  # pragma: no cover - used only for thread capture
            errors.append(exc)

    thread_a = threading.Thread(target=_worker, args=(b"thread-a", "a.png"), daemon=True)
    thread_b = threading.Thread(target=_worker, args=(b"thread-b", "b.png"), daemon=True)
    thread_a.start()
    thread_b.start()
    barrier.wait(timeout=5)
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert not errors
    assert sorted(sequence for _, sequence in results) == [1, 2]


def test_evidence_upload_rollback_and_delete_failures(evidence_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _, root = evidence_test_context
    session_id = _create_collecting_session(client)

    original_replace = evidence_store_module.os.replace
    call_counter = {"count": 0}

    def _fail_first_replace(src: str, dst: str):
        call_counter["count"] += 1
        raise OSError("simulated payload replace failure")

    monkeypatch.setattr(evidence_store_module.os, "replace", _fail_first_replace)
    payload_failed = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("fail.png", b"payload")},
    )
    assert payload_failed.status_code == 500
    assert not list((root / session_id / "evidence" / "payloads").glob("*"))
    assert not list((root / session_id / "evidence").glob("*.json"))

    monkeypatch.setattr(evidence_store_module.os, "replace", original_replace)
    first = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("one.png", b"one")},
    )
    assert first.status_code == 201

    def _fail_on_metadata_replace(src: str, dst: str):
        call_counter["count"] += 1
        if call_counter["count"] == 2:
            raise OSError("simulated metadata replace failure")
        return original_replace(src, dst)

    call_counter["count"] = 0
    monkeypatch.setattr(evidence_store_module.os, "replace", _fail_on_metadata_replace)
    failed = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        files={"file": _image_part("two.png", b"two")},
    )
    assert failed.status_code == 500
    assert len([path for path in (root / session_id / "evidence").glob("*.json") if path.name != "_evidence_manifest.json"]) == 1

    remaining = client.get(f"/investigation-sessions/{session_id}/evidence")
    assert [item["sequence_number"] for item in remaining.json()] == [1]

    delete_fail_counter = {"count": 0}

    def _fail_delete_replace(src: str, dst: str):
        delete_fail_counter["count"] += 1
        raise OSError("simulated delete payload move failure")

    monkeypatch.setattr(evidence_store_module.os, "replace", _fail_delete_replace)
    delete_failed = client.delete(f"/investigation-sessions/{session_id}/evidence/{first.json()['evidence_id']}")
    assert delete_failed.status_code == 500
    assert client.get(f"/investigation-sessions/{session_id}/evidence").status_code == 200

    monkeypatch.setattr(evidence_store_module.os, "replace", original_replace)
    metadata_path = root / session_id / "evidence" / f"{first.json()['evidence_id']}.json"
    unlink_original = Path.unlink

    def _fail_metadata_unlink(self: Path, *args, **kwargs):
        if self == metadata_path:
            raise OSError("simulated metadata unlink failure")
        return unlink_original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _fail_metadata_unlink)
    delete_failed_again = client.delete(f"/investigation-sessions/{session_id}/evidence/{first.json()['evidence_id']}")
    assert delete_failed_again.status_code == 500
    assert metadata_path.exists()


def test_evidence_routes_registered_for_phase2b():
    route_paths = {route.path for route in api.app.routes}
    assert "/investigation-sessions/{session_id}/evidence/image" in route_paths
    assert "/investigation-sessions/{session_id}/evidence/audio" in route_paths
    assert "/investigation-sessions/{session_id}/evidence" in route_paths
    assert "/investigation-sessions/{session_id}/evidence/{evidence_id}" in route_paths
