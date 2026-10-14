from __future__ import annotations

from pathlib import Path
from functools import lru_cache
import platform
import subprocess
import sys
from typing import Any


def _git_value(root: Path, *arguments: str) -> str | None:
    if not root.is_dir():
        return None
    try:
        process = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.stdout.strip() if process.returncode == 0 else None


def _git_dirty(root: Path) -> bool | None:
    if not root.is_dir():
        return None
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "diff-index", "--quiet", "HEAD", "--"],
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode == 0:
        return False
    if process.returncode == 1:
        return True
    return None


@lru_cache(maxsize=16)
def _project_for_path(root_text: str) -> dict[str, Any]:
    root = Path(root_text)
    commit = _git_value(root, "rev-parse", "HEAD")
    return {
        "path": str(root),
        "exists": root.is_dir(),
        "git_commit": commit,
        "git_dirty": _git_dirty(root),
    }


def _project(root_value: Any) -> dict[str, Any]:
    root = Path(str(root_value)).expanduser().resolve()
    return dict(_project_for_path(str(root)))


def collect_provenance(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
        "triton_project": _project(config.get("triton_root", "")),
        "ascendc_project": _project(config.get("ascendc_root", "")),
        "triton_python": config.get("triton_python"),
        "cann_path": config.get("ascend_cann_path"),
        "soc_version": config.get("ascend_soc_version"),
    }
