from __future__ import annotations

import json
import random
import sys
from dataclasses import replace
from pathlib import Path

from ..generate import OpSpec, RandomGraphGenerator
from ..model import ExecutionResult, FailureKind, Graph, Node, ProgramArtifact, TensorType
from ..plugin import LanguageAdapter


class PyTorchAdapter(LanguageAdapter):
    """Small differential example: eager output vs ``torch.compile`` output."""

    name = "pytorch"
    binary_ops = ("add", "sub", "mul")
    unary_ops = ("relu", "sigmoid")
    op_specs = tuple(
        OpSpec(name, arity, dtypes=("float32",), ranks=(2,))
        for name, arity in (
            ("add", 2), ("sub", 2), ("mul", 2), ("relu", 1), ("sigmoid", 1),
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
        candidates = self.unary_ops if len(node.inputs) == 1 else self.binary_ops
        choices = [op for op in candidates if op != node.op]
        nodes[index] = replace(node, op=rng.choice(choices))
        return replace(graph, nodes=tuple(nodes))

    def validate(self, graph: Graph):
        available = set(graph.inputs)
        for node in graph.nodes:
            expected_arity = 1 if node.op in self.unary_ops else 2 if node.op in self.binary_ops else None
            if expected_arity is None:
                yield f"unsupported PyTorch operation: {node.op}"
            elif len(node.inputs) != expected_arity:
                yield f"{node.id}: {node.op} expects {expected_arity} inputs"
            unknown = set(node.inputs) - available
            if unknown:
                yield f"{node.id}: unknown inputs {sorted(unknown)}"
            available.add(node.id)
        unknown_outputs = set(graph.outputs) - available
        if unknown_outputs:
            yield f"unknown outputs: {sorted(unknown_outputs)}"

    def emit(self, graph: Graph, output_dir: Path) -> ProgramArtifact:
        output_dir.mkdir(parents=True, exist_ok=True)
        expressions = {"x": "x", "y": "y"}
        calls = {
            "add": "torch.add({0}, {1})",
            "sub": "torch.sub({0}, {1})",
            "mul": "torch.mul({0}, {1})",
            "relu": "torch.relu({0})",
            "sigmoid": "torch.sigmoid({0})",
        }
        body: list[str] = []
        for node in graph.nodes:
            arguments = [expressions[name] for name in node.inputs]
            body.append(f"    {node.id} = {calls[node.op].format(*arguments)}")
            expressions[node.id] = node.id
        body.append(f"    return {expressions[graph.outputs[0]]}")
        input_seed = int(graph.metadata.get("input_seed", 0))
        source = "\n".join([
            "import json",
            "import os",
            "import torch",
            "",
            "def forward(x, y):",
            *body,
            "",
            f"torch.manual_seed({input_seed})",
            "x = torch.randn(4, 4, dtype=torch.float32)",
            "y = torch.randn(4, 4, dtype=torch.float32)",
            "expected = forward(x, y)",
            "backend = os.environ.get('FORGEFUZZ_TORCH_BACKEND', 'eager')",
            "compiled = torch.compile(forward, backend=backend)",
            "actual = compiled(x, y)",
            "diff = (actual - expected).abs()",
            "print(json.dumps({",
            "    'backend': backend,",
            "    'actual': actual.detach().cpu().tolist(),",
            "    'expected': expected.detach().cpu().tolist(),",
            "    'max_abs_diff': float(diff.max()),",
            "}))",
        ]) + "\n"
        script = output_dir / "case.py"
        script.write_text(source, encoding="utf-8")
        return ProgramArtifact(
            script, (script,), run_command=(sys.executable, str(script)),
            metadata={
                "node_count": len(graph.nodes), "edge_count": graph.edge_count,
                "depth": graph.depth, "operations": [node.op for node in graph.nodes],
            },
        )

    def oracle(self, artifact: ProgramArtifact, result: ExecutionResult) -> ExecutionResult:
        if not result.success or result.run is None:
            return result
        try:
            payload = json.loads(result.run.log_tail.strip().splitlines()[-1])
            max_abs_diff = float(payload["max_abs_diff"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return replace(
                result, kind=FailureKind.OUTPUT_MISMATCH, stage="oracle",
                message=f"cannot parse PyTorch result: {exc}",
            )
        if max_abs_diff > 1e-5:
            return replace(
                result, kind=FailureKind.OUTPUT_MISMATCH, stage="oracle",
                message=f"eager/compiled max_abs_diff={max_abs_diff} exceeds 1e-5",
            )
        return result

    def observe(self, artifact: ProgramArtifact, result: ExecutionResult):
        yield f"result:{result.kind.value}"
        yield f"graph:nodes:{artifact.metadata['node_count']}"
        yield f"graph:depth:{artifact.metadata['depth']}"
        for operation in artifact.metadata["operations"]:
            yield f"api:{operation}"
        if result.run and result.run.ok:
            try:
                payload = json.loads(result.run.log_tail.strip().splitlines()[-1])
                yield f"backend:{payload['backend']}"
            except (IndexError, KeyError, json.JSONDecodeError):
                pass
