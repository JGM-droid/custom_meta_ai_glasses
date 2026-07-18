from __future__ import annotations

import hashlib
import inspect
import io
import tempfile
from pathlib import Path

import pytest

import demo_live_investigation as demo
from investigations import InvestigationSessionStore, InvestigationSessionStatus


TEST_IMAGES_DIR = Path(__file__).resolve().parent / "test_images"


class RecordingProvider:
    def __init__(self, *, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    def analyze(self, request_package):
        self.calls.append(request_package)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _image(name: str) -> Path:
    return TEST_IMAGES_DIR / name


def _run(argv: list[str], *, provider_factory=None, monkeypatch=None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    outcome = demo.run_manual_investigation(argv, stdout=stdout, stderr=stderr, provider_factory=provider_factory)
    return outcome, stdout.getvalue(), stderr.getvalue()


def _success_argv(*, images: list[Path], explanation: str = "I am trying to understand why this Python environment is not activating.", extra: list[str] | None = None) -> list[str]:
    argv: list[str] = []
    for image in images:
        argv.extend(["--image", str(image)])
    argv.extend(["--explanation", explanation])
    if extra:
        argv.extend(extra)
    return argv


def test_one_image_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def provider_factory(_args, _session_root):
        return RecordingProvider(response=demo.InvestigationAnalysisResponse(
            schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Accepted.",
            immediate_recommended_action="Continue.",
            supporting_observations=["One image was accepted."],
            confidence_or_uncertainty="High confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        ))

    outcome, stdout, stderr = _run(_success_argv(images=[_image("test_image.png")], extra=["--session-root", str(tmp_path / "workspace")]), provider_factory=provider_factory)
    assert outcome.exit_code == 0
    assert outcome.image_count == 1
    assert "INVESTIGATION COMPLETE" in stdout
    assert stderr == ""


@pytest.mark.parametrize(
    "image_names",
    [
        ["test_image.png", "133959575898717423.jpg"],
        ["test_image.png", "133959575898717423.jpg", "133973540999428167.jpg"],
    ],
)
def test_two_and_three_images_preserve_input_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, image_names: list[str]):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    def provider_factory(_args, _session_root):
        provider = RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Order preserved."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )
        captured["provider"] = provider
        return provider

    outcome, _, _ = _run(_success_argv(images=[_image(name) for name in image_names], extra=["--session-root", str(tmp_path / "workspace")]), provider_factory=provider_factory)
    request = captured["provider"].calls[0]
    assert outcome.exit_code == 0
    assert [item.evidence_metadata["filename"] for item in request.ordered_evidence_inputs] == image_names


def test_zero_images_rejected(monkeypatch: pytest.MonkeyPatch):
    outcome, stdout, stderr = _run(["--explanation", "hello"], provider_factory=lambda *_: RecordingProvider(response=None))
    assert outcome.exit_code != 0
    assert "At least one --image is required." in stderr
    assert stdout == ""


def test_fourth_image_rejected(monkeypatch: pytest.MonkeyPatch):
    outcome, _, stderr = _run(
        _success_argv(
            images=[
                _image("test_image.png"),
                _image("133959575898717423.jpg"),
                _image("133973540999428167.jpg"),
                _image("134026336827829474.jpg"),
            ],
        ),
        provider_factory=lambda *_: RecordingProvider(response=None),
    )
    assert outcome.exit_code != 0
    assert "At most three --image values are allowed." in stderr


def test_missing_image_rejected(tmp_path: Path):
    missing = tmp_path / "missing.png"
    outcome, _, stderr = _run(["--image", str(missing), "--explanation", "hello"], provider_factory=lambda *_: RecordingProvider(response=None))
    assert outcome.exit_code != 0
    assert "Image file not found" in stderr


def test_unsupported_mime_rejected(tmp_path: Path):
    bogus = tmp_path / "bogus.png"
    bogus.write_text("not an image", encoding="utf-8")
    outcome, _, stderr = _run(["--image", str(bogus), "--explanation", "hello"], provider_factory=lambda *_: RecordingProvider(response=None))
    assert outcome.exit_code != 0
    assert "Unsupported image MIME type" in stderr


def test_blank_explanation_rejected(tmp_path: Path):
    outcome, _, stderr = _run(["--image", str(_image("test_image.png")), "--explanation", "   "], provider_factory=lambda *_: RecordingProvider(response=None))
    assert outcome.exit_code != 0
    assert "--explanation is required" in stderr


def test_dry_run_performs_no_network_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    called = False

    def provider_factory(*_args):
        nonlocal called
        called = True
        return RecordingProvider(response=None)

    outcome, stdout, stderr = _run(
        _success_argv(images=[_image("test_image.png")], extra=["--dry-run", "--session-root", str(tmp_path / "workspace")]),
        provider_factory=provider_factory,
    )
    assert outcome.exit_code == 0
    assert called is False
    assert "DRY RUN — no OpenAI request was made" in stdout
    assert stderr == ""


def test_dry_run_uses_production_orchestrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    called = False
    original = demo.InvestigationOrchestrator.run_confirmed_investigation

    def wrapped(self, *args, **kwargs):
        nonlocal called
        called = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(demo.InvestigationOrchestrator, "run_confirmed_investigation", wrapped)
    outcome, _, _ = _run(
        _success_argv(images=[_image("test_image.png")], extra=["--dry-run", "--session-root", str(tmp_path / "workspace")]),
    )
    assert outcome.exit_code == 0
    assert called is True


def test_dry_run_emits_deterministic_progress_sequence(tmp_path: Path):
    outcome, stdout, _ = _run(
        _success_argv(images=[_image("test_image.png"), _image("133959575898717423.jpg")], extra=["--dry-run", "--session-root", str(tmp_path / "workspace")]),
    )
    lines = [line for line in stdout.splitlines() if line.startswith("[")]
    assert outcome.exit_code == 0
    assert lines == [
        "[1] Preparing investigation",
        "[2] Freezing evidence",
        "[3] Establishing analysis attempt",
        "[4] Building AI request",
        "[5] AI is analyzing",
        "[6] Validating response",
        "[7] Persisting result",
        "[8] Completing investigation",
        "[9] Investigation complete",
    ]


def test_dry_run_prints_canonical_result_fields(tmp_path: Path):
    outcome, stdout, _ = _run(
        _success_argv(images=[_image("test_image.png")], extra=["--dry-run", "--session-root", str(tmp_path / "workspace")]),
    )
    assert outcome.exit_code == 0
    assert "INVESTIGATION COMPLETE" in stdout
    assert "Diagnosis:" in stdout
    assert "Immediate action:" in stdout
    assert "Supporting observations:" in stdout
    assert "Confidence / uncertainty:" in stdout
    assert "session_id:" in stdout
    assert "analysis_attempt_id:" in stdout
    assert "image_count: 1" in stdout
    assert "provider_model:" in stdout


def test_missing_api_key_fails_before_provider_call_in_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    called = False

    def provider_factory(*_args):
        nonlocal called
        called = True
        return RecordingProvider(response=None)

    outcome, _, stderr = _run(
        _success_argv(images=[_image("test_image.png")], extra=["--session-root", str(tmp_path / "workspace")]),
        provider_factory=provider_factory,
    )
    assert outcome.exit_code != 0
    assert called is False
    assert "OPENAI_API_KEY is required for live runs." in stderr


def test_model_override_reaches_provider_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    def fake_create_live_provider(*, api_key, session_root, model_override, timeout_seconds):
        captured["api_key"] = api_key
        captured["session_root"] = session_root
        captured["model_override"] = model_override
        captured["timeout_seconds"] = timeout_seconds
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Override captured."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    monkeypatch.setattr(demo, "_create_live_provider", fake_create_live_provider)
    outcome, _, _ = _run(
        _success_argv(
            images=[_image("test_image.png")],
            extra=["--session-root", str(tmp_path / "workspace"), "--model", "gpt-test-override", "--timeout-seconds", "12.5"],
        ),
    )
    assert outcome.exit_code == 0
    assert captured["api_key"] == "test-key"
    assert captured["model_override"] == "gpt-test-override"
    assert captured["timeout_seconds"] == 12.5


def test_timeout_override_is_validated(tmp_path: Path):
    outcome, _, stderr = _run(
        _success_argv(images=[_image("test_image.png")], extra=["--dry-run", "--timeout-seconds", "-1", "--session-root", str(tmp_path / "workspace")]),
    )
    assert outcome.exit_code != 0
    assert "--timeout-seconds must be a positive finite number." in stderr


def test_runner_creates_valid_session_through_production_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    workspace = tmp_path / "workspace"

    def provider_factory(*_args):
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Lifecycle completed."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png"), _image("133959575898717423.jpg")], extra=["--session-root", str(workspace), "--keep-session"]), provider_factory=provider_factory)
    session_store = InvestigationSessionStore(workspace)
    session = session_store.load_session(outcome.session_id)
    assert session.status == InvestigationSessionStatus.COMPLETED


