from __future__ import annotations

import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from .model import ExecutionResult, Graph, MetamorphicVariant, ProgramArtifact


class LanguageAdapter(ABC):
    """The only language-specific boundary in the ForgeFuzz core."""

    name: str

    @abstractmethod
    def generate(self, rng: random.Random) -> Graph:
        """Create a valid seed graph from the adapter's API catalog."""

    @abstractmethod
    def mutate(self, graph: Graph, rng: random.Random) -> Graph:
        """Return a mutated graph while preserving required constraints."""

    def validate(self, graph: Graph) -> Iterable[str]:
        """Yield validation errors. An empty iterable means valid."""
        return ()

    @abstractmethod
    def emit(self, graph: Graph, output_dir: Path) -> ProgramArtifact:
        """Fill language APIs and emit a standalone, replayable program."""

    def observe(self, artifact: ProgramArtifact, result: ExecutionResult) -> Iterable[str]:
        """Return coverage/novelty features after execution."""
        return (f"result:{result.kind.value}",)

    def oracle(self, artifact: ProgramArtifact, result: ExecutionResult) -> ExecutionResult:
        """Classify semantic mismatches after a successful process run.

        Override this for differential, metamorphic, invariant, or custom
        output checking. Process failures have already been classified.
        """
        return result

    def metamorphic_variants(
        self, graph: Graph, rng: random.Random,
    ) -> Iterable[MetamorphicVariant]:
        """Produce relation-preserving graphs. The default disables this stage."""
        return ()

    def metamorphic_oracle(
        self,
        base_artifact: ProgramArtifact,
        base_result: ExecutionResult,
        variant: MetamorphicVariant,
        variant_artifact: ProgramArtifact,
        variant_result: ExecutionResult,
    ) -> ExecutionResult:
        """Compare a successful base/variant pair and return the pair verdict."""
        return variant_result
