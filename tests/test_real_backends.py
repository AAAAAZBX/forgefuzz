from __future__ import annotations

from pathlib import Path
import time
import tempfile
import unittest

from fuzz.backends.ascendc import AscendCBackend
from fuzz.backends.triton import TritonBackend
from fuzz.bundle import CaseBundle, sha256_file
from fuzz.config import load_config
from fuzz.pipeline import execute_stage
from fuzz.models import ProcessResult


class RecordingRunner:
    def __init__(self):
        self.timeouts = []

    def run(self, command, *, cwd, output_dir, timeout, environment=None):
        self.timeouts.append(timeout)
        time.sleep(0.01)
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / "stdout.log"
        stderr = output_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return ProcessResult(list(command), str(cwd), 1, 0.01, False, str(stdout), str(stderr))


WORKSPACE = Path(__file__).resolve().parents[2]
TRITON_ROOT = WORKSPACE / "triton-fuzzer-main"
ASCEND_ROOT = WORKSPACE / "fuzz_code_generation"


@unittest.skipUnless((TRITON_ROOT / "triton_ascend_fuzz").is_dir(), "real Triton project is unavailable")
class TritonIntegrationTests(unittest.TestCase):
    def test_real_generate_emit_and_determinism(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={"output_dir": str(root), "triton_root": str(TRITON_ROOT), "device": "interpreter"})
            hashes = []
            for case_id in ("triton-a", "triton-b"):
                ctx = CaseBundle.create(root, case_id, "triton", 99, config)
                self.assertTrue(execute_stage(TritonBackend(), ctx, "generate").success)
                self.assertTrue(execute_stage(TritonBackend(), ctx, "emit").success)
                hashes.append(sha256_file(ctx.work_dir / "program" / "kernel_spec.json"))
                self.assertTrue((ctx.work_dir / "source" / "kernel.py").is_file())
                self.assertTrue((ctx.work_dir / "inputs" / "manifest.json").is_file())
            self.assertEqual(hashes[0], hashes[1])

    def test_failed_rerun_removes_stale_outputs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={"output_dir": str(root), "triton_root": str(TRITON_ROOT), "device": "interpreter"})
            ctx = CaseBundle.create(root, "triton-stale", "triton", 1, config)
            kernel = ctx.work_dir / "source" / "kernel.py"
            kernel.write_text("pass\n", encoding="utf-8")
            stale = (
                ctx.work_dir / "source" / "reference_output.npy",
                ctx.work_dir / "source" / "interpreter_output.npy",
                ctx.work_dir / "outputs" / "triton_reference.npy",
                ctx.work_dir / "outputs" / "triton_interpreter.npy",
            )
            for path in stale:
                path.write_bytes(b"stale")
            result = execute_stage(TritonBackend(RecordingRunner()), ctx, "run")
            self.assertFalse(result.success)
            self.assertTrue(all(not path.exists() for path in stale))


@unittest.skipUnless((ASCEND_ROOT / "generate_graph.py").is_file(), "real AscendC project is unavailable")
class AscendIntegrationTests(unittest.TestCase):
    def test_cpu_entrypoint_patch_matches_generated_signature(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "main.cpp"
            path.write_text('extern "C" void baremix_custom(uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *);\n', encoding="utf-8")
            details = AscendCBackend._patch_cpu_entrypoint(path)
            self.assertNotEqual(details["before_sha256"], details["after_sha256"])
            self.assertEqual(path.read_text().count("uint8_t *"), 8)

    def test_cpu_link_patch_adds_required_logging_library(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "CMakeLists.txt"
            path.write_text("    ascendalog\n    dl\n", encoding="utf-8")
            AscendCBackend._patch_cpu_linkage(path)
            self.assertIn("    unified_dlog\n", path.read_text())

    def test_multi_process_stage_uses_one_timeout_budget(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={"output_dir": str(root), "timeout": 1})
            ctx = CaseBundle.create(root, "timeout-budget", "ascendc", 1, config)
            CaseBundle.begin_stage(ctx, "emit")
            runner = RecordingRunner()
            backend = AscendCBackend(runner)
            deadline = backend._deadline(ctx, "emit")
            backend._run(ctx, ["first"], "first", "emit", deadline=deadline)
            backend._run(ctx, ["second"], "second", "emit", deadline=deadline)
            self.assertLess(runner.timeouts[1], runner.timeouts[0])
    def test_real_generate_emit_and_determinism(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={
                "output_dir": str(root),
                "ascendc_root": str(ASCEND_ROOT),
                "ascend_nodes": 5,
                "ascend_ops": "Add,Mul,Sub",
                "oracle_mode": "metamorphic",
                "ascend_binary_injections": 1,
                "ascend_unary_injections": 0,
            })
            hashes = []
            for case_id in ("ascend-a", "ascend-b"):
                ctx = CaseBundle.create(root, case_id, "ascendc", 99, config)
                self.assertTrue(execute_stage(AscendCBackend(), ctx, "generate").success)
                self.assertTrue(execute_stage(AscendCBackend(), ctx, "emit").success)
                hashes.append(sha256_file(ctx.work_dir / "program" / "graph.json"))
                self.assertTrue((ctx.work_dir / "source" / "base" / "baremix_custom.cpp").is_file())
                self.assertTrue((ctx.work_dir / "source" / "variant" / "baremix_custom.cpp").is_file())
                self.assertFalse((ctx.work_dir / "source" / "ops" / "ops").exists())
            self.assertEqual(hashes[0], hashes[1])

    def test_missing_cann_is_classified(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={"output_dir": str(root), "ascendc_root": str(ASCEND_ROOT), "ascend_cann_path": str(root / "missing-cann")})
            ctx = CaseBundle.create(root, "missing-cann", "ascendc", 1, config)
            result = execute_stage(AscendCBackend(), ctx, "build")
            self.assertFalse(result.success)
            self.assertEqual(result.failure_kind, "environment_missing")


if __name__ == "__main__":
    unittest.main()
