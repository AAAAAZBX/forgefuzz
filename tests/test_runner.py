import sys
from pathlib import Path

from forgefuzz.runner import ProcessRunner


def test_runner_captures_output(tmp_path: Path):
    result = ProcessRunner().run(
        (sys.executable, "-c", "print('hello')"), cwd=tmp_path,
        log_path=tmp_path / "run.log", timeout_seconds=2,
    )
    assert result.ok
    assert "hello" in result.log_tail


def test_runner_times_out(tmp_path: Path):
    result = ProcessRunner().run(
        (sys.executable, "-c", "import time; time.sleep(5)"), cwd=tmp_path,
        log_path=tmp_path / "timeout.log", timeout_seconds=0.05,
    )
    assert result.timed_out
