from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


def _check(label: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": label, "ok": ok, "detail": detail, "fix": fix}


def run_doctor(config: dict[str, Any], *, backend: str | None = None) -> tuple[list[dict[str, Any]], bool]:
    checks: list[dict[str, Any]] = []
    triton_root = Path(config["triton_root"])
    ascend_root = Path(config["ascendc_root"])
    check_triton = backend in {None, "triton"}
    check_ascend = backend in {None, "ascendc"}
    if check_triton:
        checks.append(_check("Triton project", (triton_root / "triton_ascend_fuzz" / "workflow.py").is_file(), str(triton_root), "set triton_root to triton-fuzzer-main"))
        triton_python = Path(config.get("triton_python") or triton_root / ".envs" / "triton-ascend" / "bin" / "python")
        checks.append(_check("Triton Python", triton_python.is_file(), str(triton_python), "set triton_python to the pinned Python environment"))
        if triton_python.is_file():
            with tempfile.TemporaryDirectory(prefix="forgefuzz-doctor-") as cache:
                env = {
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": cache,
                    "PYTHONPATH": str(triton_root / "third_party" / "triton-ascend" / "python") + os.pathsep + os.environ.get("PYTHONPATH", ""),
                }
                try:
                    probe = subprocess.run([str(triton_python), "-c", "import torch, torch_npu, triton; print(triton.__file__)"], capture_output=True, text=True, timeout=60, env=env)
                    detail = (probe.stdout or probe.stderr).strip().splitlines()
                    checks.append(_check("Triton runtime", probe.returncode == 0, detail[-1] if detail else f"exit {probe.returncode}", "repair the pinned environment or set triton_python"))
                except (OSError, subprocess.TimeoutExpired) as exc:
                    checks.append(_check("Triton runtime", False, str(exc), "repair the pinned environment or set triton_python"))
    if check_ascend:
        checks.append(_check("AscendC project", (ascend_root / "generate_graph.py").is_file(), str(ascend_root), "set ascendc_root to fuzz_code_generation"))
        required_ascend = ["execute_graph.py", "split_cpp_sections.py", "baremix/compile.sh", "baremix/run_once.sh", "metamorphic/inject_and_generate.py"]
        missing = [name for name in required_ascend if not (ascend_root / name).is_file()]
        checks.append(_check("AscendC integration files", not missing, "complete" if not missing else f"missing: {', '.join(missing)}", "restore the listed files in the old project"))
        for command in ("bash", "cmake"):
            path = shutil.which(command)
            checks.append(_check(command, path is not None, path or "not found", f"install {command} and put it on PATH"))
    if check_triton:
        module = "numpy"
        found = importlib.util.find_spec(module) is not None
        checks.append(_check(f"Python module {module}", found, "available" if found else "not importable", f"install {module} in the ForgeFuzz Python environment"))
    cann_value = config.get("ascend_cann_path") or os.environ.get("ASCEND_HOME_PATH") or "/usr/local/Ascend/ascend-toolkit/latest"
    cann = Path(cann_value)
    target_npu = (check_triton and config.get("device") == "npu") or (check_ascend and config.get("ascend_run_mode") == "npu")
    if check_ascend or target_npu:
        checks.append(_check("CANN", (cann / "bin" / "setenv.bash").is_file(), str(cann), "set ascend_cann_path or ASCEND_HOME_PATH"))
    npu_smi = shutil.which("npu-smi")
    if target_npu and npu_smi:
        try:
            probe = subprocess.run([npu_smi, "info"], capture_output=True, text=True, timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            detail = (probe.stdout or probe.stderr).strip().splitlines()
            checks.append(_check("NPU device", probe.returncode == 0, detail[0] if detail else f"exit {probe.returncode}", "check driver/device permissions"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append(_check("NPU device", False, str(exc), "check npu-smi and driver health"))
    elif target_npu:
        checks.append(_check("NPU device", False, "npu-smi not found", "install/activate the Ascend driver environment"))
    return checks, all(item["ok"] for item in checks)


def print_doctor(checks: list[dict[str, Any]]) -> None:
    width = max(len(item["name"]) for item in checks)
    for item in checks:
        status = "OK" if item["ok"] else "MISSING"
        print(f"{status:7} {item['name']:<{width}}  {item['detail']}")
        if not item["ok"] and item["fix"]:
            print(f"        {'':<{width}}  fix: {item['fix']}")
