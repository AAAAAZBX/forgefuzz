from __future__ import annotations

import math
from pathlib import Path
import struct
from typing import Any


def load_float32(path: Path) -> list[float]:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty output: {path}")
    if len(data) % 4:
        raise ValueError(f"output byte size is not float32-aligned: {path} ({len(data)} bytes)")
    return list(struct.unpack(f"<{len(data) // 4}f", data))


def compare_values(expected: list[float], actual: list[float], *, mode: str, atol: float, rtol: float, equal_nan: bool) -> dict[str, Any]:
    if len(expected) != len(actual):
        return {"matches": False, "reason": "shape_mismatch", "expected_count": len(expected), "actual_count": len(actual)}
    mismatch_count = 0
    first_mismatch = None
    max_abs_error = 0.0
    max_rel_error = 0.0
    for index, (left, right) in enumerate(zip(expected, actual)):
        if math.isnan(left) or math.isnan(right):
            matches = equal_nan and math.isnan(left) and math.isnan(right)
            absolute = relative = math.nan
        elif math.isinf(left) or math.isinf(right):
            matches = left == right
            absolute = 0.0 if matches else math.inf
            relative = absolute
        else:
            absolute = abs(left - right)
            relative = absolute / max(abs(left), 1e-38)
            matches = left == right if mode == "exact" else absolute <= atol + rtol * abs(left)
        if math.isfinite(absolute):
            max_abs_error = max(max_abs_error, absolute)
        if math.isfinite(relative):
            max_rel_error = max(max_rel_error, relative)
        if not matches:
            mismatch_count += 1
            if first_mismatch is None:
                first_mismatch = {"index": index, "expected": left, "actual": right}
    return {
        "matches": mismatch_count == 0,
        "reason": "match" if mismatch_count == 0 else "numeric_mismatch",
        "element_count": len(expected),
        "mismatch_count": mismatch_count,
        "max_abs_error": max_abs_error,
        "max_rel_error": max_rel_error,
        "first_mismatch": first_mismatch,
        "policy": {"mode": mode, "atol": atol, "rtol": rtol, "equal_nan": equal_nan},
    }


def compare_float32_files(expected: Path, actual: Path, config: dict[str, Any]) -> dict[str, Any]:
    return compare_values(load_float32(expected), load_float32(actual), mode=str(config.get("comparison", "allclose")), atol=float(config.get("atol", 1e-4)), rtol=float(config.get("rtol", 1e-4)), equal_nan=bool(config.get("equal_nan", True)))


def compare_npy_files(expected: Path, actual: Path, config: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    left = np.load(expected, allow_pickle=False)
    right = np.load(actual, allow_pickle=False)
    if left.shape != right.shape:
        return {"matches": False, "reason": "shape_mismatch", "expected_shape": list(left.shape), "actual_shape": list(right.shape)}
    if left.dtype != right.dtype:
        return {"matches": False, "reason": "dtype_mismatch", "expected_dtype": str(left.dtype), "actual_dtype": str(right.dtype)}
    mode = str(config.get("comparison", "allclose"))
    if mode == "exact":
        close = np.equal(left, right)
        if bool(config.get("equal_nan", True)) and np.issubdtype(left.dtype, np.floating):
            close |= np.isnan(left) & np.isnan(right)
    else:
        close = np.isclose(left, right, atol=float(config.get("atol", 1e-4)), rtol=float(config.get("rtol", 1e-4)), equal_nan=bool(config.get("equal_nan", True)))
    mismatch = ~close
    count = int(np.count_nonzero(mismatch))
    result: dict[str, Any] = {
        "matches": count == 0,
        "reason": "match" if count == 0 else "numeric_mismatch",
        "shape": list(left.shape),
        "dtype": str(left.dtype),
        "element_count": int(left.size),
        "mismatch_count": count,
        "policy": {"mode": mode, "atol": float(config.get("atol", 1e-4)), "rtol": float(config.get("rtol", 1e-4)), "equal_nan": bool(config.get("equal_nan", True))},
    }
    if count:
        index = tuple(int(i) for i in np.argwhere(mismatch)[0])
        result["first_mismatch"] = {"index": list(index), "expected": left[index].item(), "actual": right[index].item()}
    return result
