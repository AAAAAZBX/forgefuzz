from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class TensorType:
    dtype: str
    shape: tuple[int | str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TensorType":
        return cls(dtype=str(value["dtype"]), shape=tuple(value["shape"]))


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    op: str
    inputs: tuple[str, ...]
    output: TensorType
    attributes: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Node":
        return cls(
            id=str(value["id"]), op=str(value["op"]), inputs=tuple(value["inputs"]),
            output=TensorType.from_dict(value["output"]),
            attributes=dict(value.get("attributes", {})),
        )


@dataclass(frozen=True, slots=True)
class Graph:
    inputs: dict[str, TensorType]
    nodes: tuple[Node, ...]
    outputs: tuple[str, ...]
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def edge_count(self) -> int:
        return sum(len(node.inputs) for node in self.nodes)

    @property
    def depth(self) -> int:
        depths = {name: 0 for name in self.inputs}
        for node in self.nodes:
            depths[node.id] = 1 + max(depths[name] for name in node.inputs)
        return max((depths[name] for name in self.outputs), default=0)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Graph":
        return cls(
            inputs={name: TensorType.from_dict(kind) for name, kind in value["inputs"].items()},
            nodes=tuple(Node.from_dict(node) for node in value["nodes"]),
            outputs=tuple(value["outputs"]), metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class MetamorphicVariant:
    """A graph that must preserve a declared relation with its base graph."""

    id: str
    relation: str
    graph: Graph
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProgramArtifact:
    entrypoint: Path
    files: tuple[Path, ...]
    compile_command: tuple[str, ...] | None = None
    run_command: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, JsonValue] = field(default_factory=dict)


class FailureKind(str, Enum):
    SUCCESS = "success"
    INVALID = "invalid"
    EMIT_FAILURE = "emit_failure"
    COMPILE_FAILURE = "compile_failure"
    RUNTIME_FAILURE = "runtime_failure"
    TIMEOUT = "timeout"
    OUTPUT_MISMATCH = "output_mismatch"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int | None
    duration_seconds: float
    timed_out: bool
    log_path: Path
    log_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    kind: FailureKind
    stage: str
    message: str = ""
    compile: ProcessResult | None = None
    run: ProcessResult | None = None
    features: frozenset[str] = frozenset()
    fingerprint: str | None = None

    @property
    def success(self) -> bool:
        return self.kind is FailureKind.SUCCESS
