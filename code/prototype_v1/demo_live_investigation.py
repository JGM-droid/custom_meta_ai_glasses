from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from investigations import (
    INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
    InvestigationAnalysisAttemptStore,
    InvestigationAnalysisProviderMissingApiKeyError,
    InvestigationAnalysisResponse,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationInteractionContext,
    InvestigationInteractionState,
    InvestigationOrchestrator,
    InvestigationOrchestrationError,
    InvestigationOrchestrationOutcome,
    InvestigationOrchestrationProgressEvent,
    InvestigationOrchestrationStage,
    InvestigationOrchestrationStoredResult,
    InvestigationOpenAIProviderConfig,
    InvestigationRetainedResult,
    InvestigationSessionStore,
    InvestigationSessionStatus,
    OpenAIInvestigationAnalysisProvider,
    apply_start_transition,
    build_copilot_prompt,
    save_canonical_investigation_result,
)


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
SUPPORTED_IMAGE_KINDS = {"png": "image/png", "jpeg": "image/jpeg"}
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TIMEOUT_SECONDS = 45.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class DemoInvestigationError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class DemoRunOutcome:
    exit_code: int
    session_root: Path
    session_id: str | None
    analysis_attempt_id: str | None
    provider_model: str
    image_count: int
    elapsed_seconds: float
    progress_events: list[InvestigationOrchestrationProgressEvent]
    response: InvestigationAnalysisResponse | None
    cleanup_performed: bool
    dry_run: bool