def test_evidence_is_added_through_the_production_evidence_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    workspace = tmp_path / "workspace"

    def provider_factory(*_args):
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Evidence stored."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png"), _image("133959575898717423.jpg")], extra=["--session-root", str(workspace), "--keep-session"]), provider_factory=provider_factory)
    session_store = InvestigationSessionStore(workspace)
    evidence_store = demo.InvestigationEvidenceStore(session_store)
    evidence = evidence_store.list_evidence_for_analysis(outcome.session_id)
    assert [item.filename for item in evidence] == ["test_image.png", "133959575898717423.jpg"]


def test_source_images_remain_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    source = tmp_path / "source.png"
    source.write_bytes(_image("test_image.png").read_bytes())
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    def provider_factory(*_args):
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Source unchanged."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    outcome, _, _ = _run(_success_argv(images=[source], extra=["--session-root", str(tmp_path / "workspace")]), provider_factory=provider_factory)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert outcome.exit_code == 0
    assert before == after


def test_temporary_session_cleanup_affects_only_runner_owned_data(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def provider_factory(*_args):
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Cleanup."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png")]), provider_factory=provider_factory)
    assert outcome.exit_code == 0
    assert not outcome.session_root.exists()


def test_keep_session_preserves_runner_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def provider_factory(*_args):
        return RecordingProvider(
            response=demo.InvestigationAnalysisResponse(
                schema_version=demo.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                concise_diagnosis="Accepted.",
                immediate_recommended_action="Continue.",
                supporting_observations=["Preserved."],
                confidence_or_uncertainty="High confidence.",
                warning_or_blocker=None,
                follow_up_capture_request=None,
            )
        )

    workspace = tmp_path / "workspace"
    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png")], extra=["--session-root", str(workspace), "--keep-session"]), provider_factory=provider_factory)
    assert outcome.exit_code == 0
    assert workspace.exists()


