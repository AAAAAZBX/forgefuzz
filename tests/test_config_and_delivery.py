from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fuzz.bundle import CaseBundle, case_lock
from fuzz.cli import _resolved, build_parser
from fuzz.config import load_config
from fuzz.doctor import run_doctor


class ConfigValidationTests(unittest.TestCase):
    def test_ascend_device_from_config_controls_run_mode(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump({"device": "cpu"}, handle)
            handle.flush()
            args = build_parser().parse_args([
                "run", "--backend", "ascendc", "--seed", "1", "--config", handle.name,
            ])
            config = _resolved(args)
        self.assertEqual(config["device"], "cpu")
        self.assertEqual(config["ascend_run_mode"], "cpu")

    def test_invalid_numeric_and_dtype_values_are_rejected(self):
        invalid = (
            {"atol": -1},
            {"rtol": -1},
            {"ascend_nodes": 0},
            {"ascend_tensor_len": 0},
            {"ascend_data_dtype": "float16"},
            {"stage_timeouts": {"run": 0}},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                load_config(overrides=overrides)

    def test_ascend_rejects_conflicting_run_modes(self):
        from fuzz.config import validate_backend_config
        config = load_config(overrides={"device": "cpu", "ascend_run_mode": "npu"})
        with self.assertRaisesRegex(ValueError, "disagree"):
            validate_backend_config(config, "ascendc")


class DoctorScopeTests(unittest.TestCase):
    def test_triton_interpreter_does_not_require_ascend_or_npu(self):
        config = load_config(overrides={"device": "interpreter"})
        with patch("fuzz.doctor.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "triton-ok\n"
            run.return_value.stderr = ""
            checks, healthy = run_doctor(config, backend="triton")
        names = {item["name"] for item in checks}
        self.assertNotIn("AscendC project", names)
        self.assertNotIn("CANN", names)
        self.assertNotIn("NPU device", names)
        self.assertTrue(healthy)


class BundleDeliveryTests(unittest.TestCase):
    def test_case_records_upstream_provenance(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = load_config(overrides={"output_dir": raw})
            ctx = CaseBundle.create(root, "provenance", "triton", 1, config)
            provenance = json.loads((ctx.work_dir / "configs" / "provenance.json").read_text())
            self.assertEqual(provenance["schema_version"], 1)
            self.assertIn("python", provenance)
            self.assertIn("triton_project", provenance)
            self.assertIn("ascendc_project", provenance)

    def test_case_lock_rejects_a_second_writer(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = CaseBundle.create(root, "locked", "triton", 1, {"timeout": 1, "stage_timeouts": {}})
            with case_lock(ctx.work_dir):
                with self.assertRaises(BlockingIOError):
                    with case_lock(ctx.work_dir):
                        self.fail("the second lock must not be acquired")

    def test_lock_file_is_not_reported_as_an_artifact(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = CaseBundle.create(root, "manifest", "triton", 1, {"timeout": 1, "stage_timeouts": {}})
            with case_lock(ctx.work_dir):
                pass
            self.assertNotIn(".lock", CaseBundle.manifest(ctx))

    def test_manifest_excludes_transient_build_and_cache_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = CaseBundle.create(root, "manifest-transient", "triton", 1, {"timeout": 1, "stage_timeouts": {}})
            cached = ctx.work_dir / "cache" / "large.bin"
            built = ctx.work_dir / "source" / "base" / "build" / "object.o"
            source = ctx.work_dir / "source" / "base" / "kernel.cpp"
            for path in (cached, built, source):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"data")
            manifest = CaseBundle.manifest(ctx)
            self.assertNotIn("cache/large.bin", manifest)
            self.assertNotIn("source/base/build/object.o", manifest)
            self.assertIn("source/base/kernel.cpp", manifest)


class StrictIntegrationAvailabilityTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("FORGEFUZZ_REQUIRE_UPSTREAM") == "1", "strict upstream check is opt-in")
    def test_required_upstream_projects_exist(self):
        config = load_config()
        self.assertTrue((Path(config["triton_root"]) / "triton_ascend_fuzz").is_dir())
        self.assertTrue((Path(config["ascendc_root"]) / "generate_graph.py").is_file())


if __name__ == "__main__":
    unittest.main()
