from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import CaseContext, FailureKind, ProcessResult, StageResult
from ..runner import log_tail


class Backend(ABC):
    name: str

    @abstractmethod
    def generate(self, ctx: CaseContext) -> StageResult: ...

    @abstractmethod
    def emit(self, ctx: CaseContext) -> StageResult: ...

    @abstractmethod
    def build(self, ctx: CaseContext) -> StageResult: ...

    @abstractmethod
    def run(self, ctx: CaseContext) -> StageResult: ...

    @abstractmethod
    def oracle(self, ctx: CaseContext) -> StageResult: ...

    @staticmethod
    def process_failure(stage: str, process: ProcessResult, default_kind: FailureKind, message: str) -> StageResult:
        stderr = log_tail(Path(process.stderr_path))
        combined = (stderr + "\n" + log_tail(Path(process.stdout_path))).lower()
        if process.timed_out:
            kind = FailureKind.TIMEOUT
            message = f"{message}: timed out"
        elif any(token in combined for token in (
            "ascend_home_path is not set",
            "cann installation not found",
            "cann setenv script not found",
            "no npu",
            "device not found",
            "driver unavailable",
            "dcmi module initialize failed",
        )):
            kind = FailureKind.ENVIRONMENT_MISSING
        elif process.exit_code == 127 or any(token in combined for token in ("no module named", "command not found", "no such file or directory")):
            kind = FailureKind.DEPENDENCY_MISSING
        else:
            kind = default_kind
        return StageResult.fail(stage, kind, message, exit_code=process.exit_code, duration_seconds=process.duration_seconds, command=process.command, details={"process": process.to_dict(), "log_tail": combined[-3000:]})
