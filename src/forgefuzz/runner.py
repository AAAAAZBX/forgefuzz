from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence

from .model import ProcessResult


class ProcessRunner:
    """Run one stage in an isolated process group with a hard timeout."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        timeout_seconds: float,
        environment: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(environment or {})
        start = time.monotonic()
        timed_out = False
        returncode: int | None = None
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [str(item) for item in command], cwd=cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    returncode = process.wait(timeout=2)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    returncode = process.wait()
        data = log_path.read_bytes()[-65536:]
        return ProcessResult(
            tuple(str(x) for x in command), returncode, time.monotonic() - start,
            timed_out, log_path, data.decode(errors="replace"),
        )
