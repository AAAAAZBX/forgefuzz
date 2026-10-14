from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from fuzz.backends.base import Backend
from fuzz.bundle import CaseBundle
from fuzz.models import FailureKind, StageResult
from fuzz.pipeline import STAGES, run_pipeline
from fuzz.runner import ProcessRunner


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, fail_stage: str | None = None, raise_stage: str | None = None):
        self.fail_stage = fail_stage
        self.raise_stage = raise_stage

    def _stage(self, ctx, stage):
        if stage == self.raise_stage:
            raise RuntimeError("boom")
        path = ctx.work_dir / "outputs" / f"{stage}.txt"
        path.write_text(stage, encoding="utf-8")
        if stage == self.fail_stage:
            return StageResult.fail(stage, FailureKind.RUNTIME_FAILURE, "requested failure")
        return StageResult.ok(stage, "ok", artifacts=[ctx.relative(path)])

    def generate(self, ctx): return self._stage(ctx, "generate")
    def emit(self, ctx): return self._stage(ctx, "emit")
    def build(self, ctx): return self._stage(ctx, "build")
    def run(self, ctx): return self._stage(ctx, "run")
    def oracle(self, ctx): return self._stage(ctx, "oracle")


class CoreTests(unittest.TestCase):
    def _case(self, root: Path):
        return CaseBundle.create(root, "case-test", "fake", 7, {"timeout": 1.0, "stage_timeouts": {}})

    def test_success_and_persistence(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self._case(Path(raw))
            run_pipeline(FakeBackend(), ctx)
            self.assertTrue(all(ctx.results[name].success for name in STAGES))
            loaded = CaseBundle.load(ctx.work_dir)
            self.assertEqual(set(loaded.results), set(STAGES + ["report"]))
            report = json.loads((ctx.work_dir / "report.json").read_text())
            self.assertEqual(report["status"], "passed")
            self.assertIn("outputs/generate.txt", report["manifest"])
            self.assertEqual(report["replay_argv"][:2], ["forgefuzz", "replay"])

    def test_failure_stops_pipeline(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self._case(Path(raw))
            run_pipeline(FakeBackend(fail_stage="build"), ctx)
            self.assertEqual(set(ctx.results), {"generate", "emit", "build", "report"})
            self.assertEqual(ctx.results["build"].failure_kind, "runtime_failure")
            report = json.loads((ctx.work_dir / "report.json").read_text())
            self.assertEqual(report["failure_stage"], "build")

    def test_exception_becomes_result(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self._case(Path(raw))
            run_pipeline(FakeBackend(raise_stage="emit"), ctx)
            self.assertEqual(ctx.results["emit"].failure_kind, "internal_error")
            self.assertIn("RuntimeError", ctx.results["emit"].message)

    def test_process_timeout_is_persisted(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = ProcessRunner().run([sys.executable, "-c", "import time; time.sleep(5)"], cwd=root, output_dir=root / "process", timeout=0.05)
            self.assertTrue(result.timed_out)
            self.assertFalse(result.success)
            self.assertTrue((root / "process" / "command.json").is_file())
            self.assertTrue((root / "process" / "stdout.log").is_file())

    def test_missing_executable_is_a_process_result(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            process = ProcessRunner().run([str(root / "does-not-exist")], cwd=root, output_dir=root / "process", timeout=1)
            self.assertEqual(process.exit_code, 127)
            failure = FakeBackend.process_failure("run", process, FailureKind.RUNTIME_FAILURE, "failed")
            self.assertEqual(failure.failure_kind, "dependency_missing")

    def test_device_not_found_is_environment_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stderr = root / "stderr.log"
            stdout = root / "stdout.log"
            stderr.write_text("NPU device not found: driver unavailable", encoding="utf-8")
            stdout.write_text("", encoding="utf-8")
            from fuzz.models import ProcessResult
            process = ProcessResult(["tool"], str(root), 1, 0.1, False, str(stdout), str(stderr))
            failure = FakeBackend.process_failure("run", process, FailureKind.RUNTIME_FAILURE, "failed")
            self.assertEqual(failure.failure_kind, "environment_missing")

    def test_cann_path_in_compile_log_does_not_hide_compile_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stderr = root / "stderr.log"
            stdout = root / "stdout.log"
            stderr.write_text("/usr/local/Ascend/cann/include/header.h: error: too many arguments", encoding="utf-8")
            stdout.write_text("", encoding="utf-8")
            from fuzz.models import ProcessResult
            process = ProcessResult(["compiler"], str(root), 1, 0.1, False, str(stdout), str(stderr))
            failure = FakeBackend.process_failure("build", process, FailureKind.COMPILE_FAILURE, "failed")
            self.assertEqual(failure.failure_kind, "compile_failure")

    def test_backend_contract_is_abstract(self):
        with self.assertRaises(TypeError):
            Backend()


if __name__ == "__main__":
    unittest.main()
