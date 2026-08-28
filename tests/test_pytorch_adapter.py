import json
import random
from pathlib import Path

import pytest

pytest.importorskip("torch")

from forgefuzz.adapters import PyTorchAdapter
from forgefuzz.engine import Campaign, CampaignConfig


def test_pytorch_graph_is_deterministic_and_valid():
    adapter = PyTorchAdapter()
    first = adapter.generate(random.Random(7))
    second = adapter.generate(random.Random(7))
    assert first == second
    assert list(adapter.validate(first)) == []
    assert 3 <= len(first.nodes) <= 8
    assert first.metadata["generator"] == "random_dag"


def test_pytorch_campaign(tmp_path: Path):
    output = tmp_path / "pytorch"
    summary = Campaign(
        PyTorchAdapter(), CampaignConfig(output, iterations=4, seed=3, timeout_seconds=60),
    ).run()
    assert summary["success"] == 4
    assert summary["generated"] >= 1
    assert summary["mutated"] >= 1
    payload = json.loads((output / "cases/id_000000/result.json").read_text())
    assert "backend:eager" in payload["features"]
    assert any(feature.startswith("graph:nodes:") for feature in payload["features"])
