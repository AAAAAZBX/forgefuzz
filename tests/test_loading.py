from pathlib import Path

from forgefuzz.loading import load_adapter
from forgefuzz.scaffold import create_adapter_project


def test_builtin_adapter_loads():
    assert load_adapter("python").name == "python"


def test_scaffold_contains_installable_contract(tmp_path: Path):
    project = create_adapter_project(tmp_path / "demo-fuzzer", "demo")
    assert (project / "pyproject.toml").is_file()
    assert (project / "src" / "demo_fuzzer" / "adapter.py").is_file()
    manifest = (project / "pyproject.toml").read_text()
    assert 'forgefuzz.adapters' in manifest
    assert 'demo_fuzzer.adapter:DemoAdapter' in manifest
