from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .models import InvestigationRetainedResult


class InvestigationStoreError(RuntimeError):
    pass


class InvestigationStoreNotFound(InvestigationStoreError):
    pass


def save_latest_investigation_result(path: Path, result: InvestigationRetainedResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)

        os.replace(str(temp_path), str(path))
    except OSError as exc:
        raise InvestigationStoreError("Failed to persist investigation result.") from exc
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_latest_investigation_result(path: Path) -> InvestigationRetainedResult:
    if not path.exists() or not path.is_file():
        raise InvestigationStoreNotFound("No retained investigation result exists.")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvestigationStoreError("Failed to read retained investigation result.") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvestigationStoreError("Retained investigation result is malformed JSON.") from exc

    try:
        return InvestigationRetainedResult.model_validate(parsed)
    except ValidationError as exc:
        raise InvestigationStoreError("Retained investigation result has invalid schema.") from exc
