from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fuzz.backends.base import Backend
from fuzz.cli import main
from fuzz.models import StageResult


class DeterministicBackend(Backend):
    name = "triton"

    def generate(self, ctx):
        path = ctx.work_dir / "program" / "kernel_spec.json"
        path.write_text(f'{{"seed": {ctx.seed}}}\n', encoding="utf-8")
        return StageResult.ok("generate", "ok", artifacts=[ctx.relative(path)])

    def emit(self, ctx): return StageResult.ok("emit", "ok")
    def build(self, ctx): return StageResult.ok("build", "ok")
    def run(self, ctx): return StageResult.ok("run", "ok")
    def oracle(self, ctx): return StageResult.ok("oracle", "ok")


class CliTests(unittest.TestCase):
    def test_canonical_module_entrypoint_and_version(self):
        process = subprocess.run(
            [sys.executable, "-m", "forgefuzz", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(process.stdout.strip(), "forgefuzz 0.2.0")

    def test_run_stage_resume_and_replay(self):
        with tempfile.TemporaryDirectory() as raw, patch("fuzz.cli.BACKENDS", {"triton": DeterministicBackend()}):
            root = Path(raw)
            self.assertEqual(main(["run", "--backend", "triton", "--seed", "42", "--case-id", "original", "--output-dir", str(root)]), 0)
            case = root / "original"
            self.assertEqual(main(["stage", "oracle", str(case)]), 0)
            self.assertEqual(main(["resume", str(case), "--from", "emit"]), 0)
            self.assertEqual(main(["replay", str(case)]), 0)
            self.assertEqual(len(list(root.glob("*-replay"))), 1)

    def test_stage_rejects_missing_prerequisite(self):
        with tempfile.TemporaryDirectory() as raw, patch("fuzz.cli.BACKENDS", {"triton": DeterministicBackend()}):
            root = Path(raw)
            from fuzz.bundle import CaseBundle
            CaseBundle.create(root, "empty", "triton", 1, {"timeout": 1.0, "stage_timeouts": {}})
            self.assertEqual(main(["stage", "build", str(root / "empty")]), 2)

    def test_invalid_backend_device_combination(self):
        with tempfile.TemporaryDirectory() as raw, patch("fuzz.cli.BACKENDS", {"triton": DeterministicBackend()}):
            self.assertEqual(main(["run", "--backend", "triton", "--seed", "1", "--device", "cpu", "--output-dir", raw]), 2)

    def test_sequential_campaign_persists_summary(self):
        with tempfile.TemporaryDirectory() as raw, patch("fuzz.cli.BACKENDS", {"triton": DeterministicBackend()}):
            result = main([
                "campaign", "--backend", "triton", "--start-seed", "10", "--count", "3",
                "--campaign-id", "smoke", "--device", "interpreter", "--output-dir", raw,
            ])
            self.assertEqual(result, 0)
            summary = json.loads((Path(raw) / "smoke" / "campaign.json").read_text())
            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["executed_count"], 3)
            self.assertEqual([item["seed"] for item in summary["cases"]], [10, 11, 12])


if __name__ == "__main__":
    unittest.main()