class ManualSmokeTestResultPersistence:
    def __init__(self, session_store: InvestigationSessionStore, session_root: Path):
        self._session_store = session_store
        self._session_root = session_root
        self._smoke_results_dir = self._session_root / "manual_results"
        self._canonical_results_root = self._session_root / "canonical_results"
        self._smoke_results_dir.mkdir(parents=True, exist_ok=True)
        self._canonical_results_root.mkdir(parents=True, exist_ok=True)

    def load_completed_result(self, *, session_id: str) -> InvestigationOrchestrationStoredResult | None:
        session = self._session_store.load_session(session_id)
        result_id = session.completed_result_id
        if not result_id:
            return None

        smoke_path = self._smoke_results_dir / f"{result_id}.json"
        if smoke_path.exists() and smoke_path.is_file():
            payload = json.loads(smoke_path.read_text(encoding="utf-8"))
            response = InvestigationAnalysisResponse.model_validate(payload["response"])
            return InvestigationOrchestrationStoredResult(result_id=result_id, response=response)

        return None

    def persist_result(
        self,
        *,
        session,
        request_package,
        response: InvestigationAnalysisResponse,
    ) -> str:
        result_id = str(uuid4())
        smoke_record = {
            "result_id": result_id,
            "session_id": session.session_id,
            "analysis_attempt_id": request_package.analysis_attempt_id,
            "response": response.model_dump(mode="json"),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json(self._smoke_results_dir / f"{result_id}.json", smoke_record)

        if len(request_package.ordered_evidence_inputs) >= 2:
            retained_result = self._build_retained_result(session_id=session.session_id, request_package=request_package, response=response)
            save_canonical_investigation_result(
                self._canonical_results_root,
                result_id=result_id,
                retained_result=retained_result,
                session_id=session.session_id,
                analysis_attempt_id=request_package.analysis_attempt_id,
            )

        return result_id

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f"{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)

            os.replace(str(temp_path), str(path))
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _build_retained_result(*, session_id: str, request_package, response: InvestigationAnalysisResponse) -> InvestigationRetainedResult:
        image_order = []
        for index, attachment in enumerate(request_package.ordered_evidence_inputs):
            metadata = attachment.evidence_metadata or {}
            image_order.append(f"{index + 1}:{metadata.get('filename', attachment.evidence_id)}")
        retained = InvestigationRetainedResult(
            schema_version=response.schema_version,
            projection_version="1.0",
            investigation_id=f"inv_{uuid5(NAMESPACE_URL, f'{session_id}|{request_package.analysis_attempt_id}').hex[:16]}",
            session_id=session_id,
            status="analyzed",
            diagnosis=response.concise_diagnosis,
            required_next_action=response.immediate_recommended_action,
            image_count=len(request_package.ordered_evidence_inputs),
            image_order=image_order,
            used_user_explanation=request_package.normalized_explanation_text or "",
            completed_at_utc=datetime.now(timezone.utc),
            context_used=False,
            context_staleness="unknown",
            context_signal_age_seconds=None,
            copilot_prompt="placeholder",
        )
        retained.copilot_prompt = build_copilot_prompt(retained)
        return retained


class _DryRunProvider:
    def __init__(self, model: str):
        self.model = model
        self.calls: list[str] = []

    def analyze(self, request_package) -> InvestigationAnalysisResponse:
        self.calls.append(request_package.analysis_attempt_id)
        return InvestigationAnalysisResponse(
            schema_version=INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Dry-run diagnosis: the runner and orchestration path are wired correctly.",
            immediate_recommended_action="Proceed with the live run using the same images and explanation.",
            supporting_observations=[
                f"Received {len(request_package.ordered_evidence_inputs)} image(s) in the preserved input order.",
                "No live OpenAI request was made.",
            ],
            confidence_or_uncertainty="Deterministic smoke test output only.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


@dataclass(frozen=True)
class _PreparedImage:
    path: Path
    mime_type: str
    filename: str
    raw_bytes: bytes


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual live investigation smoke-test runner")
    parser.add_argument("--image", action="append", default=[], help="Local image path (repeat 1-3 times)")
    parser.add_argument("--explanation", help="User explanation for the investigation")
    parser.add_argument("--prompt-explanation", action="store_true", help="Prompt for the explanation interactively")
    parser.add_argument("--session-root", help="Override the demo session workspace root")
    parser.add_argument("--model", help="Override the OpenAI model for this run")
    parser.add_argument("--timeout-seconds", type=float, help="Override the OpenAI timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Run the production orchestration path with a fake provider")
    parser.add_argument("--keep-session", action="store_true", help="Preserve the generated demo workspace")
    parser.add_argument("--verbose", action="store_true", help="Print traceback details on failure")
    return parser.parse_args(argv)


def _resolve_explanation(args: argparse.Namespace) -> str:
    explanation = str(args.explanation or "").strip()
    if explanation:
        return explanation
    if args.prompt_explanation and sys.stdin.isatty():
        prompted = input("Explanation: ").strip()
        if prompted:
            return prompted
    raise DemoInvestigationError("invalid_input", "--explanation is required and cannot be blank.")


def _validate_timeout(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise DemoInvestigationError("invalid_input", "--timeout-seconds must be a positive finite number.")
    return float(timeout_seconds)


def _resolve_model_override(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = str(model).strip()
    if not normalized:
        raise DemoInvestigationError("invalid_input", "--model must be a non-blank string.")
    if any(ch in normalized for ch in "\r\n\t"):
        raise DemoInvestigationError("invalid_input", "--model must be a single-line value.")
    return normalized


def _resolve_session_root(session_root: str | None) -> tuple[Path, bool]:
    if session_root:
        root = Path(session_root).expanduser()
        if root.exists() and not root.is_dir():
            raise DemoInvestigationError("invalid_input", "--session-root must point to a directory.")
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve(strict=False), False

    created = Path(tempfile.mkdtemp(prefix="manual-investigation-demo-"))
    return created.resolve(strict=False), True


def _resolve_openai_api_key() -> str:
    return str(os.environ.get("OPENAI_API_KEY") or "").strip()


def _resolve_provider_model(model_override: str | None) -> str:
    if model_override:
        return model_override
    env_model = str(os.environ.get("INVESTIGATION_OPENAI_MODEL") or os.environ.get("OPENAI_VISION_MODEL") or "").strip()
    return env_model or DEFAULT_MODEL


def _resolve_provider_timeout(timeout_override: float | None) -> float:
    if timeout_override is not None:
        return timeout_override
    raw_timeout = str(os.environ.get("INVESTIGATION_OPENAI_TIMEOUT_SECONDS") or "").strip()
    if not raw_timeout:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise DemoInvestigationError("invalid_input", "INVESTIGATION_OPENAI_TIMEOUT_SECONDS must be numeric.") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise DemoInvestigationError("invalid_input", "INVESTIGATION_OPENAI_TIMEOUT_SECONDS must be positive.")
    return timeout_seconds


def _build_provider_config(*, api_key: str, session_root: Path, model_override: str | None, timeout_seconds: float | None) -> InvestigationOpenAIProviderConfig:
    return InvestigationOpenAIProviderConfig(
        api_key=api_key,
        model=_resolve_provider_model(model_override),
        timeout_seconds=_resolve_provider_timeout(timeout_seconds),
        sessions_root=session_root,
    )


def _create_live_provider(*, api_key: str, session_root: Path, model_override: str | None, timeout_seconds: float | None) -> OpenAIInvestigationAnalysisProvider:
    return OpenAIInvestigationAnalysisProvider(
        config=_build_provider_config(
            api_key=api_key,
            session_root=session_root,
            model_override=model_override,
            timeout_seconds=timeout_seconds,
        )
    )


def _prepare_images(image_paths: Sequence[str]) -> list[_PreparedImage]:
    if not image_paths:
        raise DemoInvestigationError("invalid_input", "At least one --image is required.")
    if len(image_paths) > 3:
        raise DemoInvestigationError("invalid_input", "At most three --image values are allowed.")

    prepared: list[_PreparedImage] = []
    for raw_path in image_paths:
        path = Path(raw_path).expanduser()
        resolved = path.resolve(strict=False)
        if not resolved.exists() or not resolved.is_file():
            raise DemoInvestigationError("invalid_input", f"Image file not found: {raw_path}")

        suffix = resolved.suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            raise DemoInvestigationError("invalid_input", f"Unsupported image extension: {resolved.name}")

        payload_preview = resolved.read_bytes()[:8]
        if payload_preview.startswith(PNG_SIGNATURE):
            kind = "png"
        elif payload_preview.startswith(JPEG_SIGNATURE):
            kind = "jpeg"
        else:
            kind = None
        if kind not in SUPPORTED_IMAGE_KINDS:
            raise DemoInvestigationError("invalid_input", f"Unsupported image MIME type: {resolved.name}")

        raw_bytes = resolved.read_bytes()
        if not raw_bytes:
            raise DemoInvestigationError("invalid_input", f"Image file is empty: {resolved.name}")

        prepared.append(
            _PreparedImage(
                path=resolved,
                mime_type=SUPPORTED_IMAGE_KINDS[kind],
                filename=resolved.name,
                raw_bytes=raw_bytes,
            )
        )

    return prepared


def _create_session_state(session_store: InvestigationSessionStore) -> str:
    session = session_store.create_session(client_metadata={"runner": "manual_live_investigation"})
    collecting = session_store.mutate_session(
        session.session_id,
        lambda current: apply_start_transition(current, expected_revision=0),
    )
    if collecting.status != InvestigationSessionStatus.COLLECTING:
        raise DemoInvestigationError("session_setup_failure", "Failed to move the session into collecting state.")
    return collecting.session_id


def _upload_images(
    *,
    evidence_store: InvestigationEvidenceStore,
    session_id: str,
    images: Sequence[_PreparedImage],
) -> list[str]:
    evidence_ids: list[str] = []
    for image in images:
        record, created = evidence_store.upload_evidence(
            session_id=session_id,
            evidence_type=InvestigationEvidenceType.IMAGE,
            raw_bytes=image.raw_bytes,
            mime_type=image.mime_type,
            original_filename=image.filename,
            request=InvestigationEvidenceCreateRequest(
                source="manual_demo_runner",
                client_timestamp_utc=datetime.now(timezone.utc),
                normalized_text=None,
                metadata=None,
                filename=image.filename,
                mime_type=image.mime_type,
                width=None,
                height=None,
                duration_seconds=None,
            ),
        )
        if not created:
            raise DemoInvestigationError("evidence_upload_failure", f"Failed to upload image: {image.filename}")
        evidence_ids.append(record.evidence_id)
    return evidence_ids


def _build_interaction_context(*, session_id: str, evidence_ids: Sequence[str], explanation: str) -> InvestigationInteractionContext:
    return InvestigationInteractionContext(
        schema_version="1.0",
        session_id=session_id,
        interaction_state=InvestigationInteractionState.READY_FOR_CONFIRMATION,
        selected_capture_evidence_ids=list(evidence_ids),
        normalized_explanation_text=explanation,
        analysis_confirmed=True,
    )


def _progress_label(event: InvestigationOrchestrationProgressEvent) -> str:
    labels = {
        InvestigationOrchestrationStage.VALIDATING: "Preparing investigation",
        InvestigationOrchestrationStage.FREEZING_EVIDENCE: "Freezing evidence",
        InvestigationOrchestrationStage.ESTABLISHING_ATTEMPT: "Establishing analysis attempt",
        InvestigationOrchestrationStage.BUILDING_REQUEST: "Building AI request",
        InvestigationOrchestrationStage.ANALYZING: "AI is analyzing",
        InvestigationOrchestrationStage.VALIDATING_RESPONSE: "Validating response",
        InvestigationOrchestrationStage.PERSISTING_RESULT: "Persisting result",
        InvestigationOrchestrationStage.COMPLETING: "Completing investigation",
        InvestigationOrchestrationStage.COMPLETED: "Investigation complete",
        InvestigationOrchestrationStage.FAILED: "Investigation failed",
    }
    return labels.get(event.stage, event.stage.value)


def _print_progress(event: InvestigationOrchestrationProgressEvent, *, stream) -> None:
    print(f"[{event.sequence_number}] {_progress_label(event)}", file=stream)


def _summarize_success(
    *,
    stream,
    outcome: InvestigationOrchestrationOutcome,
    provider_model: str,
    image_count: int,
    elapsed_seconds: float,
) -> None:
    response = outcome.response
    if response is None:
        raise DemoInvestigationError("unexpected_orchestration_state", "Missing structured response from orchestrator.")

    print("INVESTIGATION COMPLETE", file=stream)
    print(file=stream)
    print("Diagnosis:", file=stream)
    print(response.concise_diagnosis, file=stream)
    print(file=stream)
    print("Immediate action:", file=stream)
    print(response.immediate_recommended_action, file=stream)
    print(file=stream)
    print("Supporting observations:", file=stream)
    for index, observation in enumerate(response.supporting_observations, start=1):
        print(f"{index}. {observation}", file=stream)
    print(file=stream)
    print("Confidence / uncertainty:", file=stream)
    print(response.confidence_or_uncertainty, file=stream)
    if response.warning_or_blocker:
        print(file=stream)
        print("Warning:", file=stream)
        print(response.warning_or_blocker, file=stream)
    if response.follow_up_capture_request:
        print(file=stream)
        print("Follow-up capture requested:", file=stream)
        print(response.follow_up_capture_request, file=stream)
    print(file=stream)
    print(f"session_id: {outcome.session_id}", file=stream)
    print(f"analysis_attempt_id: {outcome.analysis_attempt_id}", file=stream)
    print(f"image_count: {image_count}", file=stream)
    print(f"provider_model: {provider_model}", file=stream)
    print(f"elapsed_seconds: {elapsed_seconds:.2f}", file=stream)


def _cleanup_runner_workspace(session_root: Path) -> None:
    shutil.rmtree(session_root, ignore_errors=False)


def run_manual_investigation(argv: Sequence[str] | None = None, *, stdout=None, stderr=None, provider_factory=None) -> DemoRunOutcome:
    args = _parse_args(argv)
    stdout_stream = stdout or sys.stdout
    stderr_stream = stderr or sys.stderr
    start_time = perf_counter()
    session_root = Path(tempfile.gettempdir()) / "manual-investigation-demo-uninitialized"
    owned_root = False
    images: list[_PreparedImage] = []
    provider_model = DEFAULT_MODEL
    session_id: str | None = None

    try:
        explanation = _resolve_explanation(args)
        timeout_seconds = _validate_timeout(args.timeout_seconds)
        model_override = _resolve_model_override(args.model)
        images = _prepare_images(args.image)
        session_root, owned_root = _resolve_session_root(args.session_root)

        session_store = InvestigationSessionStore(session_root)
        evidence_store = InvestigationEvidenceStore(session_store)
        attempt_store = InvestigationAnalysisAttemptStore(session_store)

        provider_model = _resolve_provider_model(model_override)
        session_id = _create_session_state(session_store)
        evidence_ids = _upload_images(evidence_store=evidence_store, session_id=session_id, images=images)
        interaction_context = _build_interaction_context(session_id=session_id, evidence_ids=evidence_ids, explanation=explanation)

        if args.dry_run:
            provider = _DryRunProvider(model=provider_model)
            print("DRY RUN — no OpenAI request was made", file=stdout_stream)
        else:
            api_key = _resolve_openai_api_key()
            if not api_key:
                raise DemoInvestigationError(
                    "missing_configuration",
                    "OPENAI_API_KEY is required for live runs.",
                )
            if provider_factory is not None:
                provider = provider_factory(args, session_root)
            else:
                provider = _create_live_provider(
                    api_key=api_key,
                    session_root=session_root,
                    model_override=model_override,
                    timeout_seconds=timeout_seconds,
                )

        persistence = ManualSmokeTestResultPersistence(session_store, session_root)
        progress_events: list[InvestigationOrchestrationProgressEvent] = []

        def _sink(event: InvestigationOrchestrationProgressEvent) -> None:
            progress_events.append(event)
            _print_progress(event, stream=stdout_stream)

        orchestrator = InvestigationOrchestrator(
            session_store=session_store,
            evidence_store=evidence_store,
            attempt_store=attempt_store,
            analysis_provider=provider,
            result_persistence=persistence,
            progress_sink=_sink,
        )

        outcome = orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=session_store.load_session(session_id).revision,
            interaction_context=interaction_context,
        )

        elapsed_seconds = perf_counter() - start_time
        _summarize_success(
            stream=stdout_stream,
            outcome=outcome,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=elapsed_seconds,
        )

        cleanup_performed = False
        if owned_root and not args.keep_session:
            _cleanup_runner_workspace(session_root)
            cleanup_performed = True

        return DemoRunOutcome(
            exit_code=0,
            session_root=session_root,
            session_id=session_id,
            analysis_attempt_id=outcome.analysis_attempt_id,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=elapsed_seconds,
            progress_events=progress_events,
            response=outcome.response,
            cleanup_performed=cleanup_performed,
            dry_run=bool(args.dry_run),
        )
    except DemoInvestigationError as exc:
        print(f"FAILURE: {exc.category}", file=stderr_stream)
        print(exc.message, file=stderr_stream)
        if owned_root or args.keep_session:
            print(f"Session workspace preserved at: {session_root}", file=stderr_stream)
        return DemoRunOutcome(
            exit_code=1,
            session_root=session_root,
            session_id=session_id,
            analysis_attempt_id=None,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=perf_counter() - start_time,
            progress_events=[],
            response=None,
            cleanup_performed=False,
            dry_run=bool(args.dry_run),
        )
    except InvestigationOrchestrationError as exc:
        category = getattr(exc, "category", "orchestration_failure")
        message = str(exc).strip() or "Investigation orchestration failed."
        cause = str(exc.__cause__).strip() if exc.__cause__ is not None else ""
        print(f"FAILURE: {category}", file=stderr_stream)
        if cause:
            print(f"{message} ({cause})", file=stderr_stream)
        else:
            print(message, file=stderr_stream)
        print(f"Session workspace preserved at: {session_root}", file=stderr_stream)
        return DemoRunOutcome(
            exit_code=1,
            session_root=session_root,
            session_id=session_id,
            analysis_attempt_id=None,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=perf_counter() - start_time,
            progress_events=[],
            response=None,
            cleanup_performed=False,
            dry_run=bool(args.dry_run),
        )
    except InvestigationAnalysisProviderMissingApiKeyError as exc:
        print("FAILURE: missing_configuration", file=stderr_stream)
        print(str(exc), file=stderr_stream)
        return DemoRunOutcome(
            exit_code=1,
            session_root=session_root,
            session_id=session_id,
            analysis_attempt_id=None,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=perf_counter() - start_time,
            progress_events=[],
            response=None,
            cleanup_performed=False,
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:
        print("FAILURE: unexpected_error", file=stderr_stream)
        print(str(exc).strip() or exc.__class__.__name__, file=stderr_stream)
        print(f"Session workspace preserved at: {session_root}", file=stderr_stream)
        return DemoRunOutcome(
            exit_code=1,
            session_root=session_root,
            session_id=session_id,
            analysis_attempt_id=None,
            provider_model=provider_model,
            image_count=len(images),
            elapsed_seconds=perf_counter() - start_time,
            progress_events=[],
            response=None,
            cleanup_performed=False,
            dry_run=bool(args.dry_run),
        )
    finally:
        if not args.dry_run and not args.keep_session and owned_root:
            # Successful runs clean up above; failures intentionally preserve the workspace.
            pass


def main(argv: Sequence[str] | None = None) -> int:
    outcome = run_manual_investigation(argv)
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())