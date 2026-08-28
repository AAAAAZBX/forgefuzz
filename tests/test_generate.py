import random

from forgefuzz import OpSpec, RandomGraphGenerator, TensorType


OPS = (
    OpSpec("add", 2, dtypes=("float32",)),
    OpSpec("mul", 2, dtypes=("float32",)),
    OpSpec("relu", 1, dtypes=("float32",)),
)


def test_random_dag_is_deterministic_topological_and_live():
    generator = RandomGraphGenerator(OPS, min_nodes=5, max_nodes=8)
    inputs = {"x": TensorType("float32", (4, 4)), "y": TensorType("float32", (4, 4))}
    graph = generator.generate(random.Random(13), inputs)
    assert graph == generator.generate(random.Random(13), inputs)
    assert 5 <= len(graph.nodes) <= 8

    available = set(graph.inputs)
    producers = {}
    for node in graph.nodes:
        assert set(node.inputs) <= available
        producers[node.id] = node
        available.add(node.id)

    live = set()
    pending = list(graph.outputs)
    while pending:
        value = pending.pop()
        if value in live or value not in producers:
            continue
        live.add(value)
        pending.extend(producers[value].inputs)
    assert live == {node.id for node in graph.nodes}


def test_random_dag_varies_topology_and_operations():
    generator = RandomGraphGenerator(OPS, min_nodes=3, max_nodes=8)
    inputs = {"x": TensorType("float32", (4, 4)), "y": TensorType("float32", (4, 4))}
    signatures = {
        tuple((node.op, node.inputs) for node in generator.generate(random.Random(seed), inputs).nodes)
        for seed in range(20)
    }
    assert len(signatures) > 10
