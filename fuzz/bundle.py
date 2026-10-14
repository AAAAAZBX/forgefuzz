from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import fcntl

from .models import CaseContext, StageResult
from .provenance import collect_provenance


SCHEMA_VERSION = 1
CASE_DIRS = ("program", "inputs", "source", "configs", "stages", "outputs", "cache")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def case_lock(path: Path):
    """Prevent concurrent writers from corrupting one case bundle."""
    lock_path = path.resolve() / ".lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class CaseBundle:
    @staticmethod
    def create(root: Path, case_id: str, backend: str, seed: int, config: dict[str, Any]) -> CaseContext:
        if not case_id or not all(character.isalnum() or character in "-_" for character in case_id):
            raise ValueError("case ID may contain only letters, digits, '-' and '_'")
        path = root / case_id
        path.mkdir(parents=True, exist_ok=False)
        for name in CASE_DIRS:
            (path / name).mkdir()
        now = utc_now()
        ctx = CaseContext(case_id, backend, path, int(seed), config, created_at=now, updated_at=now)
        CaseBundle.save(ctx)
        atomic_json(path / "configs" / "resolved.json", config)
        atomic_json(path / "configs" / "provenance.json", collect_provenance(config))
        return ctx

    @staticmethod
    def load(path: Path) -> CaseContext:
        path = path.resolve()
        case_file = path / "case.json"
        if not case_file.is_file():
            raise FileNotFoundError(f"missing case.json: {path}")
        value = json.loads(case_file.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported case schema: {value.get('schema_version')!r}")
        results = {key: StageResult.from_dict(item) for key, item in value.get("results", {}).items()}
        return CaseContext(value["case_id"], value["backend"], path, int(value["seed"]), value["config"], results, value.get("attempts", {}), value.get("created_at", ""), value.get("updated_at", ""))

    @staticmethod
    def begin_stage(ctx: CaseContext, stage: str) -> Path:
        number = len(ctx.attempts.get(stage, [])) + 1
        attempt = ctx.work_dir / "stages" / stage / f"attempt-{number:03d}"
        attempt.mkdir(parents=True, exist_ok=False)
        ctx._active_stage_dir = attempt
        return attempt

    @staticmethod
    def record(ctx: CaseContext, result: StageResult) -> None:
        if ctx._active_stage_dir is None:
            raise RuntimeError("cannot record a stage before begin_stage")
        relative_attempt = ctx.relative(ctx._active_stage_dir)
        atomic_json(ctx._active_stage_dir / "result.json", result.to_dict())
        atomic_json(ctx.work_dir / "stages" / result.stage / "result.json", result.to_dict())
        ctx.results[result.stage] = result
        ctx.attempts.setdefault(result.stage, []).append({"path": relative_attempt, "success": result.success, "failure_kind": result.failure_kind})
        ctx.updated_at = utc_now()
        ctx._active_stage_dir = None
        CaseBundle.save(ctx)

    @staticmethod
    def save(ctx: CaseContext) -> None:
        atomic_json(ctx.work_dir / "case.json", {
            "schema_version": SCHEMA_VERSION,
            "case_id": ctx.case_id,
            "backend": ctx.backend,
            "seed": ctx.seed,
            "config": ctx.config,
            "created_at": ctx.created_at,
            "updated_at": ctx.updated_at,
            "results": {key: item.to_dict() for key, item in ctx.results.items()},
            "attempts": ctx.attempts,
        })

    @staticmethod
    def truncate_results(ctx: CaseContext, stages: list[str]) -> None:
        for stage in stages:
            ctx.results.pop(stage, None)
        ctx.updated_at = utc_now()
        CaseBundle.save(ctx)

    @staticmethod
    def manifest(ctx: CaseContext) -> dict[str, Any]:
        files = {}
        for path in sorted(ctx.work_dir.rglob("*")):
            relative = path.relative_to(ctx.work_dir).as_posix()
            parts = path.relative_to(ctx.work_dir).parts
            transient = bool(parts and parts[0] == "cache") or (
                len(parts) >= 3 and parts[0] == "source" and parts[2] in {"build", "input", "out", "output"}
            )
            if path.is_file() and not transient and relative not in {".lock", "case.json", "report.json"}:
                files[relative] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
        return files