def test_provider_failure_returns_nonzero_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def provider_factory(*_args):
        return RecordingProvider(error=RuntimeError("provider failed"))

    outcome, _, stderr = _run(_success_argv(images=[_image("test_image.png")], extra=["--session-root", str(tmp_path / "workspace")]), provider_factory=provider_factory)
    assert outcome.exit_code != 0
    assert "provider failed" in stderr


def test_provider_failure_does_not_mark_session_completed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    workspace = tmp_path / "workspace"

    def provider_factory(*_args):
        return RecordingProvider(error=RuntimeError("provider failed"))

    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png")], extra=["--session-root", str(workspace), "--keep-session"]), provider_factory=provider_factory)
    session_store = InvestigationSessionStore(workspace)
    session = session_store.load_session(outcome.session_id)
    assert session.status != InvestigationSessionStatus.COMPLETED


def test_no_fastapi_dashboard_device_behavior_is_added():
    source = inspect.getsource(demo)
    assert "FastAPI" not in source
    assert "dashboard.html" not in source
    assert "glasses_demo.py" not in source
    assert "android" not in source.lower()


def test_no_live_request_occurs_in_pytest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    called = False

    def provider_factory(*_args):
        nonlocal called
        called = True
        return RecordingProvider(response=None)

    outcome, _, _ = _run(_success_argv(images=[_image("test_image.png")], extra=["--dry-run", "--session-root", str(tmp_path / "workspace")]), provider_factory=provider_factory)
    assert outcome.exit_code == 0
    assert called is False
