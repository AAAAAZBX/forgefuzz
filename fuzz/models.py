from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FailureKind(str, Enum):
    SUCCESS = "success"
    GENERATION_FAILURE = "generation_failure"
    EMISSION_FAILURE = "emission_failure"
    COMPILE_FAILURE = "compile_failure"
    RUNTIME_FAILURE = "runtime_failure"
    ORACLE_MISMATCH = "oracle_mismatch"
    OUTPUT_MISSING = "output_missing"
    OUTPUT_FORMAT_ERROR = "output_format_error"
    REFERENCE_FAILURE = "reference_failure"
    TARGET_FAILURE = "target_failure"
    TIMEOUT = "timeout"
    DEPENDENCY_MISSING = "dependency_missing"
    ENVIRONMENT_MISSING = "environment_missing"
    INVALID_CASE = "invalid_case"
    INTERNAL_ERROR = "internal_error"

    def __str__(self) -> str:
        return self.value


@dataclass(slots=True)
class ProcessResult:
    command: list[str]
    cwd: str
    exit_code: int | None
    duration_seconds: float
    timed_out: bool
    stdout_path: str
    stderr_path: str

    @property
    def success(self) -> bool:
        return not self.timed_out and self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"success": self.success}


@dataclass(slots=True)
class StageResult:
    stage: str
    success: bool
    failure_kind: str = FailureKind.SUCCESS.value
    message: str = ""
    exit_code: int | None = None
    duration_seconds: float = 0.0
    artifacts: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, stage: str, message: str, *, exit_code: int | None = None, duration_seconds: float = 0.0, artifacts: list[str] | None = None, command: list[str] | None = None, details: dict[str, Any] | None = None) -> "StageResult":
        return cls(stage, True, message=message, exit_code=exit_code, duration_seconds=duration_seconds, artifacts=artifacts or [], command=command or [], details=details or {})

    @classmethod
    def fail(cls, stage: str, kind: FailureKind | str, message: str, *, exit_code: int | None = None, duration_seconds: float = 0.0, artifacts: list[str] | None = None, command: list[str] | None = None, details: dict[str, Any] | None = None) -> "StageResult":
        return cls(stage, False, str(kind), message, exit_code, duration_seconds, artifacts or [], command or [], details or {})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StageResult":
        return cls(**value)


@dataclass(slots=True)
class CaseContext:
    case_id: str
    backend: str
    work_dir: Path
    seed: int
    config: dict[str, Any]
    results: dict[str, StageResult] = field(default_factory=dict)
    attempts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    _active_stage_dir: Path | None = field(default=None, repr=False)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.work_dir.resolve()).as_posix()

    @property
    def stage_work_dir(self) -> Path:
        if self._active_stage_dir is None:
            raise RuntimeError("stage attempt has not been started")
        return self._active_stage_dir

    def config_value(self, name: str, default: Any = None) -> Any:
        return self.config.get(name, default)

    def result(self, stage: str) -> StageResult | None:
        return self.results.get(stage)
