from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 remains usable with JSON configs.
    tomllib = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent

DEFAULT_CONFIG: dict[str, Any] = {
    "triton_root": str(WORKSPACE_ROOT / "triton-fuzzer-main"),
    "triton_python": None,
    "ascendc_root": str(WORKSPACE_ROOT / "fuzz_code_generation"),
    "output_dir": str(PROJECT_ROOT / "runs"),
    "timeout": 120.0,
    "stage_timeouts": {},
    "device": "npu",
    "oracle_mode": "auto",
    "comparison": "allclose",
    "atol": 1e-4,
    "rtol": 1e-4,
    "equal_nan": True,
    "keep_temp": True,
    "triton_profile": "P1",
    "triton_template": None,
    "triton_case_index": 0,
    "triton_semantic_api_count": 5,
    "triton_interpreter_oracle": False,
    "triton_force_compile": False,
    "ascend_nodes": 8,
    "ascend_ops": "Add,Mul,Sub,Abs,Relu",
    "ascend_run_mode": "npu",
    "ascend_reference_run_mode": "cpu",
    "ascend_soc_version": "Ascend910B3",
    "ascend_cann_path": None,
    "ascend_tensor_len": 64,
    "ascend_data_dtype": "float32",
    "ascend_data_range": "normal",
    "ascend_variant_flags": "-fno-fast-math -ffp-contract=off",
    "ascend_binary_injections": 2,
    "ascend_unary_injections": 1,
    "reference_output": None,
}


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(DEFAULT_CONFIG)
    value["stage_timeouts"] = {}
    loaded: dict[str, Any] = {}
    if path is not None:
        raw = path.read_bytes()
        if path.suffix.lower() == ".toml" and tomllib is None:
            raise ValueError("TOML config requires Python 3.11+; use JSON with this interpreter")
        loaded = tomllib.loads(raw.decode("utf-8")) if path.suffix.lower() == ".toml" else json.loads(raw)
        if path.suffix.lower() == ".toml":
            loaded = loaded.get("forgefuzz", loaded)
        if not isinstance(loaded, dict):
            raise ValueError("config root must be an object/table")
        value.update(loaded)
        if "device" in loaded and "ascend_run_mode" not in loaded:
            value["ascend_run_mode"] = loaded["device"]
    override_values = overrides or {}
    for key, item in override_values.items():
        if item is not None:
            value[key] = item
    if override_values.get("device") is not None and override_values.get("ascend_run_mode") is None:
        value["ascend_run_mode"] = override_values["device"]
    for key in ("triton_root", "ascendc_root", "output_dir"):
        value[key] = str(Path(value[key]).expanduser().resolve())
    if value.get("triton_python"):
        value["triton_python"] = str(Path(value["triton_python"]).expanduser().resolve())
    if value.get("ascend_cann_path"):
        value["ascend_cann_path"] = str(Path(value["ascend_cann_path"]).expanduser().resolve())
    elif os.environ.get("ASCEND_HOME_PATH"):
        value["ascend_cann_path"] = os.environ["ASCEND_HOME_PATH"]
    if value.get("reference_output"):
        value["reference_output"] = str(Path(value["reference_output"]).expanduser().resolve())
    _positive_float(value["timeout"], "timeout")
    for name in ("atol", "rtol"):
        number = _finite_float(value[name], name)
        if number < 0:
            raise ValueError(f"{name} must be non-negative")
    if value["comparison"] not in {"exact", "allclose"}:
        raise ValueError("comparison must be exact or allclose")
    if value["device"] not in {"npu", "cpu", "sim", "interpreter"}:
        raise ValueError("device must be npu, cpu, sim, or interpreter")
    if value["oracle_mode"] not in {"auto", "metamorphic", "cpu_npu", "compile_diff", "golden", "external", "torch"}:
        raise ValueError("unsupported oracle_mode")
    for name in ("triton_semantic_api_count", "ascend_nodes", "ascend_tensor_len"):
        _positive_int(value[name], name)
    for name in ("triton_case_index", "ascend_binary_injections", "ascend_unary_injections"):
        _non_negative_int(value[name], name)
    if not isinstance(value["ascend_ops"], str) or not any(item.strip() for item in value["ascend_ops"].split(",")):
        raise ValueError("ascend_ops must contain at least one operation")
    if value["ascend_data_dtype"] != "float32":
        raise ValueError("only ascend_data_dtype=float32 is supported by the current oracle")
    timeouts = value.get("stage_timeouts")
    if not isinstance(timeouts, dict):
        raise ValueError("stage_timeouts must be an object/table")
    for stage, timeout in timeouts.items():
        if stage not in {"generate", "emit", "build", "run", "oracle", "report"}:
            raise ValueError(f"unknown stage timeout: {stage}")
        _positive_float(timeout, f"stage_timeouts.{stage}")
    return value


def _finite_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive_float(value: Any, name: str) -> float:
    number = _finite_float(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if str(number) != str(value) and not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return number


def _positive_int(value: Any, name: str) -> int:
    number = _integer(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _non_negative_int(value: Any, name: str) -> int:
    number = _integer(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def validate_backend_config(config: dict[str, Any], backend: str) -> None:
    if backend == "triton":
        if config["device"] not in {"npu", "interpreter"}:
            raise ValueError("Triton supports --device npu or interpreter")
        if config["oracle_mode"] not in {"auto", "torch", "metamorphic"}:
            raise ValueError("Triton supports --oracle-mode auto, torch, or metamorphic")
        return
    if backend != "ascendc":
        raise ValueError(f"unknown backend: {backend}")
    if config["device"] == "interpreter":
        raise ValueError("AscendC does not support --device interpreter")
    if config["ascend_run_mode"] != config["device"]:
        raise ValueError("device and ascend_run_mode disagree; use device as the target run mode")
    if config["oracle_mode"] not in {"auto", "metamorphic", "cpu_npu", "compile_diff", "golden", "external"}:
        raise ValueError(f"AscendC does not support oracle mode {config['oracle_mode']!r}")
    if config["oracle_mode"] == "external":
        reference = config.get("reference_output")
        if not reference:
            raise ValueError("oracle_mode=external requires reference_output")
        if not Path(reference).expanduser().is_file():
            raise ValueError(f"reference_output does not exist: {reference}")


def stage_timeout(config: dict[str, Any], stage: str) -> float:
    overrides = config.get("stage_timeouts", {})
    value = overrides.get(stage, config.get("timeout", 120.0)) if isinstance(overrides, dict) else config.get("timeout", 120.0)
    return _positive_float(value, f"timeout for {stage}")
