from __future__ import annotations

import time

from .bundle import CaseBundle
from .models import CaseContext, FailureKind, StageResult
from .report import build_report


STAGES = ["generate", "emit", "build", "run", "oracle"]
ALL_STAGES = STAGES + ["report"]


def execute_stage(backend, ctx: CaseContext, stage: str) -> StageResult:
    if stage not in ALL_STAGES:
        raise ValueError(f"unknown stage: {stage}")
    CaseBundle.begin_stage(ctx, stage)
    start = time.monotonic()
    try:
        result = build_report(ctx) if stage == "report" else getattr(backend, stage)(ctx)
        if result.stage != stage:
            raise ValueError(f"backend returned stage {result.stage!r} while running {stage!r}")
    except Exception as exc:
        result = StageResult.fail(stage, FailureKind.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}", details={"exception_type": type(exc).__name__})
    if result.duration_seconds <= 0:
        result.duration_seconds = time.monotonic() - start
    CaseBundle.record(ctx, result)
    return result


def run_pipeline(backend, ctx: CaseContext, *, start_stage: str = "generate") -> CaseContext:
    start = STAGES.index(start_stage)
    for stage in STAGES[start:]:
        result = execute_stage(backend, ctx, stage)
        if not result.success:
            break
    execute_stage(backend, ctx, "report")
    return ctx
