from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_HARDWARE = os.environ.get("FORGEFUZZ_RUN_HARDWARE") == "1"


@unittest.skipUnless(
    RUN_HARDWARE,
    "set FORGEFUZZ_RUN_HARDWARE=1 to run real NPU end-to-end tests",
)
class HardwareEndToEndTests(unittest.TestCase):
    maxDiff = None

    def _run_case(self, *arguments: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="forgefuzz-hardware-") as raw:
            output_dir = Path(raw)
            command = [
                sys.executable,
                str(PROJECT_ROOT / "main.py"),
                "run",
                *arguments,
                "--output-dir",
                str(output_dir),
                "--timeout",
                "600",
            ]
            process = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            self.assertEqual(
                process.returncode,
                0,
                f"command failed: {command!r}\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}",
            )
            reports = list(output_dir.glob("*/report.json"))
            self.assertEqual(len(reports), 1, f"expected one report, found {reports}")
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(
                all(report["results"][stage]["success"] for stage in ("generate", "emit", "build", "run", "oracle")),
                report,
            )
            return report

    def test_triton_npu_torch_oracle(self):
        report = self._run_case(
            "--backend",
            "triton",
            "--seed",
            "42",
            "--device",
            "npu",
            "--oracle-mode",
            "torch",
        )
        self.assertEqual(report["results"]["run"]["details"]["target_kind"], "npu")

    def test_triton_npu_arithmetic_metamorphic(self):
        report = self._run_case(
            "--backend", "triton", "--seed", "42", "--device", "npu",
            "--template", "elementwise_add", "--oracle-mode", "metamorphic",
        )
        self.assertIn("base_vs_metamorphic", report["results"]["oracle"]["message"])

    def test_ascendc_npu_arithmetic_metamorphic(self):
        report = self._run_case(
            "--backend", "ascendc", "--seed", "10", "--device", "npu",
            "--nodes", "5", "--ops", "Add,Sub,Mul", "--oracle-mode", "metamorphic",
            "--set", "ascend_arithmetic_rewrite=sub_add_neg",
        )
        self.assertIn("base_vs_metamorphic", report["results"]["oracle"]["message"])

    def test_ascendc_npu_metamorphic_oracle(self):
        report = self._run_case(
            "--backend",
            "ascendc",
            "--seed",
            "42",
            "--device",
            "npu",
            "--oracle-mode",
            "metamorphic",
        )
        self.assertIn("base_vs_metamorphic", report["results"]["oracle"]["message"])

    def test_ascendc_npu_compile_diff_oracle(self):
        report = self._run_case(
            "--backend",
            "ascendc",
            "--seed",
            "42",
            "--device",
            "npu",
            "--oracle-mode",
            "compile_diff",
        )
        self.assertIn("base_vs_compile_diff", report["results"]["oracle"]["message"])

    def test_ascendc_npu_cpu_oracle(self):
        report = self._run_case(
            "--backend",
            "ascendc",
            "--seed",
            "42",
            "--device",
            "npu",
            "--oracle-mode",
            "cpu_npu",
        )
        self.assertIn("npu_vs_cpu", report["results"]["oracle"]["message"])


if __name__ == "__main__":
    unittest.main()
