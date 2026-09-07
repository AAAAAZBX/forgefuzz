from __future__ import annotations

import random
import sys
from pathlib import Path

from ..model import ExecutionResult, Graph, Node, ProgramArtifact, TensorType
from ..plugin import LanguageAdapter


class PythonAdapter(LanguageAdapter):
    """Dependency-free example adapter; also serves as an adapter template."""

    name = "python"
    operations = ("add", "sub", "mul", "max")

    def generate(self, rng: random.Random) -> Graph:
        dtype = TensorType("float", (4,))
        node = Node("n0", rng.choice(self.operations), ("x", "y"), dtype)
        return Graph({"x": dtype, "y": dtype}, (node,), ("n0",), {"adapter": self.name})

    def mutate(self, graph: Graph, rng: random.Random) -> Graph:
        nodes = list(graph.nodes)
        index = rng.randrange(len(nodes))
        old = nodes[index]
        choices = [op for op in self.operations if op != old.op]
        nodes[index] = Node(old.id, rng.choice(choices), old.inputs, old.output, old.attributes)
        return Graph(graph.inputs, tuple(nodes), graph.outputs, graph.metadata)

    def validate(self, graph: Graph):
        known = set(graph.inputs)
        for node in graph.nodes:
            if node.op not in self.operations:
                yield f"unsupported operation: {node.op}"
            missing = set(node.inputs) - known
            if missing:
                yield f"{node.id} has unknown inputs: {sorted(missing)}"
            known.add(node.id)
        if set(graph.outputs) - known:
            yield "graph contains unknown outputs"

    def emit(self, graph: Graph, output_dir: Path) -> ProgramArtifact:
        output_dir.mkdir(parents=True, exist_ok=True)
        expressions = {"x": "x", "y": "y"}
        op_expr = {
            "add": "[a + b for a, b in zip({0}, {1})]",
            "sub": "[a - b for a, b in zip({0}, {1})]",
            "mul": "[a * b for a, b in zip({0}, {1})]",
            "max": "[max(a, b) for a, b in zip({0}, {1})]",
        }
        lines = ["import json", "x = [1.0, -2.0, 3.0, 4.0]", "y = [2.0, 3.0, -1.0, 0.5]"]
        for node in graph.nodes:
            left, right = (expressions[x] for x in node.inputs)
            lines.append(f"{node.id} = {op_expr[node.op].format(left, right)}")
            expressions[node.id] = node.id
        lines.append(f"print(json.dumps({expressions[graph.outputs[0]]}))")
        script = output_dir / "case.py"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ProgramArtifact(script, (script,), run_command=(sys.executable, str(script.resolve())))

    def observe(self, artifact: ProgramArtifact, result: ExecutionResult):
        yield f"result:{result.kind.value}"
        if result.run and result.run.ok:
            yield f"output:{result.run.log_tail.strip()}"
