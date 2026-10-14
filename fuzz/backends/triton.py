from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Iterator

from .base import Backend
from ..bundle import atomic_json
from ..config import stage_timeout
from ..models import CaseContext, FailureKind, StageResult
from ..oracle import compare_npy_files
from ..runner import ProcessRunner


@contextmanager
def _upstream_imports(root: Path) -> Iterator[None]:
    if not (root / "triton_ascend_fuzz").is_dir():
        raise FileNotFoundError(f"Triton project package not found: {root / 'triton_ascend_fuzz'}")
    old_flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    try:
        yield
    finally:
        sys.path.remove(str(root))
        sys.dont_write_bytecode = old_flag


class TritonBackend(Backend):
    """Adapter over the real triton_ascend_fuzz generator, emitter and harness."""

    name = "triton"

    def __init__(self, runner: ProcessRunner | None = None):
        self.runner = runner or ProcessRunner()

    def generate(self, ctx: CaseContext) -> StageResult:
        started = time.monotonic()
        root = Path(ctx.config["triton_root"])
        try:
            with _upstream_imports(root):
                from triton_ascend_fuzz.generate import ConstructiveGenerator

                generator = ConstructiveGenerator(ctx.seed, semantic_api_count=int(ctx.config["triton_semantic_api_count"]))
                case = generator.generate(
                    str(ctx.config["triton_profile"]),
                    case_index=int(ctx.config["triton_case_index"]),
                    materialize=True,
                    template=ctx.config.get("triton_template"),
                )
                if case.kernel_spec is None:
                    return StageResult.fail("generate", FailureKind.GENERATION_FAILURE, f"upstream generator did not materialize KernelSpec: {case.materialization_error}")
                inputs = generator.generate_inputs(case)
                spec_path = ctx.work_dir / "program" / "kernel_spec.json"
                canonical_path = ctx.work_dir / "program" / "canonical_case.json"
                trace_path = ctx.work_dir / "program" / "generation_trace.json"
                atomic_json(spec_path, case.kernel_spec.to_dict())
                atomic_json(canonical_path, case.to_dict())
                atomic_json(trace_path, case.trace.to_dict())
                descriptors = []
                import numpy as np

                for name in sorted(inputs.arrays):
                    target = ctx.work_dir / "inputs" / f"{name}.npy"
                    with target.open("wb") as handle:
                        np.save(handle, inputs.arrays[name], allow_pickle=False)
                    descriptors.append({
                        "name": name,
                        "path": ctx.relative(target),
                        "request": inputs.requests[name].to_dict(),
                        "summary": inputs.summaries[name].to_dict(),
                    })
                manifest = {"format_version": "CaseBundle.inputs.v0", "input_seed": inputs.input_seed, "digest": inputs.digest, "inputs": descriptors}
                atomic_json(ctx.work_dir / "inputs" / "manifest.json", manifest)
                atomic_json(ctx.stage_work_dir / "upstream.json", {"root": str(root), "case_id": case.case_id, "profile": case.profile.value, "template": case.template, "input_digest": inputs.digest})
        except ModuleNotFoundError as exc:
            return StageResult.fail("generate", FailureKind.DEPENDENCY_MISSING, f"Triton generator dependency missing: {exc}")
        except FileNotFoundError as exc:
            return StageResult.fail("generate", FailureKind.ENVIRONMENT_MISSING, str(exc))
        except Exception as exc:
            return StageResult.fail("generate", FailureKind.GENERATION_FAILURE, f"{type(exc).__name__}: {exc}")
        return StageResult.ok("generate", "generated a real upstream KernelSpec and deterministic NumPy inputs", duration_seconds=time.monotonic() - started, artifacts=["program/kernel_spec.json", "program/canonical_case.json", "program/generation_trace.json", "inputs/manifest.json"], details={"upstream_case_id": case.case_id, "input_digest": inputs.digest})

    def emit(self, ctx: CaseContext) -> StageResult:
        root = Path(ctx.config["triton_root"])
        spec_path = ctx.work_dir / "program" / "kernel_spec.json"
        if not spec_path.is_file():
            return StageResult.fail("emit", FailureKind.INVALID_CASE, "generate artifact program/kernel_spec.json is missing")
        try:
            with _upstream_imports(root):
                from triton_ascend_fuzz.emit import TritonPythonEmitter
                from triton_ascend_fuzz.spec import KernelSpec

                spec = KernelSpec.from_dict(json.loads(spec_path.read_text(encoding="utf-8")))
                emission = TritonPythonEmitter().emit(spec, artifact_subdir="source")
                kernel_path, launch_path = emission.write_to(ctx.work_dir)
                if ctx.config.get("oracle_mode") == "metamorphic":
                    variant = TritonPythonEmitter().emit(spec, artifact_subdir="source/variant")
                    variant_path, _ = variant.write_to(ctx.work_dir)
                    source, mutation = commute_arithmetic(variant.source)
                    variant_path.write_text(source, encoding="utf-8")
                    atomic_json(ctx.work_dir / "configs" / "metamorphic.json", mutation)
        except ModuleNotFoundError as exc:
            return StageResult.fail("emit", FailureKind.DEPENDENCY_MISSING, f"Triton emitter dependency missing: {exc}")
        except Exception as exc:
            return StageResult.fail("emit", FailureKind.EMISSION_FAILURE, f"{type(exc).__name__}: {exc}")
        artifacts = [ctx.relative(kernel_path), ctx.relative(launch_path)]
        if ctx.config.get("oracle_mode") == "metamorphic":
            artifacts.extend(["source/variant/kernel.py", "source/variant/launch.json", "configs/metamorphic.json"])
        return StageResult.ok("emit", "emitted the real self-contained Triton Python harness", artifacts=artifacts)

    def _environment(self, ctx: CaseContext) -> dict[str, str]:
        cache = ctx.work_dir / "cache" / "triton"
        dump = ctx.work_dir / "outputs" / "triton-ir"
        cache.mkdir(parents=True, exist_ok=True)
        dump.mkdir(parents=True, exist_ok=True)
        root = Path(ctx.config["triton_root"])
        python_path = root / "third_party" / "triton-ascend" / "python"
        inherited_pythonpath = os.environ.get("PYTHONPATH", "")
        return {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(ctx.work_dir / "cache" / "pycache"),
            "TRITON_CACHE_DIR": str(cache),
            "TRITON_DUMP_DIR": str(dump),
            "TRITON_REPRODUCER_PATH": str(ctx.work_dir / "outputs" / "reproducer.mlir"),
            "TRITON_KERNEL_DUMP": "1",
            "PYTHONPATH": str(python_path) + (os.pathsep + inherited_pythonpath if inherited_pythonpath else ""),
        }

    def _python(self, ctx: CaseContext) -> str:
        configured = ctx.config.get("triton_python")
        if configured:
            return str(configured)
        candidate = Path(ctx.config["triton_root"]) / ".envs" / "triton-ascend" / "bin" / "python"
        return str(candidate) if candidate.is_file() else sys.executable

    def _paired_stage(self, ctx: CaseContext, stage: str) -> StageResult:
        deadline = time.monotonic() + stage_timeout(ctx.config, stage)
        method = self._build_one if stage == "build" else self._run_one
        base = method(ctx, deadline=deadline)
        if not base.success or ctx.config.get("oracle_mode") != "metamorphic":
            return base
        variant = method(ctx, artifact="source/variant", prefix="triton_variant", deadline=deadline)
        if not variant.success:
            return variant
        return StageResult.ok(stage, "base and arithmetic variant succeeded",
                              artifacts=base.artifacts + variant.artifacts,
                              details={"base": base.to_dict(), "variant": variant.to_dict()})

    def build(self, ctx: CaseContext) -> StageResult:
        return self._paired_stage(ctx, "build")

    def _build_one(self, ctx: CaseContext, artifact="source", prefix="triton", deadline=None) -> StageResult:
        kernel = ctx.work_dir / artifact / "kernel.py"
        if not kernel.is_file():
            return StageResult.fail("build", FailureKind.INVALID_CASE, f"emit artifact {artifact}/kernel.py is missing")
        device = str(ctx.config.get("device", "npu"))
        if device not in {"npu", "interpreter"}:
            return StageResult.fail("build", FailureKind.INVALID_CASE, f"Triton device must be npu or interpreter, got {device!r}")
        if device == "interpreter":
            command = [self._python(ctx), "-m", "py_compile", str(kernel)]
        else:
            command = [self._python(ctx), str(kernel), "--bundle", str(ctx.work_dir), "--mode", "compile"]
        environment = self._environment(ctx)
        if bool(ctx.config.get("triton_force_compile")):
            environment["TRITON_ALWAYS_COMPILE"] = "1"
        process = self.runner.run(command, cwd=ctx.work_dir, output_dir=ctx.stage_work_dir / prefix, timeout=max(0.001, deadline - time.monotonic()) if deadline else stage_timeout(ctx.config, "build"), environment=environment)
        if not process.success:
            return self.process_failure("build", process, FailureKind.COMPILE_FAILURE, "Triton compile stage failed")
        message = "validated interpreter harness (no device compilation required)" if device == "interpreter" else "compiled the emitted Triton kernel with the target backend"
        return StageResult.ok("build", message, exit_code=process.exit_code, duration_seconds=process.duration_seconds, command=process.command, artifacts=[ctx.relative(Path(process.stdout_path)), ctx.relative(Path(process.stderr_path))], details={"process": process.to_dict(), "device": device})

    def run(self, ctx: CaseContext) -> StageResult:
        # Invalidate both paths before either is executed, including failed reruns.
        if ctx.config.get("oracle_mode") == "metamorphic":
            for path in (ctx.work_dir / "outputs").glob("triton*.npy"):
                path.unlink()
        return self._paired_stage(ctx, "run")

    def _run_one(self, ctx: CaseContext, artifact="source", prefix="triton", deadline=None) -> StageResult:
        kernel = ctx.work_dir / artifact / "kernel.py"
        if str(ctx.config.get("device", "npu")) not in {"npu", "interpreter"}:
            return StageResult.fail("run", FailureKind.INVALID_CASE, f"unsupported Triton device: {ctx.config.get('device')!r}")
        mode = "interpreter" if str(ctx.config.get("device")) == "interpreter" else "run"
        suffix = "interpreter" if mode == "interpreter" else "npu"
        reference = ctx.work_dir / artifact / "reference_output.npy"
        target = ctx.work_dir / artifact / f"{suffix}_output.npy"
        output_reference = ctx.work_dir / "outputs" / f"{prefix}_reference.npy"
        output_target = ctx.work_dir / "outputs" / f"{prefix}_{suffix}.npy"
        for stale in (reference, target, output_reference, output_target, ctx.work_dir / "outputs" / "oracle.json"):
            stale.unlink(missing_ok=True)
        command = [self._python(ctx), str(kernel), "--bundle", str(ctx.work_dir), "--mode", mode]
        environment = self._environment(ctx)
        if mode == "interpreter":
            environment.update({"TRITON_INTERPRET": "1", "TRITON_KERNEL_DUMP": "0"})
        else:
            environment["TRITON_ALWAYS_COMPILE"] = "0"
        process = self.runner.run(command, cwd=ctx.work_dir, output_dir=ctx.stage_work_dir / prefix, timeout=max(0.001, deadline - time.monotonic()) if deadline else stage_timeout(ctx.config, "run"), environment=environment)
        if not process.success:
            result = self.process_failure("run", process, FailureKind.TARGET_FAILURE, f"Triton {mode} execution failed")
            if result.failure_kind == FailureKind.RUNTIME_FAILURE.value:
                result.failure_kind = FailureKind.TARGET_FAILURE.value
            return result
        missing = [ctx.relative(path) for path in (reference, target) if not path.is_file()]
        if missing:
            return StageResult.fail("run", FailureKind.OUTPUT_MISSING, f"execution returned success but outputs are missing: {', '.join(missing)}", exit_code=process.exit_code, duration_seconds=process.duration_seconds, command=process.command, details={"process": process.to_dict()})
        shutil.copy2(reference, output_reference)
        shutil.copy2(target, output_target)
        return StageResult.ok("run", f"executed real Triton {suffix} and Torch reference paths", exit_code=process.exit_code, duration_seconds=process.duration_seconds, command=process.command, artifacts=[ctx.relative(output_reference), ctx.relative(output_target)], details={"process": process.to_dict(), "target_kind": suffix})

    def oracle(self, ctx: CaseContext) -> StageResult:
        suffix = "interpreter" if str(ctx.config.get("device")) == "interpreter" else "npu"
        reference = ctx.work_dir / "outputs" / "triton_reference.npy"
        target = ctx.work_dir / "outputs" / f"triton_{suffix}.npy"
        metamorphic = ctx.config.get("oracle_mode") == "metamorphic"
        if metamorphic:
            reference = target
            target = ctx.work_dir / "outputs" / f"triton_variant_{suffix}.npy"
        label = f"base_vs_metamorphic_{suffix}" if metamorphic else f"torch_vs_{suffix}"
        missing = [ctx.relative(path) for path in (reference, target) if not path.is_file()]
        if missing:
            return StageResult.fail("oracle", FailureKind.OUTPUT_MISSING, f"oracle inputs missing: {', '.join(missing)}")
        try:
            comparison = compare_npy_files(reference, target, ctx.config)
        except (OSError, ValueError) as exc:
            return StageResult.fail("oracle", FailureKind.OUTPUT_FORMAT_ERROR, f"cannot parse Triton outputs: {exc}")
        target_path = ctx.work_dir / "outputs" / "oracle.json"
        atomic_json(target_path, {"mode": label, "comparison": comparison})
        if not comparison["matches"]:
            return StageResult.fail("oracle", FailureKind.ORACLE_MISMATCH, f"{label} outputs differ", artifacts=[ctx.relative(target_path)], details=comparison)
        return StageResult.ok("oracle", f"{label} outputs match", artifacts=[ctx.relative(target_path)], details=comparison)


