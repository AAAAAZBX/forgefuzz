from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import resource
from collections.abc import Mapping, Sequence

from .models import ProcessResult


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class ProcessRunner:
    """Run one command in an isolated process group and persist diagnostics."""

    def run(self, command: Sequence[str], *, cwd: Path, output_dir: Path, timeout: float, environment: Mapping[str, str] | None = None) -> ProcessResult:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        command = [str(item) for item in command]
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = output_dir / "stdout.log", output_dir / "stderr.log"
        env = dict(os.environ)
        overrides = {str(key): str(value) for key, value in (environment or {}).items()}
        env.update(overrides)
        (output_dir / "command.json").write_text(json.dumps({"argv": command, "cwd": str(cwd), "environment_overrides": overrides}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        start = time.monotonic()
        exit_code: int | None = None
        timed_out = False
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True, preexec_fn=_child_limits)
            except OSError as exc:
                stderr.write(f"{type(exc).__name__}: {exc}\n".encode("utf-8", errors="replace"))
                return ProcessResult(command, str(cwd), 127, time.monotonic() - start, False, str(stdout_path), str(stderr_path))
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    exit_code = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    exit_code = process.wait()
        return ProcessResult(command, str(cwd), exit_code, time.monotonic() - start, timed_out, str(stdout_path), str(stderr_path))


def log_tail(path: Path, limit: int = 6000) -> str:
    if not path.is_file():
        return ""
    return path.read_bytes()[-limit:].decode("utf-8", errors="replace")
