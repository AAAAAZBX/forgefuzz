from __future__ import annotations

import json
import random
import sys
from dataclasses import replace
from pathlib import Path

from ..generate import OpSpec, RandomGraphGenerator
from ..model import (
    ExecutionResult, FailureKind, Graph, MetamorphicVariant, Node, ProgramArtifact,
    TensorType,
)
from ..plugin import LanguageAdapter


def _payload(result: ExecutionResult) -> dict:
    if result.run is None:
        raise ValueError("execution has no run result")
    return json.loads(result.run.log_tail.strip().splitlines()[-1])


class NumPyAdapter(LanguageAdapter):
    """Runnable reference backend with differential and metamorphic checking."""

    name = "numpy"
    binary_ops = ("add", "subtract", "multiply", "maximum")
    commutative_ops = ("add", "multiply", "maximum")
    unary_ops = ("negative", "absolute", "tanh")
    op_specs = tuple(
        OpSpec(name, arity, dtypes=("float32",), ranks=(2,))
        for name, arity in (
            ("add", 2), ("subtract", 2), ("multiply", 2), ("maximum", 2),
            ("negative", 1), ("absolute", 1), ("tanh", 1),
        )
    )

    def __init__(self, min_nodes: int = 3, max_nodes: int = 8):
        self.generator = RandomGraphGenerator(self.op_specs, min_nodes, max_nodes)

    def generate(self, rng: random.Random) -> Graph:
        tensor = TensorType("float32", (4, 4))
        return self.generator.generate(
            rng, {"x": tensor, "y": tensor},
            {"adapter": self.name, "input_seed": rng.randrange(2**31)},
        )

    def mutate(self, graph: Graph, rng: random.Random) -> Graph:
        nodes = list(graph.nodes)
        index = rng.randrange(len(nodes))
        node = nodes[index]
        pool = self.unary_ops if len(node.inputs) == 1 else self.binary_ops
        choices = [op for op in pool if op != node.op]
        nodes[index] = replace(node, op=rng.choice(choices))
        return replace(graph, nodes=tuple(nodes))

    def validate(self, graph: Graph):
        available = set(graph.inputs)
        for node in graph.nodes:
            arity = 1 if node.op in self.unary_ops else 2 if node.op in self.binary_ops else None
            if arity is None:
                yield f"unsupported NumPy operation: {node.op}"
            elif len(node.inputs) != arity:
                yield f"{node.id}: {node.op} expects {arity} inputs"
            if set(node.inputs) - available:
                yield f"{node.id}: contains a forward or unknown reference"
            available.add(node.id)
        if set(graph.outputs) - available:
            yield "graph contains unknown outputs"

    def emit(self, graph: Graph, output_dir: Path) -> ProgramArtifact:
        output_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "import json", "import numpy as np", f"rng = np.random.default_rng({int(graph.metadata.get('input_seed', 0))})",
            "x = rng.normal(size=(4, 4)).astype(np.float32)",
            "y = rng.normal(size=(4, 4)).astype(np.float32)",
        ]
        for node in graph.nodes:
            args = ", ".join(node.inputs)
            lines.append(f"{node.id} = np.{node.op}({args})")
        lines.append(f"print(json.dumps({{'output': {graph.outputs[0]}.tolist()}}))")
        script = output_dir / "case.py"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ProgramArtifact(
            script, (script,), run_command=(sys.executable, str(script.resolve())),
            metadata={"operations": [n.op for n in graph.nodes], "depth": graph.depth},
        )

    def metamorphic_variants(self, graph: Graph, rng: random.Random):
        candidates = [i for i, node in enumerate(graph.nodes) if node.op in self.commutative_ops]
        if not candidates:
            return ()
        index = rng.choice(candidates)
        nodes = list(graph.nodes)
        node = nodes[index]
        nodes[index] = replace(node, inputs=(node.inputs[1], node.inputs[0]))
        variant_graph = replace(graph, nodes=tuple(nodes))
        return (MetamorphicVariant(
            f"commute_{node.id}", "commutative-input-swap", variant_graph,
            {"node": node.id, "operation": node.op},
        ),)

    def metamorphic_oracle(self, base_artifact, base_result, variant, variant_artifact, variant_result):
        try:
            import numpy as np
            expected = np.asarray(_payload(base_result)["output"], dtype=np.float64)
            actual = np.asarray(_payload(variant_result)["output"], dtype=np.float64)
            equal = np.allclose(actual, expected, rtol=1e-5, atol=1e-6, equal_nan=True)
            difference = float(np.nanmax(np.abs(actual - expected))) if actual.size else 0.0
        except Exception as exc:
            return replace(variant_result, kind=FailureKind.OUTPUT_MISMATCH,
                           stage="metamorphic-oracle", message=f"cannot compare outputs: {exc}")
        if not equal:
            return replace(
                variant_result, kind=FailureKind.OUTPUT_MISMATCH,
                stage="metamorphic-oracle",
                message=f"{variant.relation} violated; max_abs_diff={difference}",
            )
        return variant_result

    def observe(self, artifact: ProgramArtifact, result: ExecutionResult):
        yield f"result:{result.kind.value}"
        yield f"graph:depth:{artifact.metadata['depth']}"
        for operation in artifact.metadata["operations"]:
            yield f"api:{operation}"
