from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import sys
import time
from typing import Any

from .base import Backend
from ..bundle import atomic_json, sha256_file
from ..config import stage_timeout
from ..models import CaseContext, FailureKind, ProcessResult, StageResult
from ..oracle import compare_float32_files
from ..runner import ProcessRunner


_TEMPLATE_FILES = (
    "CMakeLists.txt",
    "baremix_custom.cpp",
    "baremix_custom_copy.cpp",
    "baremix_custom_tiling.cpp",
    "compile.sh",
    "data_utils.h",
    "main.cpp",
    "run.sh",
    "run_once.sh",
)


class AscendCBackend(Backend):
    """Adapter over the real AscendC graph/codegen/template toolchain."""

    name = "ascendc"

    def __init__(self, runner: ProcessRunner | None = None):
        self.runner = runner or ProcessRunner()

    @staticmethod
    def _mode(ctx: CaseContext) -> str:
        mode = str(ctx.config.get("oracle_mode", "auto"))
        return "metamorphic" if mode == "auto" else mode

    @staticmethod
    def _root(ctx: CaseContext) -> Path:
        return Path(ctx.config["ascendc_root"])

    def _run(self, ctx: CaseContext, command: list[str], name: str, stage: str, *, cwd: Path | None = None, environment: dict[str, str] | None = None, deadline: float | None = None) -> ProcessResult:
        timeout = stage_timeout(ctx.config, stage)
        if deadline is not None:
            timeout = max(0.001, deadline - time.monotonic())
        return self.runner.run(command, cwd=cwd or ctx.work_dir, output_dir=ctx.stage_work_dir / name, timeout=timeout, environment={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONPYCACHEPREFIX": str(ctx.work_dir / "cache" / "pycache"), **(environment or {})})

    @staticmethod
    def _deadline(ctx: CaseContext, stage: str) -> float:
        return time.monotonic() + stage_timeout(ctx.config, stage)

    def generate(self, ctx: CaseContext) -> StageResult:
        deadline = self._deadline(ctx, "generate")
        root = self._root(ctx)
        script = root / "generate_graph.py"
        if not script.is_file():
            return StageResult.fail("generate", FailureKind.ENVIRONMENT_MISSING, f"AscendC generator not found: {script}")
        graph = ctx.work_dir / "program" / "graph.json"
        dot = ctx.work_dir / "program" / "graph.dot"
        graph.unlink(missing_ok=True)
        dot.unlink(missing_ok=True)
        command = [sys.executable, str(script), "--nodes", str(ctx.config["ascend_nodes"]), "--seed", str(ctx.seed), "--json", str(graph), "--dot", str(dot), "--ops", str(ctx.config["ascend_ops"])]
        process = self._run(ctx, command, "generator", "generate", deadline=deadline)
        if not process.success:
            return self.process_failure("generate", process, FailureKind.GENERATION_FAILURE, "AscendC generate_graph.py failed")
        if not graph.is_file():
            return StageResult.fail("generate", FailureKind.OUTPUT_MISSING, "generate_graph.py exited successfully without graph.json", details={"process": process.to_dict()})
        try:
            payload = json.loads(graph.read_text(encoding="utf-8"))
            if not isinstance(payload.get("nodes"), list):
                raise ValueError("nodes must be an array")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return StageResult.fail("generate", FailureKind.OUTPUT_FORMAT_ERROR, f"invalid generated graph: {exc}")
        atomic_json(ctx.stage_work_dir / "upstream.json", {"root": str(root), "graph_sha256": sha256_file(graph), "node_count": len(payload["nodes"])})
        return StageResult.ok("generate", "generated a real AscendC graph with generate_graph.py", exit_code=process.exit_code, duration_seconds=process.duration_seconds, command=process.command, artifacts=[ctx.relative(graph), ctx.relative(dot)], details={"process": process.to_dict(), "graph_sha256": sha256_file(graph), "node_count": len(payload["nodes"])})

    def _copy_template(self, root: Path, destination: Path) -> None:
        template = root / "baremix"
        if not template.is_dir():
            raise FileNotFoundError(f"AscendC baremix template not found: {template}")
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        for name in _TEMPLATE_FILES:
            source = template / name
            if not source.is_file():
                raise FileNotFoundError(f"required baremix template file missing: {source}")
            shutil.copy2(source, destination / name)
        for name in ("cmake", "scripts"):
            shutil.copytree(template / name, destination / name)
        # Generated kernels include ../ops/mmad.h unconditionally.  Keep this
        # small upstream header set once beside per-variant project folders.
        ops_destination = destination.parent / "ops"
        if ops_destination.exists():
            shutil.rmtree(ops_destination)
        ops_destination.mkdir()
        for header in (root / "ops").iterdir():
            if header.is_file() and not header.is_symlink():
                shutil.copy2(header, ops_destination / header.name)

    @staticmethod
    def _patch_cpu_entrypoint(main_cpp: Path) -> dict[str, str]:
        old = 'extern "C" void baremix_custom(uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *);'
        new = 'extern "C" void baremix_custom(uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *, uint8_t *);'
        source = main_cpp.read_text(encoding="utf-8")
        if source.count(old) != 1:
            raise ValueError("upstream CPU entrypoint declaration is missing or changed")
        before = sha256_file(main_cpp)
        main_cpp.write_text(source.replace(old, new), encoding="utf-8")
        return {"file": str(main_cpp), "before_sha256": before, "after_sha256": sha256_file(main_cpp), "reason": "match generated eight-argument kernel signature"}

    @staticmethod
    def _patch_cpu_linkage(cmake_file: Path) -> dict[str, str]:
        old = "    ascendalog\n    dl"
        new = "    ascendalog\n    unified_dlog\n    dl"
        source = cmake_file.read_text(encoding="utf-8")
        if source.count(old) != 1:
            raise ValueError("upstream CPU link library list is missing or changed")
        before = sha256_file(cmake_file)
        cmake_file.write_text(source.replace(old, new), encoding="utf-8")
        return {"file": str(cmake_file), "before_sha256": before, "after_sha256": sha256_file(cmake_file), "reason": "satisfy tiling_api CheckLogLevel dependency"}

    def emit(self, ctx: CaseContext) -> StageResult:
        deadline = self._deadline(ctx, "emit")
        root = self._root(ctx)
        graph = ctx.work_dir / "program" / "graph.json"
        if not graph.is_file():
            return StageResult.fail("emit", FailureKind.INVALID_CASE, "generate artifact program/graph.json is missing")
        for stale_name in ("variant", "reference"):
            stale = ctx.work_dir / "source" / stale_name
            if stale.exists():
                shutil.rmtree(stale)
        base = ctx.work_dir / "source" / "base"
        try:
            self._copy_template(root, base)
        except FileNotFoundError as exc:
            return StageResult.fail("emit", FailureKind.ENVIRONMENT_MISSING, str(exc))

        execute = root / "execute_graph.py"
        process = self._run(ctx, [sys.executable, str(execute), "--json", str(graph)], "codegen", "emit", deadline=deadline)
        if not process.success:
            return self.process_failure("emit", process, FailureKind.EMISSION_FAILURE, "AscendC execute_graph.py failed")
        program_cpp = ctx.work_dir / "source" / "program.cpp"
        shutil.copy2(process.stdout_path, program_cpp)
        if not program_cpp.stat().st_size:
            return StageResult.fail("emit", FailureKind.OUTPUT_MISSING, "execute_graph.py emitted empty C++ source")

        split = root / "split_cpp_sections.py"
        split_process = self._run(ctx, [sys.executable, str(split), str(program_cpp), str(ctx.work_dir / "source"), "program", str(base / "baremix_custom.cpp"), str(graph)], "assemble", "emit", deadline=deadline)
        if not split_process.success:
            return self.process_failure("emit", split_process, FailureKind.EMISSION_FAILURE, "split_cpp_sections.py failed")
        generated = base / "baremix_custom_program_out.cpp"
        if not generated.is_file():
            return StageResult.fail("emit", FailureKind.OUTPUT_MISSING, "AscendC assembler did not create baremix_custom_program_out.cpp", details={"codegen": process.to_dict(), "assemble": split_process.to_dict()})
        shutil.copy2(base / "baremix_custom.cpp", base / "baremix_custom.template.cpp")
        os.replace(generated, base / "baremix_custom.cpp")

        mode = self._mode(ctx)
        extra_processes: list[dict[str, Any]] = []
        if mode in {"metamorphic", "compile_diff"}:
            variant = ctx.work_dir / "source" / "variant"
            shutil.copytree(base, variant)
            if mode == "metamorphic":
                if ctx.config.get("ascend_arithmetic_rewrite"):
                    if ctx.config["ascend_arithmetic_rewrite"] != "sub_add_neg":
                        return StageResult.fail("emit", FailureKind.INVALID_CASE, "unsupported ascend_arithmetic_rewrite")
                    path = variant / "baremix_custom.cpp"
                    try:
                        source, mutation = rewrite_arithmetic(path.read_text(encoding="utf-8"))
                    except ValueError as exc:
                        return StageResult.fail("emit", FailureKind.EMISSION_FAILURE, str(exc))
                    path.write_text(source, encoding="utf-8")
                    atomic_json(ctx.work_dir / "configs" / "metamorphic.json", mutation)
                else:
                    injector = root / "metamorphic" / "inject_and_generate.py"
                    manifest = ctx.work_dir / "configs" / "metamorphic.json"
                    injection = self._run(ctx, [sys.executable, str(injector), "--json", str(graph), "--inject-into", str(variant / "baremix_custom.cpp"), "--seed", str(ctx.seed), "--chain-foldback", "--binary-injections", str(ctx.config["ascend_binary_injections"]), "--unary-injections", str(ctx.config["ascend_unary_injections"]), "--write-manifest", str(manifest)], "metamorphic", "emit", deadline=deadline)
                    extra_processes.append(injection.to_dict())
                    if not injection.success:
                        return self.process_failure("emit", injection, FailureKind.EMISSION_FAILURE, "AscendC metamorphic injection failed")
                    try:
                        injection_value = json.loads(manifest.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        return StageResult.fail("emit", FailureKind.OUTPUT_FORMAT_ERROR, f"invalid metamorphic manifest: {exc}")
                    if not injection_value.get("injections"):
                        return StageResult.fail("emit", FailureKind.EMISSION_FAILURE, "metamorphic injector produced no applicable variant")
                    if sha256_file(base / "baremix_custom.cpp") == sha256_file(variant / "baremix_custom.cpp"):
                        return StageResult.fail("emit", FailureKind.EMISSION_FAILURE, "metamorphic source is identical to the base source")
        elif mode == "cpu_npu":
            reference_project = ctx.work_dir / "source" / "reference"
            shutil.copytree(base, reference_project)
            try:
                patch_details = [
                    self._patch_cpu_entrypoint(reference_project / "main.cpp"),
                    self._patch_cpu_linkage(reference_project / "CMakeLists.txt"),
                ]
            except (OSError, ValueError) as exc:
                return StageResult.fail("emit", FailureKind.EMISSION_FAILURE, f"cannot prepare CPU reference project: {exc}")
            for item in patch_details:
                item["file"] = ctx.relative(Path(item["file"]))
            atomic_json(ctx.work_dir / "configs" / "cpu_reference_patch.json", {"patches": patch_details})
        elif mode == "external":
            reference_value = ctx.config.get("reference_output")
            reference = Path(reference_value) if reference_value else None
            if reference is None or not reference.is_file():
                return StageResult.fail("emit", FailureKind.REFERENCE_FAILURE, f"external reference does not exist: {reference_value}")
            bundled_reference = ctx.work_dir / "inputs" / "external_reference.bin"
            shutil.copy2(reference, bundled_reference)
            atomic_json(ctx.work_dir / "inputs" / "external_reference.json", {
                "source": str(reference.resolve()),
                "sha256": sha256_file(bundled_reference),
                "size": bundled_reference.stat().st_size,
            })
        elif mode != "golden":
            return StageResult.fail("emit", FailureKind.INVALID_CASE, f"unsupported AscendC oracle mode: {mode}")

        manifest = {
            "source": "fuzz_code_generation/baremix (selected build template files)",
            "mode": mode,
            "files": sorted(path.relative_to(ctx.work_dir / "source").as_posix() for path in (ctx.work_dir / "source").rglob("*") if path.is_file()),
        }
        atomic_json(ctx.work_dir / "configs" / "ascend_source_manifest.json", manifest)
        artifacts = ["source/program.cpp", "source/base/baremix_custom.cpp", "configs/ascend_source_manifest.json"]
        if (ctx.work_dir / "source" / "variant").is_dir():
            artifacts.append("source/variant/baremix_custom.cpp")
        if (ctx.work_dir / "source" / "reference").is_dir():
            artifacts.append("source/reference/baremix_custom.cpp")
            artifacts.append("configs/cpu_reference_patch.json")
        if mode == "external":
            artifacts.extend(["inputs/external_reference.bin", "inputs/external_reference.json"])
        return StageResult.ok("emit", f"generated a real AscendC project for oracle mode {mode}", exit_code=0, duration_seconds=process.duration_seconds + split_process.duration_seconds, command=process.command, artifacts=artifacts, details={"codegen": process.to_dict(), "assemble": split_process.to_dict(), "extra_processes": extra_processes, "oracle_mode": mode})

    def _cann(self, ctx: CaseContext) -> Path:
        configured = ctx.config.get("ascend_cann_path")
        if configured:
            return Path(configured)
        home = Path.home() / "Ascend" / "ascend-toolkit" / "latest"
        return home if home.is_dir() else Path("/usr/local/Ascend/ascend-toolkit/latest")

    def _projects(self, ctx: CaseContext) -> list[tuple[str, Path, str, dict[str, str]]]:
        mode = self._mode(ctx)
        target_mode = str(ctx.config["ascend_run_mode"])
        values = [("base", ctx.work_dir / "source" / "base", target_mode, {})]
        if mode == "metamorphic":
            values.append(("variant", ctx.work_dir / "source" / "variant", target_mode, {}))
        elif mode == "compile_diff":
            values.append(("variant", ctx.work_dir / "source" / "variant", target_mode, {"EXTRA_CXX_FLAGS": str(ctx.config["ascend_variant_flags"])}))
        elif mode == "cpu_npu":
            values.append(("reference", ctx.work_dir / "source" / "reference", str(ctx.config["ascend_reference_run_mode"]), {}))
        return values

    def build(self, ctx: CaseContext) -> StageResult:
        deadline = self._deadline(ctx, "build")
        cann = self._cann(ctx)
        setenv = cann / "bin" / "setenv.bash"
        if not setenv.is_file():
            return StageResult.fail("build", FailureKind.ENVIRONMENT_MISSING, f"CANN setenv script not found: {setenv}; set ascend_cann_path or ASCEND_HOME_PATH")
        if shutil.which("cmake") is None:
            return StageResult.fail("build", FailureKind.DEPENDENCY_MISSING, "cmake is required to build AscendC cases")
        processes = []
        artifacts = []
        for name, project, run_mode, extra_env in self._projects(ctx):
            script = project / "compile.sh"
            if not script.is_file():
                return StageResult.fail("build", FailureKind.INVALID_CASE, f"emitted project is missing {ctx.relative(script)}")
            command = ["bash", str(script), "-r", run_mode, "-v", str(ctx.config["ascend_soc_version"]), "-i", str(cann)]
            binary = project / "ascendc_kernels_bbit"
            binary.unlink(missing_ok=True)
            process = self._run(ctx, command, f"compile-{name}", "build", cwd=project, environment=extra_env, deadline=deadline)
            processes.append(process.to_dict())
            if not process.success:
                failed = self.process_failure("build", process, FailureKind.COMPILE_FAILURE, f"AscendC {name} compilation failed")
                failed.details["processes"] = processes
                return failed
            if not binary.is_file():
                return StageResult.fail("build", FailureKind.OUTPUT_MISSING, f"compile succeeded without binary: {ctx.relative(binary)}", details={"processes": processes})
            artifacts.append(ctx.relative(binary))
        return StageResult.ok("build", f"compiled {len(processes)} real AscendC project(s)", exit_code=0, duration_seconds=sum(item["duration_seconds"] for item in processes), artifacts=artifacts, details={"processes": processes, "cann_path": str(cann)})

    def run(self, ctx: CaseContext) -> StageResult:
        deadline = self._deadline(ctx, "run")
        cann = self._cann(ctx)
        processes = []
        artifacts = []
        for stale in ("ascend_base.bin", "ascend_variant.bin", "ascend_reference.bin", "ascend_golden.bin", "oracle.json"):
            (ctx.work_dir / "outputs" / stale).unlink(missing_ok=True)
        for name, project, run_mode, extra_env in self._projects(ctx):
            if not (project / "ascendc_kernels_bbit").is_file():
                return StageResult.fail("run", FailureKind.INVALID_CASE, f"build artifact missing for {name}")
            environment = {
                "BENCHMARK_DATA_SEED": str(ctx.seed),
                "BENCHMARK_TENSOR_LEN": str(ctx.config["ascend_tensor_len"]),
                "BENCHMARK_DATA_DTYPE": str(ctx.config["ascend_data_dtype"]),
                "BENCHMARK_DATA_RANGE": str(ctx.config["ascend_data_range"]),
                **extra_env,
            }
            command = ["bash", str(project / "run_once.sh"), "-r", run_mode, "-v", str(ctx.config["ascend_soc_version"]), "-i", str(cann)]
            output = project / "output" / "output.bin"
            output.unlink(missing_ok=True)
            if name == "base":
                (project / "output" / "golden.bin").unlink(missing_ok=True)
            process = self._run(ctx, command, f"run-{name}", "run", cwd=project, environment=environment, deadline=deadline)
            processes.append(process.to_dict())
            if not process.success:
                failed = self.process_failure("run", process, FailureKind.TARGET_FAILURE if name == "base" else FailureKind.REFERENCE_FAILURE, f"AscendC {name} execution failed")
                failed.details["processes"] = processes
                return failed
            if not output.is_file():
                return StageResult.fail("run", FailureKind.OUTPUT_MISSING, f"{name} execution produced no output/output.bin", details={"processes": processes})
            destination = ctx.work_dir / "outputs" / f"ascend_{name}.bin"
            shutil.copy2(output, destination)
            artifacts.append(ctx.relative(destination))
            golden = project / "output" / "golden.bin"
            if name == "base" and golden.is_file():
                shutil.copy2(golden, ctx.work_dir / "outputs" / "ascend_golden.bin")
        return StageResult.ok("run", f"ran {len(processes)} real AscendC project(s)", exit_code=0, duration_seconds=sum(item["duration_seconds"] for item in processes), artifacts=artifacts, details={"processes": processes})

    def oracle(self, ctx: CaseContext) -> StageResult:
        mode = self._mode(ctx)
        if mode in {"metamorphic", "compile_diff"}:
            expected = ctx.work_dir / "outputs" / "ascend_base.bin"
            actual = ctx.work_dir / "outputs" / "ascend_variant.bin"
            relation = f"base_vs_{mode}"
        elif mode == "cpu_npu":
            expected = ctx.work_dir / "outputs" / "ascend_reference.bin"
            actual = ctx.work_dir / "outputs" / "ascend_base.bin"
            relation = "npu_vs_cpu"
        elif mode == "golden":
            expected = ctx.work_dir / "outputs" / "ascend_golden.bin"
            actual = ctx.work_dir / "outputs" / "ascend_base.bin"
            relation = "output_vs_template_golden"
        else:
            expected = ctx.work_dir / "inputs" / "external_reference.bin"
            actual = ctx.work_dir / "outputs" / "ascend_base.bin"
            relation = "output_vs_external"
        missing = [str(path) for path in (expected, actual) if not path.is_file()]
        if missing:
            return StageResult.fail("oracle", FailureKind.OUTPUT_MISSING, f"oracle input missing: {', '.join(missing)}")
        try:
            comparison = compare_float32_files(expected, actual, ctx.config)
        except (OSError, ValueError) as exc:
            return StageResult.fail("oracle", FailureKind.OUTPUT_FORMAT_ERROR, f"cannot parse AscendC output: {exc}")
        result_file = ctx.work_dir / "outputs" / "oracle.json"
        atomic_json(result_file, {"mode": mode, "relation": relation, "expected": str(expected), "actual": str(actual), "comparison": comparison})
        if not comparison["matches"]:
            return StageResult.fail("oracle", FailureKind.ORACLE_MISMATCH, f"AscendC comparison failed: {relation}", artifacts=[ctx.relative(result_file)], details=comparison)
        return StageResult.ok("oracle", f"AscendC comparison passed: {relation}", artifacts=[ctx.relative(result_file)], details=comparison)


def rewrite_arithmetic(source: str) -> tuple[str, dict]:
    """Rewrite the final stored Sub result, so the MR affects observable output."""
    stored = re.findall(r"AscendC::DataCopy\(OutputGlobal,\s*(\w+),\s*tensor_len\);", source)
    if len(stored) != 1:
        raise ValueError("arithmetic rewrite requires one identifiable final output")
    pattern = re.compile(r"^(?P<indent>[ \t]*)Sub\((?P<dst>\w+),\s*(?P<x>\w+),\s*(?P<y>\w+),\s*(?P<count>active_len|tensor_len)\); // node (?P<node>\d+)$", re.MULTILINE)
    candidates = [m for m in pattern.finditer(source) if m['dst'] == stored[0]]
    if len(candidates) != 1:
        raise ValueError("arithmetic rewrite requires a single Sub producing the stored output")
    match = candidates[0]
    dst, x, y, count = (match[key] for key in ('dst', 'x', 'y', 'count'))
    if dst in (x, y):
        raise ValueError("arithmetic rewrite requires a distinct destination tensor")
    indent = match['indent']
    after = (f"{indent}AscendC::Muls({dst}, {y}, -1.0f, {count}); // MR: negate y\n"
             f"{indent}AscendC::Add({dst}, {x}, {dst}, {count}); // node {match['node']}: x + (-y)")
    return source[:match.start()] + after + source[match.end():], {
        "rule": "sub_add_neg", "relation": "x - y == x + (-y)",
        "before": match[0].strip(), "after": after.strip(),
        "node": int(match['node']), "stored_output": dst,
    }
