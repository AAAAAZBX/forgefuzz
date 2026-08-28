from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import ExecutionResult, Graph, ProcessResult


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def graph_id(graph: Graph) -> str:
    return hashlib.sha256(canonical_json(graph.to_dict()).encode()).hexdigest()[:16]


def failure_fingerprint(stage: str, text: str) -> str:
    meaningful = [line.strip() for line in text.splitlines() if line.strip()][-12:]
    return hashlib.sha256(f"{stage}\n{' '.join(meaningful)}".encode()).hexdigest()[:20]


def _process(value: ProcessResult | None) -> dict[str, Any] | None:
    if value is None:
        return None
    data = asdict(value)
    data["log_path"] = str(value.log_path)
    return data


class Corpus:
    def __init__(self, root: Path):
        self.root = root
        self.queue = root / "queue"
        self.failures = root / "failures"
        self.queue.mkdir(parents=True, exist_ok=True)
        self.failures.mkdir(parents=True, exist_ok=True)

    def load_graphs(self) -> list[Graph]:
        graphs: list[Graph] = []
        for path in sorted(self.queue.glob("*.json")):
            try:
                graphs.append(Graph.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return graphs

    def persist(self, case_dir: Path, graph: Graph, result: ExecutionResult, interesting: bool) -> None:
        summary = {
            "graph_id": graph_id(graph), "kind": result.kind.value, "stage": result.stage,
            "message": result.message, "features": sorted(result.features),
            "fingerprint": result.fingerprint, "compile": _process(result.compile), "run": _process(result.run),
        }
        (case_dir / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if interesting:
            target = self.queue / f"{graph_id(graph)}.json"
            target.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
        if not result.success:
            target = self.failures / f"{result.fingerprint or graph_id(graph)}.json"
            target.write_text(json.dumps({"graph": graph.to_dict(), "result": summary}, indent=2), encoding="utf-8")
