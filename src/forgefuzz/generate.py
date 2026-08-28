from __future__ import annotations

import random
from dataclasses import dataclass, field

from .model import Graph, JsonValue, Node, TensorType


@dataclass(frozen=True, slots=True)
class OpSpec:
    """Language-neutral contract for a same-shaped tensor operation."""

    name: str
    arity: int
    dtypes: tuple[str, ...] = ()
    ranks: tuple[int, ...] = ()
    attributes: dict[str, tuple[JsonValue, ...]] = field(default_factory=dict)

    def accepts(self, tensor: TensorType) -> bool:
        return (
            self.arity > 0
            and (not self.dtypes or tensor.dtype in self.dtypes)
            and (not self.ranks or len(tensor.shape) in self.ranks)
        )

    def sample_attributes(self, rng: random.Random) -> dict[str, JsonValue]:
        return {name: rng.choice(values) for name, values in self.attributes.items() if values}


class RandomGraphGenerator:
    """Build a deterministic, fully-live DAG from an operation catalog.

    Every new node consumes the previous node, creating a live backbone. Extra
    operands are selected from compatible inputs or older nodes, producing
    branches and merge edges without forward references or cycles.
    """

    def __init__(self, operations: tuple[OpSpec, ...], min_nodes: int = 3, max_nodes: int = 8):
        if not operations:
            raise ValueError("operations must not be empty")
        if min_nodes <= 0 or max_nodes < min_nodes:
            raise ValueError("expected 0 < min_nodes <= max_nodes")
        self.operations = operations
        self.min_nodes = min_nodes
        self.max_nodes = max_nodes

    def generate(
        self, rng: random.Random, inputs: dict[str, TensorType],
        metadata: dict[str, JsonValue] | None = None,
    ) -> Graph:
        if not inputs:
            raise ValueError("at least one graph input is required")
        available = dict(inputs)
        previous: str | None = None
        nodes: list[Node] = []
        count = rng.randint(self.min_nodes, self.max_nodes)

        for index in range(count):
            anchor_name = previous or rng.choice(tuple(available))
            anchor_type = available[anchor_name]
            candidates = [spec for spec in self.operations if spec.accepts(anchor_type)]
            if index == 0 and len(inputs) > 1:
                multi_input = [spec for spec in candidates if spec.arity > 1]
                candidates = multi_input or candidates
            if not candidates:
                raise ValueError(f"no operation accepts value {anchor_name}: {anchor_type}")
            spec = rng.choice(candidates)
            compatible = [name for name, kind in available.items() if kind == anchor_type]
            operands = [anchor_name]
            while len(operands) < spec.arity:
                choices = [name for name in compatible if name not in operands] or compatible
                operands.append(rng.choice(choices))
            rng.shuffle(operands)
            node_id = f"n{index}"
            nodes.append(Node(
                node_id, spec.name, tuple(operands), anchor_type,
                spec.sample_attributes(rng),
            ))
            available[node_id] = anchor_type
            previous = node_id

        graph_metadata = dict(metadata or {})
        graph_metadata.update({"generator": "random_dag", "node_count": count})
        return Graph(dict(inputs), tuple(nodes), (nodes[-1].id,), graph_metadata)
