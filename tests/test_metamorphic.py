import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from forgefuzz.adapters import NumPyAdapter
from forgefuzz.engine import Campaign, CampaignConfig
from forgefuzz.model import FailureKind


def _graph_with_commutative_node(adapter: NumPyAdapter):
    for seed in range(100):
        graph = adapter.generate(random.Random(seed))
        if any(node.op in adapter.commutative_ops for node in graph.nodes):
            return graph
    raise AssertionError("generator did not produce a commutative operation")


def test_numpy_metamorphic_campaign_persists_base_and_variant(tmp_path: Path):
    output = tmp_path / "run"
    summary = Campaign(
        NumPyAdapter(), CampaignConfig(output, iterations=4, seed=3, metamorphic_variants=1),
    ).run()
    assert summary["failure"] == 0
    assert (output / "cases/id_000000/base/program/case.py").is_file()
    transforms = list((output / "cases").glob("*/variants/*/transform.json"))
    assert transforms
    assert json.loads(transforms[0].read_text())["relation"] == "commutative-input-swap"


def test_numpy_metamorphic_oracle_detects_difference(tmp_path: Path):
    adapter = NumPyAdapter()
    graph = _graph_with_commutative_node(adapter)
    base = tmp_path / "base"
    variant = tmp_path / "variant"
    base_result = Campaign(adapter, CampaignConfig(base))._execute(graph, base)
    relation = tuple(adapter.metamorphic_variants(graph, random.Random(1)))[0]
    variant_result = Campaign(adapter, CampaignConfig(variant))._execute(relation.graph, variant)
    bad_log = variant_result.run.log_path
    bad_log.write_text('{"output": [[999.0]]}\n', encoding="utf-8")
    bad_run = replace(variant_result.run, log_tail=bad_log.read_text())
    verdict = adapter.metamorphic_oracle(
        adapter.emit(graph, base / "program2"), base_result, relation,
        adapter.emit(relation.graph, variant / "program2"), replace(variant_result, run=bad_run),
    )
    assert verdict.kind is FailureKind.OUTPUT_MISMATCH
