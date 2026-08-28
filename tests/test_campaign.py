import json
import random
from pathlib import Path

from forgefuzz import Graph
from forgefuzz.adapters import PythonAdapter
from forgefuzz.engine import Campaign, CampaignConfig


def test_python_campaign_runs_and_persists(tmp_path: Path):
    output = tmp_path / "run"
    summary = Campaign(PythonAdapter(), CampaignConfig(output, iterations=4, seed=7)).run()
    assert summary["success"] == 4
    assert summary["failure"] == 0
    assert (output / "summary.json").is_file()
    assert len(list((output / "cases").glob("*/graph.json"))) == 4
    assert list((output / "corpus" / "queue").glob("*.json"))
    assert json.loads((output / "summary.json").read_text()) == summary


def test_seed_is_deterministic(tmp_path: Path):
    graphs = []
    for name in ("a", "b"):
        output = tmp_path / name
        Campaign(PythonAdapter(), CampaignConfig(output, iterations=3, seed=19)).run()
        graphs.append([(p.read_text()) for p in sorted((output / "cases").glob("*/graph.json"))])
    assert graphs[0] == graphs[1]


def test_graph_roundtrip_and_replay(tmp_path: Path):
    adapter = PythonAdapter()
    graph = adapter.generate(random.Random(4))
    restored = Graph.from_dict(graph.to_dict())
    assert restored == graph
    result = Campaign(adapter, CampaignConfig(tmp_path / "replay")).replay(restored)
    assert result.success
    assert (tmp_path / "replay/result.json").is_file()