def commute_arithmetic(source: str) -> tuple[str, dict]:
    """Swap x/y only in a simple arithmetic kernel, never pointer/index math.

    Limit the minimal MR to the upstream elementwise Add/Mul assignment.
    The Torch reference stays unchanged. Refuse unsupported/no-op mutations.
    """
    tree = ast.parse(source)
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or function.name != "fuzz_kernel":
            continue
        for node in function.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            if not isinstance(node.targets[0], ast.Name) or node.targets[0].id != "value":
                continue
            expr = node.value
            if (isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Mult))
                    and isinstance(expr.left, ast.Name) and expr.left.id == "x"
                    and isinstance(expr.right, ast.Name) and expr.right.id == "y"
                    and expr.lineno == expr.end_lineno):
                before = ast.get_source_segment(source, expr)
                symbol = "+" if isinstance(expr.op, ast.Add) else "*"
                after = f"y {symbol} x"
                lines = source.splitlines(keepends=True)
                line = lines[expr.lineno - 1].encode("utf-8")
                lines[expr.lineno - 1] = (line[:expr.col_offset] + after.encode() + line[expr.end_col_offset:]).decode("utf-8")
                return "".join(lines), {"rule": "arithmetic_commutativity", "before": before,
                                        "after": after, "function": "fuzz_kernel",
                                        "line": expr.lineno, "shared_inputs": "inputs/manifest.json"}
    raise ValueError("arithmetic metamorphic mode requires elementwise_add or elementwise_mul (value = x + y / x * y)")
